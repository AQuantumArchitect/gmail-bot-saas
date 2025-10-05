# app_v2/services/gmail_service.py
"""
PHOENIX GMAIL SERVICE - Clean Vault Integration
Simplified Gmail OAuth using Supabase Auth + Vault for token storage.

PRINCIPLES:
- OAuth flow handled by Supabase Auth (not custom implementation)
- Tokens stored in Supabase Vault (not local database)
- Clean integration with AuthService
- Focused on Gmail API operations, not OAuth management
"""
import logging
from typing import Any, Dict, List, Optional
from datetime import datetime

import httpx
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from app_v2.core.config import settings
from app_v2.core.exceptions import (
    ValidationError,
    AuthenticationError,
    APIError
)

logger = logging.getLogger(__name__)


class GmailService:
    """
    PHOENIX GMAIL SERVICE

    Clean Gmail service that:
    - Uses tokens from Supabase Vault (via AuthService)
    - Focuses on Gmail API operations
    - Handles token refresh automatically
    - No custom OAuth flows (handled by Supabase)
    """

    GMAIL_SCOPES = [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/gmail.send"
    ]

    def __init__(self, auth_service):
        """
        Initialize Gmail service with auth service dependency.

        Args:
            auth_service: AuthService instance for token management
        """
        self.auth_service = auth_service

    # ========== GMAIL CLIENT MANAGEMENT ==========

    async def get_gmail_client(self, user_id: str):
        """
        Get authenticated Gmail API client for user.

        Args:
            user_id: User UUID string

        Returns:
            Google API client instance

        Raises:
            AuthenticationError: No valid tokens available
        """
        # Get tokens from vault via auth service
        tokens = await self.auth_service.get_gmail_tokens(user_id)

        if not tokens:
            raise AuthenticationError("No Gmail connection found for user")

        # Create Google credentials object
        credentials = Credentials(
            token=tokens.get("access_token"),
            refresh_token=tokens.get("refresh_token"),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            scopes=self.GMAIL_SCOPES
        )

        # Check if token needs refresh
        if credentials.expired:
            logger.info(f"Refreshing Gmail tokens for user {user_id}")
            refreshed_tokens = await self.auth_service.refresh_gmail_tokens(user_id)

            if not refreshed_tokens:
                raise AuthenticationError("Failed to refresh Gmail tokens")

            credentials = Credentials(
                token=refreshed_tokens.get("access_token"),
                refresh_token=refreshed_tokens.get("refresh_token"),
                token_uri="https://oauth2.googleapis.com/token",
                client_id=settings.google_client_id,
                client_secret=settings.google_client_secret,
                scopes=self.GMAIL_SCOPES
            )

        # Build Gmail API client
        return build("gmail", "v1", credentials=credentials)

    # ========== CONNECTION MANAGEMENT ==========

    async def check_gmail_connection(self, user_id: str) -> Dict[str, Any]:
        """
        Check Gmail connection status for user.

        Args:
            user_id: User UUID string

        Returns:
            Connection status information
        """
        try:
            tokens = await self.auth_service.get_gmail_tokens(user_id)

            if not tokens:
                return {
                    "connected": False,
                    "status": "not_connected",
                    "email": None,
                    "error": "No Gmail connection found"
                }

            # Test the connection
            gmail_client = await self.get_gmail_client(user_id)
            profile = gmail_client.users().getProfile(userId='me').execute()

            return {
                "connected": True,
                "status": "connected",
                "email": profile.get("emailAddress"),
                "total_messages": profile.get("messagesTotal", 0),
                "last_checked": datetime.utcnow().isoformat()
            }

        except Exception as e:
            logger.error(f"Failed to check Gmail connection for {user_id}: {e}")
            return {
                "connected": False,
                "status": "error",
                "email": None,
                "error": str(e)
            }

    async def disconnect_gmail(self, user_id: str) -> Dict[str, Any]:
        """
        Disconnect Gmail account for user.

        Args:
            user_id: User UUID string

        Returns:
            Disconnection result
        """
        try:
            success = await self.auth_service.revoke_gmail_tokens(user_id)

            if success:
                logger.info(f"Disconnected Gmail for user {user_id}")
                return {
                    "success": True,
                    "message": "Gmail account disconnected successfully",
                    "disconnected_at": datetime.utcnow().isoformat()
                }
            else:
                return {
                    "success": False,
                    "message": "Failed to disconnect Gmail account"
                }

        except Exception as e:
            logger.error(f"Failed to disconnect Gmail for {user_id}: {e}")
            return {
                "success": False,
                "message": f"Error disconnecting Gmail: {e}"
            }

    # ========== EMAIL OPERATIONS ==========

    async def get_messages(
        self,
        user_id: str,
        query: str = "",
        max_results: int = 10,
        page_token: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get Gmail messages for user.

        Args:
            user_id: User UUID string
            query: Gmail search query
            max_results: Maximum number of results
            page_token: Pagination token

        Returns:
            Messages and pagination info
        """
        try:
            gmail_client = await self.get_gmail_client(user_id)

            # Get message list
            request_params = {
                "userId": "me",
                "q": query,
                "maxResults": max_results
            }

            if page_token:
                request_params["pageToken"] = page_token

            messages_result = gmail_client.users().messages().list(**request_params).execute()

            messages = messages_result.get("messages", [])
            next_page_token = messages_result.get("nextPageToken")

            # Get message details
            detailed_messages = []
            for message in messages[:max_results]:  # Respect limit
                try:
                    msg_detail = gmail_client.users().messages().get(
                        userId="me",
                        id=message["id"],
                        format="metadata",
                        metadataHeaders=["From", "To", "Subject", "Date"]
                    ).execute()

                    detailed_messages.append(self._format_message(msg_detail))
                except Exception as e:
                    logger.warning(f"Failed to get message {message['id']}: {e}")
                    continue

            return {
                "messages": detailed_messages,
                "total_results": len(detailed_messages),
                "next_page_token": next_page_token,
                "query": query
            }

        except Exception as e:
            logger.error(f"Failed to get Gmail messages for {user_id}: {e}")
            raise APIError(f"Failed to retrieve Gmail messages: {e}")

    async def get_message_content(self, user_id: str, message_id: str) -> Dict[str, Any]:
        """
        Get full content of a specific Gmail message.

        Args:
            user_id: User UUID string
            message_id: Gmail message ID

        Returns:
            Full message content
        """
        try:
            gmail_client = await self.get_gmail_client(user_id)

            message = gmail_client.users().messages().get(
                userId="me",
                id=message_id,
                format="full"
            ).execute()

            return self._format_full_message(message)

        except Exception as e:
            logger.error(f"Failed to get message content {message_id} for {user_id}: {e}")
            raise APIError(f"Failed to retrieve message content: {e}")

    async def mark_as_read(self, user_id: str, message_ids: List[str]) -> Dict[str, Any]:
        """
        Mark Gmail messages as read.

        Args:
            user_id: User UUID string
            message_ids: List of message IDs to mark as read

        Returns:
            Operation result
        """
        try:
            gmail_client = await self.get_gmail_client(user_id)

            # Batch modify to remove UNREAD label
            gmail_client.users().messages().batchModify(
                userId="me",
                body={
                    "ids": message_ids,
                    "removeLabelIds": ["UNREAD"]
                }
            ).execute()

            logger.info(f"Marked {len(message_ids)} messages as read for user {user_id}")
            return {
                "success": True,
                "marked_count": len(message_ids),
                "message": f"Marked {len(message_ids)} messages as read"
            }

        except Exception as e:
            logger.error(f"Failed to mark messages as read for {user_id}: {e}")
            raise APIError(f"Failed to mark messages as read: {e}")

    # ========== HELPER METHODS ==========

    def _format_message(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Format Gmail message for API response."""
        headers = {}
        if "payload" in message and "headers" in message["payload"]:
            for header in message["payload"]["headers"]:
                headers[header["name"].lower()] = header["value"]

        return {
            "id": message["id"],
            "thread_id": message["threadId"],
            "label_ids": message.get("labelIds", []),
            "snippet": message.get("snippet", ""),
            "from": headers.get("from", ""),
            "to": headers.get("to", ""),
            "subject": headers.get("subject", ""),
            "date": headers.get("date", ""),
            "size_estimate": message.get("sizeEstimate", 0)
        }

    def _format_full_message(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Format full Gmail message with content."""
        formatted = self._format_message(message)

        # Extract message body
        body = self._extract_message_body(message.get("payload", {}))
        formatted["body"] = body

        return formatted

    def _extract_message_body(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Extract text and HTML body from Gmail message payload."""
        body = {"text": "", "html": ""}

        def extract_parts(part):
            if "parts" in part:
                for subpart in part["parts"]:
                    extract_parts(subpart)
            else:
                mime_type = part.get("mimeType", "")
                if mime_type == "text/plain" and "data" in part.get("body", {}):
                    import base64
                    body["text"] = base64.urlsafe_b64decode(
                        part["body"]["data"]
                    ).decode("utf-8", errors="ignore")
                elif mime_type == "text/html" and "data" in part.get("body", {}):
                    import base64
                    body["html"] = base64.urlsafe_b64decode(
                        part["body"]["data"]
                    ).decode("utf-8", errors="ignore")

        extract_parts(payload)
        return body

    # ========== HEALTH CHECK ==========

    async def health_check(self) -> Dict[str, Any]:
        """Perform health check on Gmail service."""
        try:
            # Test that auth service is available
            auth_health = await self.auth_service.health_check()

            return {
                "healthy": auth_health.get("healthy", False),
                "service": "gmail_service_v2",
                "auth_service_healthy": auth_health.get("healthy", False),
                "scopes_configured": len(self.GMAIL_SCOPES),
                "timestamp": datetime.utcnow().isoformat()
            }

        except Exception as e:
            logger.error(f"Gmail service health check failed: {e}")
            return {
                "healthy": False,
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }


# ========== FACTORY ==========

def create_gmail_service():
    """Factory function to create GmailService with dependencies."""
    from app_v2.services.auth_service import create_auth_service

    auth_service = create_auth_service()
    return GmailService(auth_service)