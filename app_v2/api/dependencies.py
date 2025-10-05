# app_v2/api/dependencies.py
"""
PHOENIX DEPENDENCIES - Clean FastAPI Dependencies
Simple, focused dependency injection for the new clean architecture.
"""
import logging
from typing import Optional
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app_v2.services.auth_service import create_auth_service
from app_v2.services.gmail_service import create_gmail_service

logger = logging.getLogger(__name__)

# Security scheme for Bearer tokens
security = HTTPBearer(auto_error=False)


# ========== SERVICE DEPENDENCIES ==========

def get_auth_service():
    """Get AuthService instance."""
    return create_auth_service()


def get_gmail_service():
    """Get GmailService instance."""
    return create_gmail_service()


# ========== AUTHENTICATION DEPENDENCIES ==========

async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    auth_service = Depends(get_auth_service)
):
    """
    Get current authenticated user from Supabase JWT.
    Raises 401 if not authenticated.
    """
    if not credentials:
        raise HTTPException(
            status_code=401,
            detail="Missing authentication token"
        )

    try:
        user_context = await auth_service.get_current_user(credentials.credentials)
        return user_context
    except Exception as e:
        logger.warning(f"Authentication failed: {e}")
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token"
        )


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    auth_service = Depends(get_auth_service)
):
    """
    Get current user if authenticated, None otherwise.
    Does not raise errors for unauthenticated requests.
    """
    if not credentials:
        return None

    try:
        user_context = await auth_service.get_current_user(credentials.credentials)
        return user_context
    except Exception as e:
        logger.info(f"Optional authentication failed: {e}")
        return None


# ========== PERMISSION DEPENDENCIES ==========

def require_gmail_access(user = Depends(get_current_user)):
    """Require user to have Gmail access permissions."""
    if not user.get("permissions", {}).get("can_connect_gmail", False):
        raise HTTPException(
            status_code=403,
            detail="Gmail access not permitted"
        )
    return user


def require_email_processing(user = Depends(get_current_user)):
    """Require user to have email processing permissions."""
    if not user.get("permissions", {}).get("can_process_emails", False):
        raise HTTPException(
            status_code=403,
            detail="Email processing not permitted - bot may be disabled or no credits"
        )
    return user


# ========== UTILITY DEPENDENCIES ==========

def get_request_info(request: Request):
    """Extract request information for logging/auditing."""
    return {
        "ip_address": request.client.host if request.client else "unknown",
        "user_agent": request.headers.get("user-agent", "unknown"),
        "method": request.method,
        "path": str(request.url.path)
    }


def no_auth_required() -> bool:
    """
    Dependency for endpoints that explicitly don't require authentication.
    Makes it clear in the endpoint signature.
    """
    return True