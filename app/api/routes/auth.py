# app/api/routes/auth.py
"""
Authentication routes for user login, registration, and JWT management.
Handles Supabase JWT tokens and user profile creation.
"""
import logging
from typing import Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field

from app.api.dependencies import (
    get_current_user,
    get_user_context,
    get_optional_user_context,
    UserContext,
    no_auth_required
)
from app.services.auth_service import AuthService
from app.services.user_service import UserService
from app.data.repositories.user_repository import UserRepository
from app.core.exceptions import AuthenticationError, ValidationError, NotFoundError

logger = logging.getLogger(__name__)

# Initialize services
user_repository = UserRepository()
auth_service = AuthService(user_repository)
user_service = UserService(
    user_repository=user_repository,
    billing_service=None,  # Will be injected when needed
    billing_repository=None,
    email_repository=None,
    gmail_repository=None
)

router = APIRouter(
    prefix="/auth",
    tags=["authentication"],
    responses={
        401: {"description": "Authentication failed"},
        422: {"description": "Validation error"}
    }
)


# --- Request/Response Models ---

class TokenRequest(BaseModel):
    """Request model for token validation"""
    token: str = Field(..., description="JWT token to validate")


class TokenResponse(BaseModel):
    """Response model for token validation"""
    valid: bool = Field(..., description="Whether token is valid")
    user_id: Optional[str] = Field(None, description="User ID if token is valid")
    email: Optional[str] = Field(None, description="User email if token is valid")
    expires_at: Optional[str] = Field(None, description="Token expiration time")


class UserProfileResponse(BaseModel):
    """Response model for user profile"""
    user_id: str
    email: str
    display_name: Optional[str] = None
    credits_remaining: int
    bot_enabled: bool
    timezone: str
    created_at: str
    permissions: Dict[str, bool]


class LoginRequest(BaseModel):
    """Request model for login (for testing/development)"""
    email: EmailStr = Field(..., description="User email address")
    password: str = Field(..., min_length=8, description="User password")


class RegisterRequest(BaseModel):
    """Request model for registration"""
    email: EmailStr = Field(..., description="User email address")
    display_name: Optional[str] = Field(None, description="User display name")
    timezone: str = Field("UTC", description="User timezone")


class SessionRequest(BaseModel):
    """Request model for session creation"""
    access_token: str = Field(..., description="Supabase access token")
    refresh_token: Optional[str] = Field(None, description="Supabase refresh token")
    token_type: str = Field("bearer", description="Token type")
    expires_in: int = Field(3600, description="Token expiration in seconds")


class SessionResponse(BaseModel):
    """Response model for session creation"""
    success: bool
    user_id: str
    email: str
    needs_gmail: bool = False
    message: str


# --- Authentication Endpoints ---

@router.post("/validate-token", response_model=TokenResponse)
async def validate_token(
    request: TokenRequest
) -> TokenResponse:
    """
    Validate a JWT token and return user info.
    Used by frontend to check if token is still valid.
    """
    try:
        # Validate the token
        token_data = auth_service.validate_jwt_token(request.token)
        
        logger.info(f"Token validated for user: {token_data.get('user_id')}")
        
        return TokenResponse(
            valid=True,
            user_id=token_data.get("user_id"),
            email=token_data.get("email"),
            expires_at=token_data.get("expires_at")
        )
    
    except AuthenticationError as e:
        logger.warning(f"Token validation failed: {e}")
        return TokenResponse(valid=False)
    
    except Exception as e:
        logger.error(f"Token validation error: {e}")
        return TokenResponse(valid=False)


@router.get("/me", response_model=UserProfileResponse)
async def get_current_user_profile(
    context: UserContext = Depends(get_user_context)
) -> UserProfileResponse:
    """
    Get current user profile information.
    Returns user data and permissions.
    """
    try:
        # Get full user profile
        user_profile = await user_service.get_user_profile(context.user_id)
        
        return UserProfileResponse(
            user_id=context.user_id,
            email=context.email,
            display_name=context.display_name,
            credits_remaining=context.credits_remaining,
            bot_enabled=context.bot_enabled,
            timezone=context.timezone,
            created_at=context.created_at,
            permissions={
                "can_process_emails": context.can_process_emails,
                "can_access_dashboard": context.can_access_dashboard,
                "can_connect_gmail": context.can_connect_gmail,
                "can_purchase_credits": context.can_purchase_credits
            }
        )
    
    except NotFoundError:
        raise HTTPException(
            status_code=404,
            detail="User profile not found"
        )


@router.post("/create-session", response_model=SessionResponse)
async def create_session(
    request: SessionRequest,
    http_request: Request
) -> SessionResponse:
    """
    Create a user session from Supabase tokens.
    Called by frontend after successful OAuth login.
    """
    try:
        # Decode the JWT token to get user info
        jwt_payload = auth_service._decode_jwt_token(request.access_token)
        
        # Get or create user profile
        user_profile = auth_service.get_or_create_user_profile(jwt_payload)
        
        # Create session
        session_data = {
            "ip_address": http_request.client.host if http_request.client else "unknown",
            "user_agent": http_request.headers.get("user-agent", "unknown")
        }
        
        session = auth_service.create_user_session(user_profile, session_data)
        
        # Log successful login
        auth_service.audit_log_authentication(
            user_profile, 
            "login_success", 
            {
                "method": "supabase_jwt",
                "ip_address": session_data["ip_address"],
                "user_agent": session_data["user_agent"]
            }
        )
        
        logger.info(f"Session created for user: {user_profile['user_id']}")
        
        # Check if user needs Gmail setup
        needs_gmail = not user_profile.get("gmail_connected", False)
        
        return SessionResponse(
            success=True,
            user_id=user_profile["user_id"],
            email=user_profile["email"],
            needs_gmail=needs_gmail,
            message="Session created successfully"
        )
    
    except AuthenticationError as e:
        logger.warning(f"Session creation failed: {e}")
        raise HTTPException(
            status_code=401,
            detail=str(e)
        )
    
    except ValidationError as e:
        logger.warning(f"Invalid session data: {e}")
        raise HTTPException(
            status_code=422,
            detail=str(e)
        )
    
    except Exception as e:
        logger.error(f"Session creation error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to create session"
        )


@router.post("/logout")
async def logout(
    context: UserContext = Depends(get_user_context)
) -> Dict[str, Any]:
    """
    Log out current user and invalidate sessions.
    """
    try:
        # Invalidate all user sessions
        result = auth_service.invalidate_all_user_sessions(context.user_id)
        
        # Log logout
        auth_service.audit_log_authentication(
            context._raw_user_data,
            "logout_success",
            {
                "sessions_invalidated": result["invalidated_count"]
            }
        )
        
        logger.info(f"User logged out: {context.user_id}")
        
        return {
            "success": True,
            "message": "Logged out successfully",
            "sessions_invalidated": result["invalidated_count"]
        }
    
    except Exception as e:
        logger.error(f"Logout error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to logout"
        )


@router.post("/refresh")
async def refresh_token(
    context: UserContext = Depends(get_user_context)
) -> Dict[str, Any]:
    """
    Refresh user profile data from latest JWT.
    Updates cached user information.
    """
    try:
        # This would typically involve calling Supabase to refresh the JWT
        # For now, we'll just return current user data
        
        logger.info(f"Token refresh requested for user: {context.user_id}")
        
        return {
            "success": True,
            "user_id": context.user_id,
            "email": context.email,
            "display_name": context.display_name,
            "credits_remaining": context.credits_remaining,
            "bot_enabled": context.bot_enabled,
            "message": "Profile refreshed successfully"
        }
    
    except Exception as e:
        logger.error(f"Token refresh error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to refresh token"
        )


# --- Development/Testing Endpoints ---

@router.post("/login", response_model=Dict[str, Any])
async def login_for_testing(
    request: LoginRequest,
    http_request: Request
) -> Dict[str, Any]:
    """
    Login endpoint for testing/development.
    In production, authentication goes through Supabase directly.
    """
    try:
        # This is a mock login for testing
        # In production, users would authenticate through Supabase UI
        
        if request.email == "test@example.com" and request.password == "password123":
            # Create mock user profile
            user_data = {
                "user_id": "test-user-123",
                "email": request.email,
                "display_name": "Test User",
                "credits_remaining": 50,
                "bot_enabled": True,
                "timezone": "UTC"
            }
            
            # Create session
            session_data = {
                "ip_address": http_request.client.host if http_request.client else "unknown",
                "user_agent": http_request.headers.get("user-agent", "unknown")
            }
            
            session = auth_service.create_user_session(user_data, session_data)
            
            logger.info(f"Test login successful for: {request.email}")
            
            return {
                "success": True,
                "message": "Login successful",
                "user_id": user_data["user_id"],
                "session_id": session["session_id"],
                "mock_token": "mock-jwt-token-for-testing"
            }
        else:
            raise AuthenticationError("Invalid credentials")
    
    except AuthenticationError as e:
        logger.warning(f"Test login failed: {e}")
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password"
        )
    
    except Exception as e:
        logger.error(f"Test login error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Login failed"
        )


@router.post("/register", response_model=Dict[str, Any])
async def register_for_testing(
    request: RegisterRequest
) -> Dict[str, Any]:
    """
    Registration endpoint for testing/development.
    In production, users register through Supabase directly.
    """
    try:
        # This is a mock registration for testing
        # In production, users would register through Supabase UI
        
        # Create user profile
        user_data = {
            "user_id": f"user-{hash(request.email)}",
            "email": request.email,
            "display_name": request.display_name,
            "timezone": request.timezone,
            "credits_remaining": 5,  # Starter credits
            "bot_enabled": True
        }
        
        # Create profile in repository
        profile = await user_service.create_user_profile(user_data)
        
        logger.info(f"Test registration successful for: {request.email}")
        
        return {
            "success": True,
            "message": "Registration successful",
            "user_id": profile["user_id"],
            "email": profile["email"],
            "credits_remaining": profile["credits_remaining"]
        }
    
    except ValidationError as e:
        logger.warning(f"Test registration validation failed: {e}")
        raise HTTPException(
            status_code=422,
            detail=str(e)
        )
    
    except Exception as e:
        logger.error(f"Test registration error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Registration failed"
        )


# --- Session Management ---

@router.get("/sessions")
async def get_user_sessions(
    context: UserContext = Depends(get_user_context)
) -> Dict[str, Any]:
    """
    Get all active sessions for current user.
    """
    try:
        sessions = auth_service.get_user_sessions(context.user_id)
        
        # Remove sensitive data
        safe_sessions = []
        for session in sessions:
            safe_sessions.append({
                "session_id": session["session_id"],
                "ip_address": session.get("ip_address", "unknown"),
                "user_agent": session.get("user_agent", "unknown"),
                "created_at": session["created_at"],
                "expires_at": session["expires_at"]
            })
        
        return {
            "success": True,
            "sessions": safe_sessions,
            "total_sessions": len(safe_sessions)
        }
    
    except Exception as e:
        logger.error(f"Get sessions error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to get sessions"
        )


@router.delete("/sessions/{session_id}")
async def invalidate_session(
    session_id: str,
    context: UserContext = Depends(get_user_context)
) -> Dict[str, Any]:
    """
    Invalidate a specific session.
    """
    try:
        # Verify the session belongs to the current user
        sessions = auth_service.get_user_sessions(context.user_id)
        session_exists = any(s["session_id"] == session_id for s in sessions)
        
        if not session_exists:
            raise HTTPException(
                status_code=404,
                detail="Session not found or doesn't belong to current user"
            )
        
        # Invalidate the session
        success = auth_service.invalidate_user_session(session_id)
        
        if success:
            logger.info(f"Session invalidated: {session_id}")
            return {
                "success": True,
                "message": "Session invalidated successfully"
            }
        else:
            raise HTTPException(
                status_code=404,
                detail="Session not found"
            )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Invalidate session error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to invalidate session"
        )


# --- Security Endpoints ---

@router.get("/audit-log")
async def get_user_audit_log(
    context: UserContext = Depends(get_user_context),
    limit: int = 50
) -> Dict[str, Any]:
    """
    Get authentication audit log for current user.
    """
    try:
        if limit > 100:
            limit = 100  # Cap at 100 entries
        
        audit_logs = auth_service.get_user_audit_logs(context.user_id, limit=limit)
        
        return {
            "success": True,
            "audit_logs": audit_logs,
            "total_entries": len(audit_logs),
            "user_id": context.user_id
        }
    
    except Exception as e:
        logger.error(f"Get audit log error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to get audit log"
        )


@router.post("/change-password")
async def change_password(
    context: UserContext = Depends(get_user_context)
) -> Dict[str, Any]:
    """
    Change password endpoint (placeholder).
    In production, this would integrate with Supabase Auth.
    """
    try:
        # This would typically call Supabase Auth to change password
        # For now, return a placeholder response
        
        logger.info(f"Password change requested for user: {context.user_id}")
        
        return {
            "success": True,
            "message": "Password change functionality not implemented. Please use Supabase Auth UI."
        }
    
    except Exception as e:
        logger.error(f"Change password error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Password change failed"
        )


# --- Public Endpoints ---

@router.get("/status")
async def auth_status(
    context: Optional[UserContext] = Depends(get_optional_user_context)
) -> Dict[str, Any]:
    """
    Get authentication status.
    Works with or without authentication.
    """
    if context:
        return {
            "authenticated": True,
            "user_id": context.user_id,
            "email": context.email,
            "permissions": {
                "can_process_emails": context.can_process_emails,
                "can_access_dashboard": context.can_access_dashboard,
                "can_connect_gmail": context.can_connect_gmail,
                "can_purchase_credits": context.can_purchase_credits
            }
        }
    else:
        return {
            "authenticated": False,
            "message": "No valid authentication token provided"
        }


@router.get("/health")
async def auth_health(
    _: bool = Depends(no_auth_required)
) -> Dict[str, Any]:
    """
    Health check for authentication service.
    """
    try:
        # Check auth service health
        stats = auth_service.get_auth_statistics()
        
        return {
            "status": "healthy",
            "service": "authentication",
            "total_users": stats["total_users"],
            "active_sessions": stats["active_sessions"],
            "success_rate": stats["success_rate"]
        }
    
    except Exception as e:
        logger.error(f"Auth health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e)
        }


# --- Example Usage ---

# from fastapi import FastAPI
# from app.api.routes.auth import router as auth_router
# 
# app = FastAPI()
# app.include_router(auth_router)
# 
# # Available endpoints:
# # POST /auth/validate-token - Validate JWT token
# # GET /auth/me - Get current user profile
# # POST /auth/create-session - Create session from Supabase tokens
# # POST /auth/logout - Log out and invalidate sessions
# # POST /auth/refresh - Refresh user profile
# # POST /auth/login - Login for testing
# # POST /auth/register - Register for testing
# # GET /auth/sessions - Get user sessions
# # DELETE /auth/sessions/{id} - Invalidate session
# # GET /auth/audit-log - Get authentication audit log
# # POST /auth/change-password - Change password (placeholder)
# # GET /auth/status - Get authentication status
# # GET /auth/health - Authentication service health