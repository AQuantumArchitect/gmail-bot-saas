# app/api/routes/gmail.py
"""
Gmail routes for OAuth connection and email processing.
Handles Gmail integration and email management.

Updated to match the expected test endpoints and provide comprehensive Gmail functionality.
Fixed to align with actual service method signatures from project knowledge.
"""
import logging
import secrets
from typing import Dict, Any, Optional, List
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
from app.core.exceptions import NotFoundError, ValidationError, APIError, AuthenticationError, InsufficientCreditsError

logger = logging.getLogger(__name__)

# --- Service Factory Functions (SAAS Pattern: Clean Dependency Injection) ---

def get_gmail_oauth_service():
    """Get Gmail OAuth service from container."""
    from app.core.container import get_gmail_oauth_service as container_get_gmail_oauth_service
    return container_get_gmail_oauth_service()


def get_gmail_service():
    """Get Gmail service from container."""
    from app.core.container import get_gmail_service as container_get_gmail_service
    return container_get_gmail_service()


def get_email_service():
    """Get email service from container."""
    from app.core.container import get_email_service as container_get_email_service
    return container_get_email_service()


router = APIRouter(
    prefix="/gmail",
    tags=["gmail"],
    responses={
        403: {"description": "Gmail access denied"},
        404: {"description": "Gmail connection not found"}
    }
)


# --- Request/Response Models ---

class GmailConnectionStatusResponse(BaseModel):
    """Gmail connection status response"""
    connected: bool
    email_address: Optional[str] = None
    connection_status: str
    scopes: Optional[List[str]] = None
    last_sync: Optional[str] = None
    error: Optional[str] = None


class OAuthStartResponse(BaseModel):
    """Response model for OAuth start"""
    success: bool
    oauth_url: str
    state: str
    message: str


class OAuthCompleteRequest(BaseModel):
    """Request model for OAuth completion"""
    code: str = Field(..., min_length=1, description="OAuth authorization code")
    state: str = Field(..., min_length=1, description="OAuth state parameter")


class OAuthCompleteResponse(BaseModel):
    """Response model for OAuth completion"""
    success: bool
    email: str
    connected: bool
    message: str


class TokenRefreshResponse(BaseModel):
    """Response model for token refresh"""
    success: bool
    message: str
    expires_at: Optional[str] = None


class DisconnectResponse(BaseModel):
    """Response model for Gmail disconnection"""
    success: bool
    message: str
    revoked_tokens: int


class EmailDiscoveryResponse(BaseModel):
    """Response model for email discovery"""
    success: bool
    emails_discovered: int
    new_emails: int
    filtered_emails: int
    discovery_time: str


class SingleEmailProcessRequest(BaseModel):
    """Request model for single email processing"""
    message_id: str = Field(..., min_length=1, description="Gmail message ID to process")


class SingleEmailProcessResponse(BaseModel):
    """Response model for single email processing"""
    success: bool
    message_id: str
    processing_time: float
    credits_used: int
    summary_sent: bool
    summary: Optional[str] = None


class ProcessedEmailsResponse(BaseModel):
    """Response model for processed emails list"""
    success: bool
    emails: List[Dict[str, Any]]
    total_count: int
    returned_count: int
    offset: int


class EmailDetailsResponse(BaseModel):
    """Response model for single email details"""
    success: bool
    email: Dict[str, Any]


class ConnectionValidationResponse(BaseModel):
    """Response model for connection validation"""
    valid: bool
    user_id: str
    validated_at: str
    email: Optional[str] = None
    scopes_valid: Optional[bool] = None
    error: Optional[str] = None


class HealthCheckResponse(BaseModel):
    """Response model for health check"""
    status: str
    service: str
    connection_status: Optional[str] = None
    last_successful_sync: Optional[str] = None
    error_count: int = 0
    api_response_time: Optional[int] = None
    error: Optional[str] = None


# --- Gmail Connection Status Endpoint ---

@router.get("/connection", response_model=GmailConnectionStatusResponse)
async def get_gmail_connection_status(
    context: UserContext = Depends(get_user_context),
    oauth_service: GmailOAuthService = Depends(get_gmail_oauth_service)
) -> GmailConnectionStatusResponse:
    """
    Get Gmail connection status for authenticated user.
    Returns connection details, permissions, and health status.
    """
    try:
        # Check connection status (NOT async based on service implementation)
        connection_status = oauth_service.check_connection_status(context.user_id)
        connection_info = oauth_service.get_connection_info(context.user_id)
        
        return GmailConnectionStatusResponse(
            connected=connection_status.get("connected", False),
            email_address=connection_status.get("email"),
            connection_status=connection_status.get("status", "unknown"),
            scopes=connection_info.get("scopes") if connection_info else None,
            last_sync=connection_info.get("last_sync") if connection_info else None,
            error=connection_status.get("error")
        )
    
    except Exception as e:
        logger.error(f"Gmail connection status error for user {context.user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get Gmail connection status")


# --- OAuth Flow Endpoints ---

@router.post("/connect", response_model=OAuthStartResponse)
async def initiate_gmail_connection(
    context: UserContext = Depends(require_gmail_connection_permission),
    oauth_service: GmailOAuthService = Depends(get_gmail_oauth_service)
) -> OAuthStartResponse:
    """
    Initiate Gmail OAuth connection flow.
    Returns authorization URL and state for OAuth flow.
    """
    try:
        # Generate state parameter for CSRF protection
        state = secrets.token_urlsafe(32)
        
        # Note: generate_oauth_url is NOT async based on the service implementation
        oauth_result = oauth_service.generate_oauth_url(
            user_id=context.user_id,
            state=state
        )
        
        logger.info(f"OAuth flow initiated for user {context.user_id}")
        
        return OAuthStartResponse(
            success=True,
            oauth_url=oauth_result["oauth_url"],
            state=oauth_result["state"],
            message="Visit the URL to authorize Gmail access"
        )
    
    except Exception as e:
        logger.error(f"OAuth initiation error for user {context.user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to initiate Gmail connection")


@router.post("/callback", response_model=OAuthCompleteResponse)
async def complete_gmail_oauth(
    request: OAuthCompleteRequest,
    context: UserContext = Depends(require_gmail_connection_permission),
    oauth_service: GmailOAuthService = Depends(get_gmail_oauth_service)
) -> OAuthCompleteResponse:
    """
    Complete Gmail OAuth flow with authorization code.
    Exchanges code for tokens and establishes Gmail connection.
    """
    try:
        # Complete OAuth flow with correct parameter names based on service implementation
        result = await oauth_service.complete_oauth_flow(
            user_id=context.user_id,
            code=request.code,  # Parameter name is 'code'
            state=request.state
        )
        
        if not result.get("success"):
            raise ValidationError("OAuth completion failed")
        
        logger.info(f"OAuth completed for user {context.user_id}: {result.get('email')}")
        
        return OAuthCompleteResponse(
            success=True,
            email=result["email"],  # Service returns 'email', not 'email_address'
            connected=True,
            message="Gmail connected successfully"
        )
    
    except AuthenticationError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error(f"OAuth completion error for user {context.user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to complete Gmail OAuth")


@router.post("/refresh", response_model=TokenRefreshResponse)
async def refresh_gmail_tokens(
    context: UserContext = Depends(get_user_context),
    oauth_service: GmailOAuthService = Depends(get_gmail_oauth_service)
) -> TokenRefreshResponse:
    """
    Refresh Gmail access tokens using refresh token.
    """
    try:
        # refresh_access_token is async based on service implementation
        result = await oauth_service.refresh_access_token(context.user_id)
        
        if not result.get("success"):
            raise AuthenticationError("Token refresh failed")
        
        logger.info(f"Gmail tokens refreshed for user {context.user_id}")
        
        return TokenRefreshResponse(
            success=True,
            message="Token refreshed successfully",
            expires_at=result.get("expires_at")
        )
    
    except AuthenticationError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        logger.error(f"Token refresh error for user {context.user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to refresh Gmail tokens")


@router.delete("/connection", response_model=DisconnectResponse)
async def disconnect_gmail(
    context: UserContext = Depends(get_user_context),
    oauth_service: GmailOAuthService = Depends(get_gmail_oauth_service)
) -> DisconnectResponse:
    """
    Disconnect Gmail for user.
    Revokes tokens and removes Gmail connection.
    """
    try:
        # revoke_connection is async based on service implementation
        result = await oauth_service.revoke_connection(context.user_id)
        
        logger.info(f"Gmail disconnected for user {context.user_id}")
        
        return DisconnectResponse(
            success=True,
            message="Gmail disconnected successfully",
            revoked_tokens=result.get("revoked_count", 0)
        )
    
    except Exception as e:
        logger.error(f"Gmail disconnect error for user {context.user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to disconnect Gmail")


# --- Email Discovery and Processing Endpoints ---

@router.post("/discover", response_model=EmailDiscoveryResponse)
async def discover_emails(
    apply_filters: bool = Query(True, description="Apply email filters during discovery"),
    context: UserContext = Depends(require_email_processing_permission),
    email_service: EmailService = Depends(get_email_service)
) -> EmailDiscoveryResponse:
    """
    Discover new emails from Gmail.
    Scans Gmail for new emails and adds them to processing queue.
    """
    try:
        # discover_user_emails is async based on service implementation
        result = await email_service.discover_user_emails(
            user_id=context.user_id,
            apply_filters=apply_filters
        )
        
        logger.info(f"Email discovery completed for user {context.user_id}: {result.get('emails_discovered', 0)} emails")
        
        return EmailDiscoveryResponse(
            success=result.get("success", True),
            emails_discovered=result.get("emails_discovered", 0),
            new_emails=result.get("new_emails", 0),
            filtered_emails=result.get("filtered_emails", 0),
            discovery_time=result.get("discovery_time", "")
        )
    
    except APIError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"Email discovery error for user {context.user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to discover emails")


@router.post("/process", response_model=SingleEmailProcessResponse)
async def process_single_email(
    request: SingleEmailProcessRequest,
    context: UserContext = Depends(require_email_processing_permission),
    email_service: EmailService = Depends(get_email_service)
) -> SingleEmailProcessResponse:
    """
    Process a single email by message ID.
    Generates AI summary and sends it to the user.
    """
    try:
        # process_single_email is async based on service implementation
        result = await email_service.process_single_email(
            user_id=context.user_id,
            message_id=request.message_id
        )
        
        logger.info(f"Single email processed for user {context.user_id}: {request.message_id}")
        
        return SingleEmailProcessResponse(
            success=result.get("success", False),
            message_id=request.message_id,
            processing_time=result.get("processing_time", 0.0),
            credits_used=result.get("credits_used", 0),
            summary_sent=result.get("summary_sent", False),
            summary=result.get("summary")
        )
    
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except InsufficientCreditsError as e:
        raise HTTPException(status_code=402, detail=str(e))
    except Exception as e:
        logger.error(f"Single email processing error for user {context.user_id}: {e}")
        raise HTTPException(status_code=500, detail="Single email processing failed")


# --- Email Management Endpoints ---

@router.get("/emails", response_model=ProcessedEmailsResponse)
async def get_processed_emails(
    context: UserContext = Depends(get_user_context),
    gmail_service: GmailService = Depends(get_gmail_service),
    limit: int = Query(20, ge=1, le=100, description="Number of emails to return"),
    offset: int = Query(0, ge=0, description="Number of emails to skip")
) -> ProcessedEmailsResponse:
    """
    Get user's processed emails with pagination.
    Returns list of emails that have been processed by the system.
    """
    try:
        # get_user_processed_emails is async based on service implementation
        emails_data = await gmail_service.get_user_processed_emails(
            user_id=context.user_id,
            limit=limit,
            offset=offset
        )
        
        return ProcessedEmailsResponse(
            success=True,
            emails=emails_data.get("emails", []),
            total_count=emails_data.get("total_count", 0),
            returned_count=len(emails_data.get("emails", [])),
            offset=offset
        )
    
    except Exception as e:
        logger.error(f"Get processed emails error for user {context.user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get processed emails")


@router.get("/emails/{message_id}", response_model=EmailDetailsResponse)
async def get_email_details(
    message_id: str,
    context: UserContext = Depends(get_user_context),
    gmail_service: GmailService = Depends(get_gmail_service)
) -> EmailDetailsResponse:
    """
    Get detailed information for a specific email.
    Returns full email content, summary, and processing metadata.
    """
    try:
        # get_email_by_message_id is async based on service implementation
        email_data = await gmail_service.get_email_by_message_id(
            user_id=context.user_id,
            message_id=message_id
        )
        
        if not email_data:
            raise HTTPException(status_code=404, detail="Email not found")
        
        return EmailDetailsResponse(
            success=True,
            email=email_data
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get email details error for user {context.user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get email details")


# --- Connection Validation and Health Endpoints ---

@router.post("/validate", response_model=ConnectionValidationResponse)
async def validate_gmail_connection(
    context: UserContext = Depends(get_user_context),
    oauth_service: GmailOAuthService = Depends(get_gmail_oauth_service)
) -> ConnectionValidationResponse:
    """
    Validate Gmail connection for user.
    Checks if tokens are valid and connection is healthy.
    """
    try:
        # validate_connection is async based on service implementation
        result = await oauth_service.validate_connection(context.user_id)
        
        return ConnectionValidationResponse(
            valid=result.get("valid", False),
            user_id=result.get("user_id", context.user_id),
            validated_at=result.get("validated_at", ""),
            email=result.get("email"),
            scopes_valid=result.get("scopes_valid"),
            error=result.get("error")
        )
    
    except Exception as e:
        logger.error(f"Connection validation error for user {context.user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to validate Gmail connection")


@router.get("/health", response_model=HealthCheckResponse)
async def gmail_service_health(
    context: UserContext = Depends(get_user_context),
    gmail_service: GmailService = Depends(get_gmail_service)
) -> HealthCheckResponse:
    """
    Check Gmail service health for user.
    Returns connection status and service health metrics.
    """
    try:
        # check_service_health is async based on service implementation
        health = await gmail_service.check_service_health(context.user_id)
        
        return HealthCheckResponse(
            status=health.get("status", "unknown"),
            service="gmail",
            connection_status=health.get("connection_status"),
            last_successful_sync=health.get("last_successful_sync"),
            error_count=health.get("error_count", 0),
            api_response_time=health.get("api_response_time")
        )
    
    except Exception as e:
        logger.error(f"Gmail health check error for user {context.user_id}: {e}")
        return HealthCheckResponse(
            status="unhealthy",
            service="gmail",
            error_count=1,
            error=str(e)
        )


# --- Statistics Endpoint (Expected by Tests) ---

@router.get("/stats")
async def get_gmail_statistics(
    context: UserContext = Depends(get_user_context),
    gmail_service: GmailService = Depends(get_gmail_service)
) -> Dict[str, Any]:
    """
    Get Gmail processing statistics for user.
    Returns email processing metrics and usage statistics.
    """
    try:
        # get_user_gmail_statistics is NOT async based on service implementation
        stats = gmail_service.get_user_gmail_statistics(context.user_id)
        
        return {
            "success": True,
            "statistics": stats,
            "user_id": context.user_id
        }
    
    except Exception as e:
        logger.error(f"Gmail statistics error for user {context.user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get Gmail statistics")