# app/api/dependencies.py
"""
FastAPI dependencies for authentication, user context, and permission checking.
Provides clean injection of user context into route handlers.
"""
import logging
from typing import Optional, Dict, Any
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.core.exceptions import AuthenticationError, NotFoundError, ValidationError
from app.core.container import get_billing_service as _get_billing_service
from app.services.auth_service import AuthService
from app.services.user_service import UserService
from app.data.repositories.user_repository import UserRepository


logger = logging.getLogger(__name__)

# Security scheme for JWT tokens
security = HTTPBearer(auto_error=False)

# Global service instances (would be properly injected in production)
user_repository = UserRepository()
auth_service = AuthService(user_repository)
user_service = UserService(
    user_repository=user_repository,
    billing_service=None,  # Will be injected when needed
    billing_repository=None,
    email_repository=None,
    gmail_repository=None
)


class UserContext:
    """
    User context object passed to route handlers.
    Contains authenticated user info and permissions.
    """
    def __init__(self, user_data: Dict[str, Any], permissions: Dict[str, bool]):
        self.user_id = user_data.get("user_id")
        self.email = user_data.get("email")
        self.display_name = user_data.get("display_name")
        self.credits_remaining = user_data.get("credits_remaining", 0)
        self.bot_enabled = user_data.get("bot_enabled", False)
        self.timezone = user_data.get("timezone", "UTC")
        self.created_at = user_data.get("created_at")
        
        # Permissions
        self.can_process_emails = permissions.get("can_process_emails", False)
        self.can_access_dashboard = permissions.get("can_access_dashboard", False)
        self.can_connect_gmail = permissions.get("can_connect_gmail", False)
        self.can_purchase_credits = permissions.get("can_purchase_credits", False)
        
        # Raw data for services
        self._raw_user_data = user_data
        self._raw_permissions = permissions
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON responses"""
        return {
            "user_id": self.user_id,
            "email": self.email,
            "display_name": self.display_name,
            "credits_remaining": self.credits_remaining,
            "bot_enabled": self.bot_enabled,
            "timezone": self.timezone,
            "created_at": self.created_at,
            "permissions": {
                "can_process_emails": self.can_process_emails,
                "can_access_dashboard": self.can_access_dashboard,
                "can_connect_gmail": self.can_connect_gmail,
                "can_purchase_credits": self.can_purchase_credits
            }
        }


# --- Authentication Dependencies ---

async def get_auth_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> str:
    """
    Extract JWT token from Authorization header.
    Raises 401 if no token provided.
    """
    if not credentials:
        raise HTTPException(
            status_code=401,
            detail="Authorization header required",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    return credentials.credentials


async def get_current_user(
    token: str = Depends(get_auth_token)
) -> Dict[str, Any]:
    """
    Get current user from JWT token.
    Validates token and returns user profile.
    """
    try:
        user_data = await auth_service.get_current_user(token)
        logger.info(f"Authenticated user: {user_data.get('user_id')}")
        return user_data
    
    except AuthenticationError as e:
        logger.warning(f"Authentication failed: {e}")
        raise HTTPException(
            status_code=401,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    except Exception as e:
        logger.error(f"Authentication error: {e}")
        raise HTTPException(
            status_code=401,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"}
        )


async def get_user_context(
    user_data: Dict[str, Any] = Depends(get_current_user)
) -> UserContext:
    """
    Create user context with permissions.
    This is the main dependency for route handlers.
    """
    try:
        # Get permissions
        permissions = {
            "can_process_emails": auth_service.check_user_permissions(user_data, "email_processing")["allowed"],
            "can_access_dashboard": auth_service.check_user_permissions(user_data, "dashboard_access")["allowed"],
            "can_connect_gmail": auth_service.check_user_permissions(user_data, "gmail_connection")["allowed"],
            "can_purchase_credits": auth_service.check_user_permissions(user_data, "credit_purchase")["allowed"]
        }
        
        return UserContext(user_data, permissions)
    
    except Exception as e:
        logger.error(f"Failed to create user context: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to create user context"
        )


# --- Permission Dependencies ---

async def require_email_processing_permission(
    context: UserContext = Depends(get_user_context)
) -> UserContext:
    """
    Require email processing permission.
    Raises 403 if user cannot process emails.
    """
    if not context.can_process_emails:
        if context.credits_remaining <= 0:
            raise HTTPException(
                status_code=402,  # Payment Required
                detail="Insufficient credits for email processing"
            )
        elif not context.bot_enabled:
            raise HTTPException(
                status_code=403,
                detail="Bot is disabled. Enable bot to process emails."
            )
        else:
            raise HTTPException(
                status_code=403,
                detail="Email processing not allowed"
            )
    
    return context


async def require_dashboard_access(
    context: UserContext = Depends(get_user_context)
) -> UserContext:
    """
    Require dashboard access permission.
    Should always be allowed for authenticated users.
    """
    if not context.can_access_dashboard:
        raise HTTPException(
            status_code=403,
            detail="Dashboard access not allowed"
        )
    
    return context


async def require_gmail_connection_permission(
    context: UserContext = Depends(get_user_context)
) -> UserContext:
    """
    Require Gmail connection permission.
    Should always be allowed for authenticated users.
    """
    if not context.can_connect_gmail:
        raise HTTPException(
            status_code=403,
            detail="Gmail connection not allowed"
        )
    
    return context


async def require_credit_purchase_permission(
    context: UserContext = Depends(get_user_context)
) -> UserContext:
    """
    Require credit purchase permission.
    Should always be allowed for authenticated users.
    """
    if not context.can_purchase_credits:
        raise HTTPException(
            status_code=403,
            detail="Credit purchase not allowed"
        )
    
    return context


# --- Rate Limiting Dependencies ---

async def check_rate_limit(
    request: Request,
    context: UserContext = Depends(get_user_context)
) -> UserContext:
    """
    Check rate limits for authenticated users.
    80 emails/day limit with buffer for processing.
    """
    try:
        # Get client IP
        client_ip = request.client.host if request.client else "unknown"
        
        # Check rate limit (80 requests per day per user)
        rate_limit_result = auth_service.check_rate_limit(
            identifier=context.user_id,
            action="api_request"
        )
        
        if not rate_limit_result["allowed"]:
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded. Please try again later.",
                headers={
                    "X-RateLimit-Limit": "80",
                    "X-RateLimit-Remaining": str(rate_limit_result["remaining"]),
                    "X-RateLimit-Reset": rate_limit_result["reset_time"]
                }
            )
        
        # Add rate limit headers to successful responses
        # (This would be handled by middleware in production)
        
        return context
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Rate limit check failed: {e}")
        # Don't fail on rate limit errors - just log and continue
        return context


# --- Optional Dependencies ---

async def get_optional_user_context(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> Optional[UserContext]:
    """
    Get user context if token is provided, otherwise return None.
    Useful for endpoints that work with or without authentication.
    """
    if not credentials:
        return None
    
    try:
        user_data = await auth_service.get_current_user(credentials.credentials)
        permissions = {
            "can_process_emails": auth_service.check_user_permissions(user_data, "email_processing")["allowed"],
            "can_access_dashboard": auth_service.check_user_permissions(user_data, "dashboard_access")["allowed"],
            "can_connect_gmail": auth_service.check_user_permissions(user_data, "gmail_connection")["allowed"],
            "can_purchase_credits": auth_service.check_user_permissions(user_data, "credit_purchase")["allowed"]
        }
        
        return UserContext(user_data, permissions)
    
    except Exception as e:
        logger.warning(f"Optional authentication failed: {e}")
        return None


# --- Service Dependencies ---

async def get_user_service(
    context: UserContext = Depends(get_user_context)
) -> UserService:
    """
    Get UserService instance for the current user.
    Useful for routes that need user-specific operations.
    """
    return user_service

async def get_billing_service():
    """Get billing service with proper dependency injection"""
    return _get_billing_service()

# --- Request Context Dependencies ---

async def get_request_context(
    request: Request,
    context: UserContext = Depends(get_user_context)
) -> Dict[str, Any]:
    """
    Get request context with user info and request metadata.
    Useful for audit logging and analytics.
    """
    return {
        "user_id": context.user_id,
        "request_id": id(request),  # Simple request ID
        "method": request.method,
        "url": str(request.url),
        "client_ip": request.client.host if request.client else "unknown",
        "user_agent": request.headers.get("user-agent", "unknown"),
        "timestamp": None  # Would be set by middleware
    }


# --- Admin Dependencies ---

async def require_admin_access(
    context: UserContext = Depends(get_user_context)
) -> UserContext:
    """
    Require admin access.
    For now, just checks if user exists (placeholder).
    """
    # In production, this would check for admin role
    # For now, just verify user is authenticated
    if not context.user_id:
        raise HTTPException(
            status_code=403,
            detail="Admin access required"
        )
    
    return context


# --- Validation Dependencies ---

async def validate_user_ownership(
    user_id: str,
    context: UserContext = Depends(get_user_context)
) -> UserContext:
    """
    Validate that the current user owns the resource.
    Prevents users from accessing other users' data.
    """
    if context.user_id != user_id:
        raise HTTPException(
            status_code=403,
            detail="Access denied. You can only access your own data."
        )
    
    return context


# --- Health Check Dependencies ---

async def no_auth_required() -> bool:
    """
    Dependency for endpoints that don't require authentication.
    Always returns True. Used for health checks and public endpoints.
    """
    return True


# --- Utility Functions ---

def get_error_response(error: Exception) -> Dict[str, Any]:
    """
    Convert exception to API error response.
    """
    if isinstance(error, ValidationError):
        return {
            "error": "validation_error",
            "message": str(error),
            "status_code": 422
        }
    elif isinstance(error, NotFoundError):
        return {
            "error": "not_found",
            "message": str(error),
            "status_code": 404
        }
    elif isinstance(error, AuthenticationError):
        return {
            "error": "authentication_error",
            "message": str(error),
            "status_code": 401
        }
    else:
        return {
            "error": "internal_error",
            "message": "An unexpected error occurred",
            "status_code": 500
        }


# --- Example Usage in Routes ---

# @app.get("/api/dashboard/data")
# async def get_dashboard_data(
#     context: UserContext = Depends(require_dashboard_access)
# ):
#     return {"user_id": context.user_id, "credits": context.credits_remaining}

# @app.post("/api/email/process")
# async def process_email(
#     context: UserContext = Depends(require_email_processing_permission)
# ):
#     # User has sufficient credits and bot is enabled
#     return {"status": "processing"}

# @app.get("/api/health")
# async def health_check(
#     _: bool = Depends(no_auth_required)
# ):
#     return {"status": "healthy"}