# app/api/routes/gmail.py
"""
Gmail routes for OAuth connection and email processing.
Handles Gmail integration and email management.
"""
import logging
from typing import Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.dependencies import (
    get_user_context,
    require_gmail_connection_permission,
    require_email_processing_permission,
    UserContext
)
from app.services.gmail_service import GmailService
from app.services.gmail_oauth_service import GmailOAuthService
from app.services.email_service import EmailService
from app.data.repositories.gmail_repository import GmailRepository
from app.data.repositories.user_repository import UserRepository
from app.data.repositories.email_repository import EmailRepository
from app.core.exceptions import NotFoundError, ValidationError, APIError

logger = logging.getLogger(__name__)

# Initialize services
gmail_repository = GmailRepository()
user_repository = UserRepository()
email_repository = EmailRepository()

gmail_oauth_service = GmailOAuthService(
    gmail_repository=gmail_repository,
    user_repository=user_repository
)

gmail_service = GmailService(
    gmail_repository=gmail_repository,
    user_repository=user_repository,
    email_repository=email_repository,
    job_repository=None,  # Will be injected when needed
    oauth_service=gmail_oauth_service
)

email_service = EmailService(
    gmail_service=gmail_service,
    billing_service=None,  # Will be injected when needed
    auth_service=None,     # Will be injected when needed
    user_repository=user_repository,
    email_repository=email_repository,
    billing_repository=None
)

router = APIRouter(
    prefix="/gmail",
    tags=["gmail"],
    responses={
        403: {"description": "Gmail access denied"},
        404: {"description": "Gmail connection not found"}
    }
)


# --- Request/Response Models ---

class GmailConnectionResponse(BaseModel):
    """Gmail connection status response"""
    connected: bool
    email_address: Optional[str] = None
    connection_status: str
    scopes: Optional[list] = None
    last_sync: Optional[str] = None
    error: Optional[str] = None


class ProcessEmailRequest(BaseModel):
    """Request to process a specific email"""
    message_id: str = Field(..., description="Gmail message ID to process")


class ProcessEmailResponse(BaseModel):
    """Response from processing an email"""
    success: bool
    message_id: str
    processing_time: float
    credits_used: int
    summary_sent: bool


class DiscoverEmailsResponse(BaseModel):
    """Response from email discovery"""
    success: bool
    emails_discovered: int
    new_emails: int
    filtered_emails: int
    discovery_time: str


# --- Gmail Connection Endpoints ---

@router.get("/connection", response_model=GmailConnectionResponse)
async def get_gmail_connection_status(
    context: UserContext = Depends(get_user_context)
) -> GmailConnectionResponse:
    """
    Get current Gmail connection status.
    """
    try:
        # Check connection status
        connection_status = gmail_oauth_service.check_connection_status(context.user_id)
        
        # Get connection info if connected
        connection_info = gmail_oauth_service.get_connection_info(context.user_id)
        
        return GmailConnectionResponse(
            connected=connection_status["connected"],
            email_address=connection_status.get("email"),
            connection_status=connection_status["status"],
            scopes=connection_info.get("scopes", []) if connection_info else None,
            last_sync=connection_info.get("last_sync") if connection_info else None,
            error=connection_status.get("error")
        )
    
    except Exception as e:
        logger.error(f"Get Gmail connection error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to get Gmail connection status"
        )


@router.post("/connect")
async def initiate_gmail_connection(
    context: UserContext = Depends(require_gmail_connection_permission)
) -> Dict[str, Any]:
    """
    Initiate Gmail OAuth connection.
    Returns OAuth URL for user to authorize.
    """
    try:
        # Generate OAuth URL
        oauth_data = gmail_oauth_service.generate_oauth_url(
            user_id=context.user_id,
            state=f"gmail_oauth_{context.user_id}"
        )
        
        logger.info(f"Gmail OAuth initiated for user: {context.user_id}")
        
        return {
            "success": True,
            "oauth_url": oauth_data["oauth_url"],
            "state": oauth_data["state"],
            "message": "Visit the OAuth URL to authorize Gmail access"
        }
    
    except Exception as e:
        logger.error(f"Gmail OAuth initiation error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to initiate Gmail connection"
        )


@router.post("/disconnect")
async def disconnect_gmail(
    context: UserContext = Depends(get_user_context)
) -> Dict[str, Any]:
    """
    Disconnect Gmail connection and revoke tokens.
    """
    try:
        # Revoke connection
        result = await gmail_oauth_service.revoke_connection(context.user_id)
        
        if result["success"]:
            logger.info(f"Gmail disconnected for user: {context.user_id}")
            return {
                "success": True,
                "message": "Gmail connection revoked successfully",
                "revoked_at": result["revoked_at"],
                "warnings": result.get("warnings", [])
            }
        else:
            return {
                "success": False,
                "message": result.get("error", "Failed to disconnect Gmail"),
                "error": result.get("error")
            }
    
    except Exception as e:
        logger.error(f"Gmail disconnect error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to disconnect Gmail"
        )


@router.post("/validate")
async def validate_gmail_connection(
    context: UserContext = Depends(get_user_context)
) -> Dict[str, Any]:
    """
    Validate Gmail connection and test API access.
    """
    try:
        # Validate connection
        validation_result = await gmail_oauth_service.validate_connection(context.user_id)
        
        return {
            "valid": validation_result["valid"],
            "user_id": validation_result["user_id"],
            "validated_at": validation_result.get("validated_at"),
            "error": validation_result.get("error")
        }
    
    except Exception as e:
        logger.error(f"Gmail validation error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to validate Gmail connection"
        )


# --- Email Processing Endpoints ---

@router.post("/discover", response_model=DiscoverEmailsResponse)
async def discover_emails(
    context: UserContext = Depends(require_email_processing_permission),
    apply_filters: bool = Query(True, description="Whether to apply email filters")
) -> DiscoverEmailsResponse:
    """
    Discover new emails from Gmail.
    """
    try:
        # Discover emails
        result = await email_service.discover_user_emails(
            context.user_id,
            apply_filters=apply_filters
        )
        
        logger.info(f"Email discovery completed for user: {context.user_id}")
        
        return DiscoverEmailsResponse(
            success=result["success"],
            emails_discovered=result.get("emails_discovered", 0),
            new_emails=result.get("new_emails", 0),
            filtered_emails=result.get("filtered_emails", 0),
            discovery_time=result.get("discovery_time", "")
        )
    
    except APIError as e:
        logger.error(f"Email discovery error: {e}")
        raise HTTPException(
            status_code=503,
            detail=str(e)
        )
    
    except Exception as e:
        logger.error(f"Email discovery error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to discover emails"
        )


@router.post("/process", response_model=ProcessEmailResponse)
async def process_email(
    request: ProcessEmailRequest,
    context: UserContext = Depends(require_email_processing_permission)
) -> ProcessEmailResponse:
    """
    Process a specific email and generate AI summary.
    """
    try:
        # Process the email
        result = await email_service.process_single_email(
            context.user_id,
            request.message_id
        )
        
        logger.info(f"Email processed for user: {context.user_id}")
        
        return ProcessEmailResponse(
            success=result["success"],
            message_id=result["message_id"],
            processing_time=result.get("processing_time", 0.0),
            credits_used=result.get("credits_used", 0),
            summary_sent=result.get("summary_sent", False)
        )
    
    except ValidationError as e:
        logger.warning(f"Email processing validation error: {e}")
        raise HTTPException(
            status_code=422,
            detail=str(e)
        )
    
    except APIError as e:
        logger.error(f"Email processing API error: {e}")
        raise HTTPException(
            status_code=503,
            detail=str(e)
        )
    
    except Exception as e:
        logger.error(f"Email processing error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to process email"
        )


@router.post("/process-batch")
async def process_batch_emails(
    context: UserContext = Depends(require_email_processing_permission),
    max_emails: int = Query(10, ge=1, le=50, description="Maximum emails to process")
) -> Dict[str, Any]:
    """
    Process multiple emails in batch.
    """
    try:
        # Process batch of emails
        result = await email_service.process_user_emails(
            context.user_id,
            max_emails=max_emails
        )
        
        logger.info(f"Batch processing completed for user: {context.user_id}")
        
        return {
            "success": result["success"],
            "user_id": result["user_id"],
            "emails_processed": result.get("emails_processed", 0),
            "credits_used": result.get("credits_used", 0),
            "failed_emails": result.get("failed_emails", 0),
            "errors": result.get("errors", [])
        }
    
    except ValidationError as e:
        logger.warning(f"Batch processing validation error: {e}")
        raise HTTPException(
            status_code=422,
            detail=str(e)
        )
    
    except APIError as e:
        logger.error(f"Batch processing API error: {e}")
        raise HTTPException(
            status_code=503,
            detail=str(e)
        )
    
    except Exception as e:
        logger.error(f"Batch processing error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to process batch emails"
        )


@router.post("/process-all")
async def process_all_emails(
    context: UserContext = Depends(require_email_processing_permission)
) -> Dict[str, Any]:
    """
    Run full email processing pipeline (discover + process).
    """
    try:
        # Run full processing pipeline
        result = await email_service.run_full_processing_pipeline(context.user_id)
        
        logger.info(f"Full processing pipeline completed for user: {context.user_id}")
        
        return {
            "success": result["success"],
            "user_id": result["user_id"],
            "pipeline_completed": result["pipeline_completed"],
            "emails_discovered": result.get("emails_discovered", 0),
            "emails_processed": result.get("emails_processed", 0),
            "credits_used": result.get("credits_used", 0)
        }
    
    except APIError as e:
        logger.error(f"Full processing API error: {e}")
        raise HTTPException(
            status_code=503,
            detail=str(e)
        )
    
    except Exception as e:
        logger.error(f"Full processing error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to run full processing pipeline"
        )


# --- Email History Endpoints ---

@router.get("/history")
async def get_processing_history(
    context: UserContext = Depends(get_user_context),
    limit: int = Query(20, ge=1, le=100, description="Number of entries to return"),
    status: Optional[str] = Query(None, description="Filter by processing status")
) -> Dict[str, Any]:
    """
    Get email processing history.
    """
    try:
        # Get processing history
        history = email_service.get_user_processing_history(
            context.user_id,
            limit=limit
        )
        
        # Filter by status if provided
        if status:
            history["processing_history"] = [
                item for item in history["processing_history"]
                if item.get("status") == status
            ]
        
        return {
            "success": True,
            "user_id": context.user_id,
            "processing_history": history["processing_history"],
            "total_entries": len(history["processing_history"])
        }
    
    except Exception as e:
        logger.error(f"Get processing history error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to get processing history"
        )


@router.get("/stats")
async def get_gmail_statistics(
    context: UserContext = Depends(get_user_context)
) -> Dict[str, Any]:
    """
    Get Gmail integration statistics.
    """
    try:
        # Get Gmail statistics
        gmail_stats = gmail_service.get_user_gmail_statistics(context.user_id)
        
        # Get email processing statistics
        email_stats = email_service.get_user_email_statistics(context.user_id)
        
        return {
            "user_id": context.user_id,
            "gmail_connection": {
                "status": gmail_stats.get("connection_status"),
                "email_address": gmail_stats.get("email_address"),
                "total_discovered": gmail_stats.get("total_discovered", 0),
                "total_processed": gmail_stats.get("total_processed", 0),
                "success_rate": gmail_stats.get("success_rate", 0.0)
            },
            "email_processing": {
                "total_processed": email_stats.get("total_processed", 0),
                "total_successful": email_stats.get("total_successful", 0),
                "total_failed": email_stats.get("total_failed", 0),
                "total_credits_used": email_stats.get("total_credits_used", 0),
                "average_processing_time": email_stats.get("average_processing_time", 0.0)
            }
        }
    
    except Exception as e:
        logger.error(f"Get Gmail stats error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to get Gmail statistics"
        )


# --- Health Check ---

@router.get("/health")
async def gmail_health_check(
    context: UserContext = Depends(get_user_context)
) -> Dict[str, Any]:
    """
    Health check for Gmail integration.
    """
    try:
        # Check Gmail connection
        connection_status = gmail_oauth_service.check_connection_status(context.user_id)
        
        # Check processing queue
        queue_status = gmail_service.get_queue_status()
        
        return {
            "status": "healthy" if connection_status["connected"] and queue_status["queue_status"] == "healthy" else "degraded",
            "gmail_connection": {
                "connected": connection_status["connected"],
                "status": connection_status["status"]
            },
            "processing_queue": {
                "status": queue_status["queue_status"],
                "pending_jobs": queue_status["pending_jobs"],
                "processing_jobs": queue_status["processing_jobs"]
            }
        }
    
    except Exception as e:
        logger.error(f"Gmail health check error: {e}")
        return {
            "status": "unhealthy",
            "error": str(e)
        }


# --- Example Usage ---

# from fastapi import FastAPI
# from app.api.routes.gmail import router as gmail_router
# 
# app = FastAPI()
# app.include_router(gmail_router)
# 
# # Available endpoints:
# # GET /gmail/connection - Gmail connection status
# # POST /gmail/connect - Initiate Gmail OAuth
# # POST /gmail/disconnect - Disconnect Gmail
# # POST /gmail/validate - Validate connection
# # POST /gmail/discover - Discover new emails
# # POST /gmail/process - Process specific email
# # POST /gmail/process-batch - Process multiple emails
# # POST /gmail/process-all - Full processing pipeline
# # GET /gmail/history - Processing history
# # GET /gmail/stats - Gmail statistics
# # GET /gmail/health - Gmail health check