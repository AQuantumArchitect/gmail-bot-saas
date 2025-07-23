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
from app.services.email_service import EmailService
from app.services.gmail_service import GmailService
from app.services.billing_service import BillingService
from app.data.repositories.user_repository import UserRepository
from app.data.repositories.email_repository import EmailRepository
from app.data.repositories.gmail_repository import GmailRepository
from app.data.repositories.billing_repository import BillingRepository
from app.core.exceptions import NotFoundError, ValidationError

logger = logging.getLogger(__name__)

# Initialize services
user_repository = UserRepository()
email_repository = EmailRepository()
gmail_repository = GmailRepository()
billing_repository = BillingRepository()

user_service = UserService(
    user_repository=user_repository,
    billing_service=None,  # Will be injected when needed
    billing_repository=billing_repository,
    email_repository=email_repository,
    gmail_repository=gmail_repository
)

gmail_service = GmailService(
    gmail_repository=gmail_repository,
    user_repository=user_repository,
    email_repository=email_repository,
    job_repository=None,  # Will be injected when needed
    oauth_service=None   # Will be injected when needed
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


class PreferencesUpdateRequest(BaseModel):
    """Request model for updating preferences"""
    email_filters: Optional[Dict[str, Any]] = None
    ai_preferences: Optional[Dict[str, Any]] = None
    processing_frequency: Optional[str] = None
    timezone: Optional[str] = None


class BotToggleRequest(BaseModel):
    """Request model for toggling bot status"""
    enabled: bool = Field(..., description="Whether to enable or disable the bot")


# --- Dashboard Data Endpoints ---

@router.get("/data", response_model=DashboardDataResponse)
async def get_dashboard_data(
    context: UserContext = Depends(require_dashboard_access)
) -> DashboardDataResponse:
    """
    Get complete dashboard data for the user.
    Returns all information needed for the dashboard UI.
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
        logger.warning(f"Dashboard data not found: {e}")
        raise HTTPException(
            status_code=404,
            detail=str(e)
        )
    
    except Exception as e:
        logger.error(f"Dashboard data error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve dashboard data"
        )


@router.get("/status", response_model=BotStatusResponse)
async def get_bot_status(
    context: UserContext = Depends(require_dashboard_access)
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
        logger.error(f"Bot status error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to get bot status"
        )


@router.post("/bot/toggle")
async def toggle_bot_status(
    request: BotToggleRequest,
    context: UserContext = Depends(require_dashboard_access)
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
        logger.error(f"Bot toggle error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to toggle bot status"
        )


# --- Statistics Endpoints ---

@router.get("/stats/email", response_model=EmailStatsResponse)
async def get_email_statistics(
    context: UserContext = Depends(require_dashboard_access)
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
        logger.error(f"Email stats error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to get email statistics"
        )


@router.get("/stats/credits")
async def get_credit_statistics(
    context: UserContext = Depends(require_dashboard_access)
) -> Dict[str, Any]:
    """
    Get credit balance and usage statistics.
    """
    try:
        # Get credit balance
        balance = await user_service.get_credit_balance(context.user_id)
        
        # Get recent credit history
        history = await user_service.get_credit_history(context.user_id, limit=10)
        
        return {
            "current_balance": balance["credits_remaining"],
            "last_updated": balance["last_updated"],
            "recent_transactions": history["transactions"],
            "total_transactions": history["total_transactions"]
        }
    
    except Exception as e:
        logger.error(f"Credit stats error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to get credit statistics"
        )


@router.get("/stats/usage")
async def get_usage_statistics(
    context: UserContext = Depends(require_dashboard_access),
    days: int = Query(30, ge=1, le=90, description="Number of days to include")
) -> Dict[str, Any]:
    """
    Get usage statistics for the specified period.
    """
    try:
        # Get processing statistics
        processing_stats = email_repository.get_processing_stats(context.user_id)
        
        # Get Gmail statistics
        gmail_stats = gmail_service.get_user_gmail_statistics(context.user_id)
        
        return {
            "period_days": days,
            "email_processing": {
                "total_processed": processing_stats.get("total_processed", 0),
                "successful": processing_stats.get("total_successful", 0),
                "failed": processing_stats.get("total_failed", 0),
                "success_rate": processing_stats.get("success_rate", 0.0),
                "avg_processing_time": processing_stats.get("average_processing_time", 0.0)
            },
            "gmail_integration": {
                "connection_status": gmail_stats.get("connection_status", "not_connected"),
                "total_discovered": gmail_stats.get("total_discovered", 0),
                "total_processed": gmail_stats.get("total_processed", 0)
            },
            "credits": {
                "total_used": processing_stats.get("total_credits_used", 0),
                "remaining": context.credits_remaining
            }
        }
    
    except Exception as e:
        logger.error(f"Usage stats error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to get usage statistics"
        )


# --- Settings Endpoints ---

@router.get("/settings")
async def get_user_settings(
    context: UserContext = Depends(require_dashboard_access)
) -> Dict[str, Any]:
    """
    Get user settings and preferences.
    """
    try:
        # Get user preferences
        preferences = await user_service.get_user_preferences(context.user_id)
        
        # Get user profile for additional settings
        profile = await user_service.get_user_profile(context.user_id)
        
        return {
            "user_profile": {
                "display_name": profile.get("display_name"),
                "timezone": profile.get("timezone"),
                "email": profile.get("email")
            },
            "email_filters": preferences["email_filters"],
            "ai_preferences": preferences["ai_preferences"],
            "processing_frequency": preferences["processing_frequency"],
            "bot_enabled": profile.get("bot_enabled", False)
        }
    
    except Exception as e:
        logger.error(f"Get settings error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to get user settings"
        )


@router.put("/settings")
async def update_user_settings(
    request: PreferencesUpdateRequest,
    context: UserContext = Depends(require_dashboard_access)
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
        logger.warning(f"Settings validation error: {e}")
        raise HTTPException(
            status_code=422,
            detail=str(e)
        )
    
    except Exception as e:
        logger.error(f"Update settings error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to update settings"
        )


@router.post("/settings/reset")
async def reset_settings_to_default(
    context: UserContext = Depends(require_dashboard_access)
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
        logger.error(f"Reset settings error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to reset settings"
        )


# --- Activity Endpoints ---

@router.get("/activity")
async def get_recent_activity(
    context: UserContext = Depends(require_dashboard_access),
    limit: int = Query(20, ge=1, le=100, description="Number of activities to return")
) -> Dict[str, Any]:
    """
    Get recent user activity.
    """
    try:
        # Get recent processing history
        processing_history = email_repository.get_processing_history(
            context.user_id, 
            limit=limit
        )
        
        # Get recent credit transactions
        credit_history = await user_service.get_credit_history(
            context.user_id, 
            limit=5
        )
        
        # Combine and format activities
        activities = []
        
        # Add processing activities
        for item in processing_history:
            activities.append({
                "type": "email_processed",
                "timestamp": item.get("processing_completed_at"),
                "description": f"Processed email: {item.get('subject', 'Unknown')}",
                "status": item.get("status"),
                "credits_used": item.get("processing_result", {}).get("credits_used", 0)
            })
        
        # Add credit activities
        for item in credit_history["transactions"][:5]:
            activities.append({
                "type": "credit_transaction",
                "timestamp": item.get("created_at"),
                "description": item.get("description"),
                "amount": item.get("credit_amount"),
                "transaction_type": item.get("transaction_type")
            })
        
        # Sort by timestamp
        activities.sort(key=lambda x: x["timestamp"] or "", reverse=True)
        
        return {
            "activities": activities[:limit],
            "total_activities": len(activities)
        }
    
    except Exception as e:
        logger.error(f"Get activity error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to get recent activity"
        )


# --- System Health for User ---

@router.get("/health")
async def get_user_system_health(
    context: UserContext = Depends(require_dashboard_access)
) -> Dict[str, Any]:
    """
    Get system health status from user's perspective.
    """
    try:
        # Get Gmail connection status
        gmail_stats = gmail_service.get_user_gmail_statistics(context.user_id)
        gmail_healthy = gmail_stats.get("connection_status") == "connected"
        
        # Get processing queue status
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
        logger.error(f"User health check error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to get system health"
        )


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