# app_v2/api/routes/gmail.py
"""
PHOENIX GMAIL ROUTES - Clean Vault Integration
Simple Gmail API endpoints using Supabase Vault for token storage.

PRINCIPLES:
- OAuth handled by Supabase Auth (not custom flows)
- Tokens from vault (not local database)
- Clean Gmail API operations
- Proper error handling
"""
import logging
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app_v2.api.dependencies import (
    get_current_user,
    require_gmail_access,
    get_gmail_service,
    no_auth_required
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/gmail",
    tags=["gmail"]
)


# ========== REQUEST/RESPONSE MODELS ==========

class ConnectionStatusResponse(BaseModel):
    """Response model for Gmail connection status."""
    connected: bool
    status: str
    email: Optional[str] = None
    total_messages: Optional[int] = None
    last_checked: Optional[str] = None
    error: Optional[str] = None


class MessageResponse(BaseModel):
    """Response model for Gmail message."""
    id: str
    thread_id: str
    subject: str
    from_: str = Field(alias="from")
    to: str
    date: str
    snippet: str
    size_estimate: int


class MessagesResponse(BaseModel):
    """Response model for Gmail messages list."""
    messages: List[MessageResponse]
    total_results: int
    next_page_token: Optional[str] = None
    query: str


class MessageContentResponse(BaseModel):
    """Response model for full message content."""
    id: str
    thread_id: str
    subject: str
    from_: str = Field(alias="from")
    to: str
    date: str
    snippet: str
    body: Dict[str, str]  # {"text": "...", "html": "..."}


class MarkAsReadRequest(BaseModel):
    """Request model for marking messages as read."""
    message_ids: List[str] = Field(..., min_items=1, max_items=100)


# ========== CONNECTION ENDPOINTS ==========

@router.get("/status", response_model=ConnectionStatusResponse)
async def get_gmail_status(
    user = Depends(require_gmail_access),
    gmail_service = Depends(get_gmail_service)
) -> ConnectionStatusResponse:
    """
    Get Gmail connection status for current user.
    """
    try:
        status = await gmail_service.check_gmail_connection(user["user_id"])

        return ConnectionStatusResponse(
            connected=status["connected"],
            status=status["status"],
            email=status.get("email"),
            total_messages=status.get("total_messages"),
            last_checked=status.get("last_checked"),
            error=status.get("error")
        )

    except Exception as e:
        logger.error(f"Failed to get Gmail status for {user['user_id']}: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to check Gmail connection"
        )


@router.delete("/connection")
async def disconnect_gmail(
    user = Depends(require_gmail_access),
    gmail_service = Depends(get_gmail_service)
) -> Dict[str, Any]:
    """
    Disconnect Gmail account for current user.
    Revokes tokens and removes connection.
    """
    try:
        result = await gmail_service.disconnect_gmail(user["user_id"])

        if result["success"]:
            logger.info(f"Disconnected Gmail for user {user['user_id']}")
            return result
        else:
            raise HTTPException(
                status_code=500,
                detail=result["message"]
            )

    except Exception as e:
        logger.error(f"Failed to disconnect Gmail for {user['user_id']}: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to disconnect Gmail"
        )


# ========== EMAIL ENDPOINTS ==========

@router.get("/messages", response_model=MessagesResponse)
async def get_messages(
    user = Depends(require_gmail_access),
    gmail_service = Depends(get_gmail_service),
    query: str = Query("", description="Gmail search query"),
    limit: int = Query(10, ge=1, le=50, description="Maximum number of messages"),
    page_token: Optional[str] = Query(None, description="Pagination token")
) -> MessagesResponse:
    """
    Get Gmail messages for current user.

    Supports Gmail search queries:
    - is:unread (unread messages)
    - from:someone@example.com (from specific sender)
    - subject:"important" (messages with subject containing "important")
    - newer_than:7d (messages newer than 7 days)
    """
    try:
        messages = await gmail_service.get_messages(
            user["user_id"],
            query=query,
            max_results=limit,
            page_token=page_token
        )

        # Convert to response model
        message_responses = [
            MessageResponse(
                id=msg["id"],
                thread_id=msg["thread_id"],
                subject=msg["subject"],
                from_=msg["from"],  # Note: using from_ to avoid Python keyword
                to=msg["to"],
                date=msg["date"],
                snippet=msg["snippet"],
                size_estimate=msg["size_estimate"]
            )
            for msg in messages["messages"]
        ]

        return MessagesResponse(
            messages=message_responses,
            total_results=messages["total_results"],
            next_page_token=messages.get("next_page_token"),
            query=messages["query"]
        )

    except Exception as e:
        logger.error(f"Failed to get Gmail messages for {user['user_id']}: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve Gmail messages"
        )


@router.get("/messages/{message_id}", response_model=MessageContentResponse)
async def get_message_content(
    message_id: str,
    user = Depends(require_gmail_access),
    gmail_service = Depends(get_gmail_service)
) -> MessageContentResponse:
    """
    Get full content of a specific Gmail message.
    """
    try:
        message = await gmail_service.get_message_content(user["user_id"], message_id)

        return MessageContentResponse(
            id=message["id"],
            thread_id=message["thread_id"],
            subject=message["subject"],
            from_=message["from"],
            to=message["to"],
            date=message["date"],
            snippet=message["snippet"],
            body=message["body"]
        )

    except Exception as e:
        logger.error(f"Failed to get message {message_id} for {user['user_id']}: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve message content"
        )


@router.post("/messages/mark-read")
async def mark_messages_as_read(
    request: MarkAsReadRequest,
    user = Depends(require_gmail_access),
    gmail_service = Depends(get_gmail_service)
) -> Dict[str, Any]:
    """
    Mark Gmail messages as read.
    """
    try:
        result = await gmail_service.mark_as_read(user["user_id"], request.message_ids)

        logger.info(f"Marked {len(request.message_ids)} messages as read for user {user['user_id']}")
        return result

    except Exception as e:
        logger.error(f"Failed to mark messages as read for {user['user_id']}: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to mark messages as read"
        )


# ========== HEALTH AND INFO ==========

@router.get("/health")
async def gmail_health(
    _: bool = Depends(no_auth_required),
    gmail_service = Depends(get_gmail_service)
) -> Dict[str, Any]:
    """
    Health check for Gmail service.
    """
    try:
        health = await gmail_service.health_check()

        return {
            "status": "healthy" if health.get("healthy") else "unhealthy",
            "service": health.get("service", "gmail_service_v2"),
            "auth_service_healthy": health.get("auth_service_healthy"),
            "timestamp": health.get("timestamp")
        }

    except Exception as e:
        logger.error(f"Gmail health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e),
            "service": "gmail_service_v2"
        }


@router.get("/info")
async def gmail_info(
    _: bool = Depends(no_auth_required)
) -> Dict[str, Any]:
    """
    Get Gmail service information.
    Public endpoint for integration details.
    """
    return {
        "service": "gmail-api-v2",
        "auth_method": "supabase_vault",
        "oauth_provider": "google",
        "supported_operations": [
            "check_connection",
            "get_messages",
            "get_message_content",
            "mark_as_read",
            "disconnect"
        ],
        "search_syntax": {
            "unread": "is:unread",
            "from_sender": "from:email@example.com",
            "subject_contains": "subject:keyword",
            "newer_than": "newer_than:7d",
            "has_attachment": "has:attachment"
        },
        "limits": {
            "max_messages_per_request": 50,
            "max_mark_read_batch": 100
        }
    }