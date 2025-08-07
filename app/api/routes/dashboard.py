# app/api/routes/dashboard.py
"""
Dashboard routes for user dashboard data and settings.
Provides all the data needed for the user dashboard interface.
"""

import logging
from typing import Dict, Any, Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.dependencies import (
    get_user_context,
    require_dashboard_access,
    UserContext
)
from app.services.user_service import UserService
from app.services.gmail_service import GmailService
from app.core.exceptions import NotFoundError, ValidationError
from app.core.container import get_user_repository, get_billing_service

logger = logging.getLogger(__name__)

# --- Service Factory Functions ---

def get_user_service():
    """Get user service with all dependencies properly injected"""
    from app.data.repositories.email_repository import EmailRepository
    from app.data.repositories.gmail_repository import GmailRepository
    from app.data.repositories.billing_repository import BillingRepository
    
    return UserService(
        user_repository=get_user_repository(),
        billing_service=get_billing_service(),
        billing_repository=BillingRepository(),
        email_repository=EmailRepository(),
        gmail_repository=GmailRepository()
    )

def get_gmail_service():
    """Get gmail service with dependencies"""
    from app.data.repositories.email_repository import EmailRepository
    from app.data.repositories.gmail_repository import GmailRepository
    from app.services.gmail_oauth_service import GmailOAuthService
    
    gmail_repo = GmailRepository()
    user_repo = get_user_repository()
    email_repo = EmailRepository()
    
    oauth_service = GmailOAuthService(
        gmail_repository=gmail_repo,
        user_repository=user_repo
    )
    
    return GmailService(
        gmail_repository=gmail_repo,
        user_repository=user_repo,
        email_repository=email_repo,
        job_repository=None,  # Would be injected in full implementation
        oauth_service=oauth_service
    )

router = APIRouter(
    prefix="/dashboard",
    tags=["dashboard"],
    responses={
        403: {"description": "Dashboard access denied"},
        404: {"description": "Resource not found"}
    }
)

# --- Request/Response Models ---

class DashboardDataResponse(BaseModel):
    """Complete dashboard data response"""
    user_profile: Dict[str, Any]
    bot_status: Dict[str, Any]
    credits: Dict[str, Any]
    email_stats: Dict[str, Any]
    gmail_status: Dict[str, Any]
    recent_activity: List[Dict[str, Any]]
    timestamp: str

class BotStatusResponse(BaseModel):
    """Bot status response"""
    bot_enabled: bool
    gmail_connected: bool
    credits_remaining: int
    status: str
    processing_frequency: str
    last_processing: Optional[str] = None

class EmailStatsResponse(BaseModel):
    """Email statistics response"""
    total_processed: int
    successful_emails: int
    failed_emails: int
    success_rate: float
    credits_used: int
    avg_processing_time: float

class UserSettingsRequest(BaseModel):
    """Request model for updating user settings"""
    email_filters: Optional[Dict[str, Any]] = None
    ai_preferences: Optional[Dict[str, Any]] = None
    processing_frequency: Optional[str] = None
    timezone: Optional[str] = None

class UserSettingsResponse(BaseModel):
    """Response model for user settings"""
    user_id: str
    bot_enabled: bool
    timezone: str
    email_filters: Dict[str, Any]
    ai_preferences: Dict[str, Any]
    processing_frequency: str
    updated_at: str

class BotToggleRequest(BaseModel):
    """Request model for toggling bot status"""
    enabled: bool = Field(..., description="Whether to enable or disable the bot")

# --- Dashboard Endpoints ---

@router.get("/data", response_model=DashboardDataResponse)
async def get_dashboard_data(
    context: UserContext = Depends(require_dashboard_access),
    user_service: UserService = Depends(get_user_service),
    gmail_service: GmailService = Depends(get_gmail_service)
) -> DashboardDataResponse:
    """
    Get complete dashboard data for authenticated user.
    Returns all data needed for the dashboard UI.
    """
    try:
        # Get comprehensive dashboard data
        dashboard_data = await user_service.get_dashboard_data(context.user_id)
        
        logger.info(f"Dashboard data retrieved for user: {context.user_id}")
        
        return DashboardDataResponse(
            user_profile=dashboard_data["user_profile"],
            bot_status=dashboard_data["bot_status"],
            credits=dashboard_data["credits"],
            email_stats=dashboard_data["email_stats"],
            gmail_status=dashboard_data.get("gmail_status", {"connected": False}),
            recent_activity=dashboard_data.get("recent_activity", []),
            timestamp=dashboard_data["timestamp"]
        )
    
    except NotFoundError as e:
        logger.warning(f"Dashboard data not found for user {context.user_id}: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    
    except Exception as e:
        logger.error(f"Dashboard data error for user {context.user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve dashboard data")

@router.get("/status", response_model=BotStatusResponse)
async def get_bot_status(
    context: UserContext = Depends(require_dashboard_access),
    user_service: UserService = Depends(get_user_service)
) -> BotStatusResponse:
    """
    Get current bot status and configuration.
    """
    try:
        bot_status = await user_service.get_bot_status(context.user_id)
        
        return BotStatusResponse(
            bot_enabled=bot_status["bot_enabled"],
            gmail_connected=bot_status["gmail_connected"],
            credits_remaining=bot_status["credits_remaining"],
            status=bot_status["status"],
            processing_frequency=bot_status["processing_frequency"],
            last_processing=bot_status.get("last_processing")
        )
    
    except Exception as e:
        logger.error(f"Bot status error for user {context.user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get bot status")

@router.post("/bot/toggle")
async def toggle_bot_status(
    request: BotToggleRequest,
    context: UserContext = Depends(require_dashboard_access),
    user_service: UserService = Depends(get_user_service)
) -> Dict[str, Any]:
    """
    Enable or disable the bot for the user.
    """
    try:
        if request.enabled:
            result = await user_service.enable_bot(context.user_id)
            logger.info(f"Bot enabled for user: {context.user_id}")
        else:
            result = await user_service.disable_bot(context.user_id)
            logger.info(f"Bot disabled for user: {context.user_id}")
        
        return {
            "success": True,
            "bot_enabled": result["bot_enabled"],
            "message": f"Bot {'enabled' if request.enabled else 'disabled'} successfully"
        }
    
    except Exception as e:
        logger.error(f"Bot toggle error for user {context.user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to toggle bot status")

# --- Statistics Endpoints ---

@router.get("/stats/email", response_model=EmailStatsResponse)
async def get_email_statistics(
    context: UserContext = Depends(require_dashboard_access),
    user_service: UserService = Depends(get_user_service)
) -> EmailStatsResponse:
    """
    Get detailed email processing statistics.
    """
    try:
        stats = await user_service.get_user_statistics(context.user_id)
        
        return EmailStatsResponse(
            total_processed=stats["total_emails_processed"],
            successful_emails=stats["successful_emails"],
            failed_emails=stats["failed_emails"],
            success_rate=stats["success_rate"],
            credits_used=stats["credits_used"],
            avg_processing_time=stats.get("avg_processing_time", 0.0)
        )
    
    except Exception as e:
        logger.error(f"Email stats error for user {context.user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get email statistics")

@router.get("/stats/credits")
async def get_credit_statistics(
    context: UserContext = Depends(require_dashboard_access),
    user_service: UserService = Depends(get_user_service)
) -> Dict[str, Any]:
    """
    Get credit balance and usage statistics.
    """
    try:
        stats = await user_service.get_user_credit_statistics(context.user_id)
        return stats
    
    except Exception as e:
        logger.error(f"Credit stats error for user {context.user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get credit statistics")

@router.get("/stats/usage")
async def get_usage_statistics(
    context: UserContext = Depends(require_dashboard_access),
    user_service: UserService = Depends(get_user_service)
) -> Dict[str, Any]:
    """
    Get overall usage statistics for user.
    """
    try:
        stats = await user_service.get_user_usage_statistics(context.user_id)
        return stats
    
    except Exception as e:
        logger.error(f"Usage stats error for user {context.user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get usage statistics")

# --- Settings Endpoints ---

@router.get("/settings", response_model=UserSettingsResponse)
async def get_user_settings(
    context: UserContext = Depends(require_dashboard_access),
    user_service: UserService = Depends(get_user_service)
) -> UserSettingsResponse:
    """
    Get user settings and preferences.
    """
    try:
        profile = await user_service.get_user_profile(context.user_id)
        
        return UserSettingsResponse(
            user_id=context.user_id,
            bot_enabled=profile.get("bot_enabled", False),
            timezone=profile.get("timezone", "UTC"),
            email_filters=profile.get("email_filters", {}),
            ai_preferences=profile.get("ai_preferences", {}),
            processing_frequency=profile.get("processing_frequency", "daily"),
            updated_at=profile.get("updated_at", "")
        )
    
    except NotFoundError:
        raise HTTPException(status_code=404, detail="User settings not found")
    except Exception as e:
        logger.error(f"Get settings error for user {context.user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get user settings")

@router.put("/settings", response_model=Dict[str, Any])
async def update_user_settings(
    request: UserSettingsRequest,
    context: UserContext = Depends(require_dashboard_access),
    user_service: UserService = Depends(get_user_service)
) -> Dict[str, Any]:
    """
    Update user settings and preferences.
    """
    try:
        results = {}
        
        # Update email filters
        if request.email_filters is not None:
            result = await user_service.update_email_filters(
                context.user_id, 
                request.email_filters
            )
            results["email_filters"] = result
        
        # Update AI preferences
        if request.ai_preferences is not None:
            result = await user_service.update_ai_preferences(
                context.user_id, 
                request.ai_preferences
            )
            results["ai_preferences"] = result
        
        # Update processing frequency
        if request.processing_frequency is not None:
            result = await user_service.update_processing_frequency(
                context.user_id, 
                request.processing_frequency
            )
            results["processing_frequency"] = result
        
        # Update timezone
        if request.timezone is not None:
            result = await user_service.update_timezone(
                context.user_id, 
                request.timezone
            )
            results["timezone"] = result
        
        logger.info(f"Settings updated for user: {context.user_id}")
        
        return {
            "success": True,
            "message": "Settings updated successfully",
            "updates": results
        }
    
    except ValidationError as e:
        logger.warning(f"Settings validation error for user {context.user_id}: {e}")
        raise HTTPException(status_code=422, detail=str(e))
    
    except Exception as e:
        logger.error(f"Update settings error for user {context.user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to update settings")

@router.post("/settings/reset")
async def reset_settings_to_default(
    context: UserContext = Depends(require_dashboard_access),
    user_service: UserService = Depends(get_user_service)
) -> Dict[str, Any]:
    """
    Reset user settings to default values.
    """
    try:
        result = await user_service.reset_preferences_to_default(context.user_id)
        
        logger.info(f"Settings reset to default for user: {context.user_id}")
        
        return {
            "success": True,
            "message": "Settings reset to default successfully",
            "preferences_reset": result["preferences_reset"]
        }
    
    except Exception as e:
        logger.error(f"Reset settings error for user {context.user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to reset settings")

# --- Activity Endpoints ---

@router.get("/activity")
async def get_recent_activity(
    context: UserContext = Depends(require_dashboard_access),
    user_service: UserService = Depends(get_user_service),
    limit: int = Query(20, ge=1, le=100, description="Number of activities to return")
) -> Dict[str, Any]:
    """
    Get recent user activity.
    """
    try:
        activities = await user_service.get_user_recent_activity(context.user_id, limit=limit)
        
        return {
            "success": True,
            "activities": activities,
            "total_returned": len(activities)
        }
    
    except Exception as e:
        logger.error(f"Recent activity error for user {context.user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get recent activity")

# --- Health Check ---

@router.get("/health")
async def get_user_system_health(
    context: UserContext = Depends(require_dashboard_access),
    gmail_service: GmailService = Depends(get_gmail_service)
) -> Dict[str, Any]:
    """
    Get system health status for current user.
    """
    try:
        # Get Gmail connection status
        gmail_stats = await gmail_service.get_user_gmail_statistics(context.user_id)
        gmail_healthy = gmail_stats.get("connection_status") == "connected"
        
        # Get processing queue status (mock implementation)
        from app.data.repositories.email_repository import EmailRepository
        email_repository = EmailRepository()
        processing_stats = email_repository.get_processing_stats(context.user_id)
        processing_healthy = processing_stats.get("total_pending", 0) < 10
        
        # Overall health
        overall_health = "healthy" if gmail_healthy and processing_healthy else "degraded"
        
        return {
            "overall_status": overall_health,
            "gmail_connection": {
                "status": "healthy" if gmail_healthy else "unhealthy",
                "connected": gmail_healthy,
                "email_address": gmail_stats.get("email_address")
            },
            "email_processing": {
                "status": "healthy" if processing_healthy else "degraded",
                "pending_emails": processing_stats.get("total_pending", 0),
                "success_rate": processing_stats.get("success_rate", 0.0)
            },
            "bot_status": {
                "enabled": context.bot_enabled,
                "credits_remaining": context.credits_remaining,
                "status": "active" if context.bot_enabled and context.credits_remaining > 0 else "inactive"
            }
        }
    
    except Exception as e:
        logger.error(f"User health check error for user {context.user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get system health")

# --- Example Usage ---

# from fastapi import FastAPI
# from app.api.routes.dashboard import router as dashboard_router
# 
# app = FastAPI()
# app.include_router(dashboard_router)
# 
# # Available endpoints:
# # GET /dashboard/data - Complete dashboard data
# # GET /dashboard/status - Bot status
# # POST /dashboard/bot/toggle - Enable/disable bot
# # GET /dashboard/stats/email - Email statistics
# # GET /dashboard/stats/credits - Credit statistics
# # GET /dashboard/stats/usage - Usage statistics
# # GET /dashboard/settings - User settings
# # PUT /dashboard/settings - Update settings
# # POST /dashboard/settings/reset - Reset settings
# # GET /dashboard/activity - Recent activity
# # GET /dashboard/health - System health for user