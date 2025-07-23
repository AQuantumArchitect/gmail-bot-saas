# app/external/gmail_client.py
"""
Gmail API Client - External service integration for Gmail API operations.
Provides OAuth flow, token management, and email operations with proper error handling.
"""
import logging
import base64
import asyncio
import time
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import httpx
from urllib.parse import urlencode

from app.core.config import settings
from app.core.exceptions import AuthenticationError, APIError, ValidationError

logger = logging.getLogger(__name__)


class GmailClient:
    """
    Gmail API client with OAuth 2.0 support, retry logic, and proper error handling.
    Handles token management, email fetching, and sending operations.
    """
    
    # Google OAuth 2.0 endpoints
    OAUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    REVOKE_URL = "https://oauth2.googleapis.com/revoke"
    USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
    
    # Gmail API endpoints
    GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1"
    
    # OAuth scopes
    DEFAULT_SCOPES = [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.send",
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/userinfo.profile"
    ]
    
    # Rate limiting
    MAX_REQUESTS_PER_MINUTE = 250
    MAX_REQUESTS_PER_SECOND = 5
    
    def __init__(self):
        self.client_id = settings.google_client_id
        self.client_secret = settings.google_client_secret
        self.redirect_uri = settings.redirect_uri
        
        # Rate limiting state
        self._request_times = []
        self._last_request_time = 0
        
        # Circuit breaker state
        self._circuit_breaker = {
            "failure_count": 0,
            "last_failure": None,
            "state": "closed"  # closed, open, half-open
        }
    
    # --- OAuth 2.0 Flow ---
    
    def get_oauth_url(self, state: str, scopes: Optional[List[str]] = None) -> str:
        """
        Generate OAuth 2.0 authorization URL.
        
        Args:
            state: CSRF protection state parameter
            scopes: Optional custom scopes (defaults to DEFAULT_SCOPES)
            
        Returns:
            OAuth authorization URL
        """
        if not state:
            raise ValidationError("State parameter is required")
        
        scopes = scopes or self.DEFAULT_SCOPES
        
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": " ".join(scopes),
            "response_type": "code",
            "state": state,
            "access_type": "offline",
            "prompt": "consent"
        }
        
        return f"{self.OAUTH_URL}?{urlencode(params)}"
    
    async def exchange_code_for_tokens(self, code: str) -> Dict[str, Any]:
        """
        Exchange authorization code for access and refresh tokens.
        
        Args:
            code: Authorization code from OAuth callback
            
        Returns:
            Token response with access_token, refresh_token, expires_in, etc.
        """
        if not code:
            raise ValidationError("Authorization code is required")
        
        data = {
            "code": code,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": self.redirect_uri,
            "grant_type": "authorization_code"
        }
        
        try:
            async with self._get_http_client() as client:
                response = await client.post(self.TOKEN_URL, data=data)
                response.raise_for_status()
                
                token_data = response.json()
                
                # Validate token response
                if "access_token" not in token_data:
                    raise AuthenticationError("Invalid token response: missing access_token")
                
                if "refresh_token" not in token_data:
                    raise AuthenticationError("Invalid token response: missing refresh_token")
                
                logger.info("Successfully exchanged code for tokens")
                return token_data
                
        except httpx.HTTPStatusError as e:
            error_data = e.response.json() if e.response.headers.get("content-type") == "application/json" else {}
            error_msg = error_data.get("error_description", str(e))
            raise AuthenticationError(f"Token exchange failed: {error_msg}")
        except httpx.RequestError as e:
            raise APIError(f"Network error during token exchange: {e}")
    
    async def refresh_access_token(self, refresh_token: str) -> Dict[str, Any]:
        """
        Refresh access token using refresh token.
        
        Args:
            refresh_token: Valid refresh token
            
        Returns:
            New token data with access_token and expires_in
        """
        if not refresh_token:
            raise ValidationError("Refresh token is required")
        
        data = {
            "refresh_token": refresh_token,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "refresh_token"
        }
        
        try:
            async with self._get_http_client() as client:
                response = await client.post(self.TOKEN_URL, data=data)
                response.raise_for_status()
                
                token_data = response.json()
                
                if "access_token" not in token_data:
                    raise AuthenticationError("Invalid refresh response: missing access_token")
                
                logger.info("Successfully refreshed access token")
                return token_data
                
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 400:
                raise AuthenticationError("Invalid refresh token")
            error_data = e.response.json() if e.response.headers.get("content-type") == "application/json" else {}
            error_msg = error_data.get("error_description", str(e))
            raise AuthenticationError(f"Token refresh failed: {error_msg}")
        except httpx.RequestError as e:
            raise APIError(f"Network error during token refresh: {e}")
    
    async def revoke_token(self, token: str) -> bool:
        """
        Revoke access or refresh token.
        
        Args:
            token: Token to revoke
            
        Returns:
            True if revoked successfully
        """
        if not token:
            raise ValidationError("Token is required")
        
        try:
            async with self._get_http_client() as client:
                response = await client.post(self.REVOKE_URL, params={"token": token})
                response.raise_for_status()
                
                logger.info("Successfully revoked token")
                return True
                
        except httpx.HTTPStatusError as e:
            logger.warning(f"Token revocation failed: {e}")
            return False
        except httpx.RequestError as e:
            logger.warning(f"Network error during token revocation: {e}")
            return False
    
    async def get_user_info(self, access_token: str) -> Dict[str, Any]:
        """
        Get user profile information.
        
        Args:
            access_token: Valid access token
            
        Returns:
            User profile data
        """
        if not access_token:
            raise ValidationError("Access token is required")
        
        headers = {"Authorization": f"Bearer {access_token}"}
        
        try:
            async with self._get_http_client() as client:
                response = await client.get(self.USERINFO_URL, headers=headers)
                response.raise_for_status()
                
                user_data = response.json()
                logger.info(f"Retrieved user info for {user_data.get('email')}")
                return user_data
                
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise AuthenticationError("Invalid access token")
            raise APIError(f"Failed to get user info: {e}")
        except httpx.RequestError as e:
            raise APIError(f"Network error getting user info: {e}")
    
    # --- Gmail API Operations ---
    
    async def fetch_messages(
        self, 
        access_token: str, 
        query: str = "", 
        max_results: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Fetch Gmail messages matching query.
        
        Args:
            access_token: Valid access token
            query: Gmail search query
            max_results: Maximum number of messages to fetch
            
        Returns:
            List of message data
        """
        if not access_token:
            raise ValidationError("Access token is required")
        
        # Check circuit breaker
        if not self._check_circuit_breaker():
            raise APIError("Circuit breaker is open - too many failures")
        
        # Apply rate limiting
        await self._apply_rate_limit()
        
        headers = {"Authorization": f"Bearer {access_token}"}
        params = {
            "q": query,
            "maxResults": min(max_results, 500)  # Gmail API limit
        }
        
        try:
            # Get message list
            async with self._get_http_client() as client:
                response = await client.get(
                    f"{self.GMAIL_API_BASE}/users/me/messages",
                    headers=headers,
                    params=params
                )
                response.raise_for_status()
                
                messages_data = response.json()
                messages = messages_data.get("messages", [])
                
                # Fetch full message details
                full_messages = []
                for message in messages:
                    message_detail = await self._fetch_message_detail(
                        access_token, message["id"]
                    )
                    if message_detail:
                        full_messages.append(message_detail)
                
                self._record_success()
                logger.info(f"Fetched {len(full_messages)} messages")
                return full_messages
                
        except httpx.HTTPStatusError as e:
            self._record_failure()
            if e.response.status_code == 401:
                raise AuthenticationError("Invalid access token")
            elif e.response.status_code == 429:
                raise APIError("Rate limit exceeded")
            raise APIError(f"Failed to fetch messages: {e}")
        except httpx.RequestError as e:
            self._record_failure()
            raise APIError(f"Network error fetching messages: {e}")
    
    async def _fetch_message_detail(self, access_token: str, message_id: str) -> Optional[Dict[str, Any]]:
        """Fetch detailed message information."""
        headers = {"Authorization": f"Bearer {access_token}"}
        
        try:
            async with self._get_http_client() as client:
                response = await client.get(
                    f"{self.GMAIL_API_BASE}/users/me/messages/{message_id}",
                    headers=headers,
                    params={"format": "full"}
                )
                response.raise_for_status()
                
                message_data = response.json()
                return self._parse_message(message_data)
                
        except httpx.HTTPStatusError as e:
            logger.warning(f"Failed to fetch message {message_id}: {e}")
            return None
        except Exception as e:
            logger.warning(f"Error parsing message {message_id}: {e}")
            return None
    
    def _parse_message(self, message_data: Dict[str, Any]) -> Dict[str, Any]:
        """Parse Gmail message data into standard format."""
        payload = message_data.get("payload", {})
        headers = payload.get("headers", [])
        
        # Extract headers
        header_dict = {h["name"]: h["value"] for h in headers}
        
        # Extract content
        content = self._extract_message_content(payload)
        
        return {
            "id": message_data["id"],
            "thread_id": message_data["threadId"],
            "subject": header_dict.get("Subject", ""),
            "sender": header_dict.get("From", ""),
            "recipient": header_dict.get("To", ""),
            "date": header_dict.get("Date", ""),
            "content": content,
            "snippet": message_data.get("snippet", ""),
            "label_ids": message_data.get("labelIds", []),
            "size_estimate": message_data.get("sizeEstimate", 0),
            "internal_date": message_data.get("internalDate", "")
        }
    
    def _extract_message_content(self, payload: Dict[str, Any]) -> str:
        """Extract text content from message payload."""
        content = ""
        
        # Check direct body
        if "body" in payload and payload["body"].get("data"):
            content = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="ignore")
        
        # Check parts for multipart messages
        elif "parts" in payload:
            for part in payload["parts"]:
                if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
                    content = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="ignore")
                    break
                elif part.get("mimeType") == "text/html" and part.get("body", {}).get("data") and not content:
                    # Fallback to HTML if no plain text
                    html_content = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="ignore")
                    content = self._strip_html(html_content)
        
        return content.strip()
    
    def _strip_html(self, html: str) -> str:
        """Simple HTML tag removal."""
        import re
        return re.sub(r'<[^>]+>', '', html)
    
    async def send_message(self, access_token: str, message_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Send Gmail message.
        
        Args:
            access_token: Valid access token
            message_data: Message data with 'to', 'subject', 'body', optional 'thread_id'
            
        Returns:
            Send result with message ID
        """
        if not access_token:
            raise ValidationError("Access token is required")
        
        # Check circuit breaker
        if not self._check_circuit_breaker():
            raise APIError("Circuit breaker is open - too many failures")
        
        # Apply rate limiting
        await self._apply_rate_limit()
        
        headers = {"Authorization": f"Bearer {access_token}"}
        
        # Create email message
        email_message = self._create_email_message(message_data)
        
        payload = {
            "raw": base64.urlsafe_b64encode(email_message.encode()).decode()
        }
        
        # Add thread ID if replying
        if message_data.get("thread_id"):
            payload["threadId"] = message_data["thread_id"]
        
        try:
            async with self._get_http_client() as client:
                response = await client.post(
                    f"{self.GMAIL_API_BASE}/users/me/messages/send",
                    headers=headers,
                    json=payload
                )
                response.raise_for_status()
                
                result = response.json()
                self._record_success()
                logger.info(f"Sent message {result['id']}")
                return result
                
        except httpx.HTTPStatusError as e:
            self._record_failure()
            if e.response.status_code == 401:
                raise AuthenticationError("Invalid access token")
            elif e.response.status_code == 429:
                raise APIError("Rate limit exceeded")
            raise APIError(f"Failed to send message: {e}")
        except httpx.RequestError as e:
            self._record_failure()
            raise APIError(f"Network error sending message: {e}")
    
    def _create_email_message(self, message_data: Dict[str, Any]) -> str:
        """Create RFC 2822 email message."""
        lines = []
        
        # Headers
        lines.append(f"To: {message_data['to']}")
        lines.append(f"Subject: {message_data['subject']}")
        lines.append("Content-Type: text/plain; charset=utf-8")
        lines.append("")
        
        # Body
        lines.append(message_data['body'])
        
        return "\r\n".join(lines)
    
    async def modify_message(self, access_token: str, message_id: str, modifications: Dict[str, Any]) -> Dict[str, Any]:
        """
        Modify Gmail message (add/remove labels, mark as read, etc.).
        
        Args:
            access_token: Valid access token
            message_id: Message ID to modify
            modifications: Labels to add/remove
            
        Returns:
            Modified message data
        """
        if not access_token:
            raise ValidationError("Access token is required")
        
        if not message_id:
            raise ValidationError("Message ID is required")
        
        # Check circuit breaker
        if not self._check_circuit_breaker():
            raise APIError("Circuit breaker is open - too many failures")
        
        # Apply rate limiting
        await self._apply_rate_limit()
        
        headers = {"Authorization": f"Bearer {access_token}"}
        
        try:
            async with self._get_http_client() as client:
                response = await client.post(
                    f"{self.GMAIL_API_BASE}/users/me/messages/{message_id}/modify",
                    headers=headers,
                    json=modifications
                )
                response.raise_for_status()
                
                result = response.json()
                self._record_success()
                logger.info(f"Modified message {message_id}")
                return result
                
        except httpx.HTTPStatusError as e:
            self._record_failure()
            if e.response.status_code == 401:
                raise AuthenticationError("Invalid access token")
            elif e.response.status_code == 429:
                raise APIError("Rate limit exceeded")
            raise APIError(f"Failed to modify message: {e}")
        except httpx.RequestError as e:
            self._record_failure()
            raise APIError(f"Network error modifying message: {e}")
    
    # --- Helper Methods ---
    
    def _get_http_client(self) -> httpx.AsyncClient:
        """Get HTTP client with timeout and retry configuration."""
        return httpx.AsyncClient(
            timeout=30.0,
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=20)
        )
    
    async def _apply_rate_limit(self):
        """Apply rate limiting to prevent API quota exhaustion."""
        now = time.time()
        
        # Remove old requests (older than 1 minute)
        self._request_times = [t for t in self._request_times if now - t < 60]
        
        # Check per-minute limit
        if len(self._request_times) >= self.MAX_REQUESTS_PER_MINUTE:
            sleep_time = 60 - (now - self._request_times[0])
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)
        
        # Check per-second limit
        if now - self._last_request_time < 1.0 / self.MAX_REQUESTS_PER_SECOND:
            sleep_time = 1.0 / self.MAX_REQUESTS_PER_SECOND - (now - self._last_request_time)
            await asyncio.sleep(sleep_time)
        
        # Record this request
        self._request_times.append(time.time())
        self._last_request_time = time.time()
    
    def _check_circuit_breaker(self) -> bool:
        """Check if circuit breaker allows requests."""
        now = datetime.utcnow()
        
        if self._circuit_breaker["state"] == "open":
            # Check if we should try again (half-open)
            if (self._circuit_breaker["last_failure"] and 
                now - self._circuit_breaker["last_failure"] > timedelta(minutes=5)):
                self._circuit_breaker["state"] = "half-open"
                return True
            return False
        
        return True
    
    def _record_success(self):
        """Record successful API call."""
        self._circuit_breaker["failure_count"] = 0
        self._circuit_breaker["state"] = "closed"
    
    def _record_failure(self):
        """Record failed API call."""
        self._circuit_breaker["failure_count"] += 1
        self._circuit_breaker["last_failure"] = datetime.utcnow()
        
        if self._circuit_breaker["failure_count"] >= 5:
            self._circuit_breaker["state"] = "open"
            logger.warning("Gmail API circuit breaker opened due to failures")
    
    # --- Utility Methods ---
    
    def validate_token_response(self, token_data: Dict[str, Any]) -> bool:
        """Validate token response structure."""
        required_fields = ["access_token", "token_type"]
        return all(field in token_data for field in required_fields)
    
    def is_token_expired(self, token_data: Dict[str, Any]) -> bool:
        """Check if token is expired based on expires_in."""
        if "expires_in" not in token_data:
            return False
        
        issued_at = token_data.get("issued_at", time.time())
        expires_in = token_data.get("expires_in", 3600)
        
        return time.time() - issued_at >= expires_in
    
    def get_client_info(self) -> Dict[str, Any]:
        """Get client configuration info."""
        return {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scopes": self.DEFAULT_SCOPES,
            "circuit_breaker_state": self._circuit_breaker["state"],
            "failure_count": self._circuit_breaker["failure_count"]
        }