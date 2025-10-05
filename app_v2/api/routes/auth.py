# app_v2/api/routes/auth.py
"""
PHOENIX AUTH ROUTES - Clean Supabase Auth Integration
Simple, focused authentication endpoints that work with Supabase Auth.

PRINCIPLES:
- No custom login/register (use Supabase Auth UI)
- JWT validation only (no token generation)
- Clean user profile management
- Proper error handling
"""
import logging
from typing import Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app_v2.api.dependencies import (
    get_current_user,
    get_optional_user,
    get_auth_service,
    no_auth_required
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/auth",
    tags=["authentication"]
)


# ========== REQUEST/RESPONSE MODELS ==========

class UserProfileResponse(BaseModel):
    """Response model for user profile."""
    user_id: str
    email: str
    display_name: Optional[str] = None
    timezone: str
    bot_enabled: bool
    created_at: str
    permissions: Dict[str, bool]


class UpdateProfileRequest(BaseModel):
    """Request model for profile updates."""
    display_name: Optional[str] = None
    timezone: Optional[str] = None
    bot_enabled: Optional[bool] = None


class HealthResponse(BaseModel):
    """Response model for health check."""
    status: str
    service: str
    timestamp: str


# ========== AUTHENTICATION ENDPOINTS ==========

@router.get("/me", response_model=UserProfileResponse)
async def get_current_user_profile(
    user = Depends(get_current_user)
) -> UserProfileResponse:
    """
    Get current user profile information.
    Requires valid Supabase JWT token.
    """
    return UserProfileResponse(
        user_id=user["user_id"],
        email=user["email"],
        display_name=user["display_name"],
        timezone=user["timezone"],
        bot_enabled=user["bot_enabled"],
        created_at=user["created_at"],
        permissions=user["permissions"]
    )


@router.put("/me", response_model=UserProfileResponse)
async def update_user_profile(
    updates: UpdateProfileRequest,
    user = Depends(get_current_user),
    auth_service = Depends(get_auth_service)
) -> UserProfileResponse:
    """
    Update current user profile.
    """
    try:
        # Convert to dict, excluding None values
        update_data = {
            k: v for k, v in updates.dict().items()
            if v is not None
        }

        if not update_data:
            raise HTTPException(
                status_code=400,
                detail="No valid updates provided"
            )

        # Update profile
        updated_user = await auth_service.update_user_profile(
            user["user_id"],
            update_data
        )

        logger.info(f"Updated profile for user {user['user_id']}")

        return UserProfileResponse(
            user_id=updated_user["user_id"],
            email=updated_user["email"],
            display_name=updated_user["display_name"],
            timezone=updated_user["timezone"],
            bot_enabled=updated_user["bot_enabled"],
            created_at=updated_user.get("created_at", user["created_at"]),
            permissions=updated_user["permissions"]
        )

    except Exception as e:
        logger.error(f"Failed to update profile for {user['user_id']}: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to update profile"
        )


@router.delete("/me")
async def delete_user_account(
    user = Depends(get_current_user),
    auth_service = Depends(get_auth_service)
) -> Dict[str, Any]:
    """
    Delete current user account and all associated data.
    WARNING: This action is irreversible.
    """
    try:
        success = await auth_service.delete_user_account(user["user_id"])

        if success:
            logger.info(f"Deleted user account: {user['user_id']}")
            return {
                "success": True,
                "message": "User account deleted successfully"
            }
        else:
            raise HTTPException(
                status_code=500,
                detail="Failed to delete user account"
            )

    except Exception as e:
        logger.error(f"Failed to delete account for {user['user_id']}: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to delete user account"
        )


# ========== STATUS ENDPOINTS ==========

@router.get("/status")
async def auth_status(
    user = Depends(get_optional_user)
) -> Dict[str, Any]:
    """
    Get authentication status.
    Works with or without authentication.
    """
    if user:
        return {
            "authenticated": True,
            "user_id": user["user_id"],
            "email": user["email"],
            "display_name": user["display_name"],
            "permissions": user["permissions"]
        }
    else:
        return {
            "authenticated": False,
            "message": "No valid authentication token provided"
        }


@router.get("/health", response_model=HealthResponse)
async def auth_health(
    _: bool = Depends(no_auth_required),
    auth_service = Depends(get_auth_service)
) -> HealthResponse:
    """
    Health check for authentication service.
    """
    try:
        health = await auth_service.health_check()

        return HealthResponse(
            status="healthy" if health.get("healthy") else "unhealthy",
            service=health.get("service", "auth_service_v2"),
            timestamp=health.get("timestamp", "")
        )

    except Exception as e:
        logger.error(f"Auth health check failed: {e}")
        return HealthResponse(
            status="unhealthy",
            service="auth_service_v2",
            timestamp=""
        )


# ========== INFORMATION ENDPOINTS ==========

@router.get("/info")
async def auth_info(
    _: bool = Depends(no_auth_required)
) -> Dict[str, Any]:
    """
    Get authentication service information.
    Public endpoint for integration details.
    """
    return {
        "service": "gmail-bot-auth-v2",
        "auth_provider": "supabase",
        "jwt_validation": "enabled",
        "oauth_provider": "google",
        "token_storage": "supabase_vault",
        "features": {
            "user_profiles": True,
            "gmail_oauth": True,
            "token_refresh": True,
            "account_deletion": True
        },
        "endpoints": {
            "profile": "/auth/me",
            "update_profile": "/auth/me (PUT)",
            "delete_account": "/auth/me (DELETE)",
            "status": "/auth/status",
            "health": "/auth/health"
        }
    }