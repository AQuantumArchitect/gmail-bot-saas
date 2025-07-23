import time
import secrets
import urllib.parse
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta
from uuid import uuid4

import httpx

from app.core.config import settings
from app.core.exceptions import ValidationError, NotFoundError, AuthenticationError
from app.data.repositories.gmail_repository import GmailRepository
from app.data.repositories.user_repository import UserRepository


class GmailOAuthService:
    """
    Service layer for Gmail OAuth flows and connection management.
    """
    AUTH_BASE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    REVOKE_URL = "https://oauth2.googleapis.com/revoke"
    USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
    DEFAULT_SCOPES = [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/gmail.send",
    ]

    def __init__(
        self,
        gmail_repository: GmailRepository,
        user_repository: UserRepository
    ):
        self.gmail_repository = gmail_repository
        self.user_repository = user_repository
        # Recommendation: Move state to a persistent cache (e.g., Redis) or DB
        # to support multi-instance deployments and enhance security.
        self._oauth_states: Dict[str, Dict[str, Any]] = {}
        self._oauth_audit_logs: List[Dict[str, Any]] = []

    # --- Public API for OAuth Flow ---

    def generate_oauth_url(
        self,
        user_id: str,
        state: str,
        scopes: Optional[List[str]] = None,
    ) -> Dict[str, str]:
        """Builds and returns the Google OAuth consent screen URL."""
        if not user_id:
            raise ValidationError("user_id is required")
        if not state:
            raise ValidationError("state is required")

        scope_list = scopes or self.DEFAULT_SCOPES
        params = {
            "client_id": settings.google_client_id,
            "redirect_uri": settings.redirect_uri,
            "response_type": "code",
            "scope": " ".join(scope_list),
            "access_type": "offline",
            "include_granted_scopes": "true",
            "state": state,
            "prompt": "consent"
        }
        oauth_url = f"{self.AUTH_BASE_URL}?{urllib.parse.urlencode(params)}"
        
        # Store state with a timestamp for expiration
        self._oauth_states[state] = {
            "state": state,
            "user_id": user_id,
            "created_at": self._utc_now_iso()
        }
        return {"oauth_url": oauth_url, "state": state}

    async def complete_oauth_flow(
        self,
        user_id: str,
        code: str,
        state: str
    ) -> Dict[str, Any]:
        """Completes the OAuth flow after user is redirected back."""
        # Validate state to prevent CSRF attacks
        self._validate_oauth_state(state, user_id)

        if not self.user_repository.get_user_profile(user_id):
            raise NotFoundError("User not found")

        tokens = await self._exchange_code_for_tokens(code)
        access_token = tokens.get("access_token")

        # Verify token response
        if not access_token or "refresh_token" not in tokens:
            raise AuthenticationError("Invalid token data received from Google.")

        info = await self._fetch_user_profile(access_token)
        
        # Validate scopes granted by the user
        granted_scopes = tokens.get("scope", "").split()
        scope_validation = self.validate_scopes(self.DEFAULT_SCOPES, granted_scopes)
        if not scope_validation["valid"]:
            # Optionally, raise an error or log a warning about missing scopes
            self._log_oauth_event(user_id, "oauth_scope_mismatch", {"missing": scope_validation["missing_scopes"]})

        # Persist the connection details
        if not self.gmail_repository.store_oauth_tokens(user_id, tokens, info):
            raise Exception("Failed to store OAuth tokens")

        expires_at = self.calculate_token_expiry(tokens.get("expires_in", 0))["expires_at"]
        
        return {
            "success": True, 
            "user_id": user_id, 
            "email": info.get("email"), 
            "connection_status": "connected", 
            "expires_at": expires_at
        }

    # --- Public API for Connection Management ---

    async def refresh_access_token(self, user_id: str) -> Dict[str, Any]:
        """Refreshes an expired access token using the stored refresh token."""
        if not self.gmail_repository.get_oauth_tokens(user_id):
            raise NotFoundError("Gmail connection not found for user")
        try:
            result = self.gmail_repository.refresh_access_token(user_id)
            self._log_oauth_event(user_id, "token_refreshed", {"success": True})
            return result
        except Exception as e:
            self._log_oauth_event(user_id, "token_refresh_failed", {"error": str(e)})
            self.gmail_repository.update_connection_status(user_id, "error")
            raise AuthenticationError(f"Token refresh failed: {e}")

    async def revoke_connection(self, user_id: str) -> Dict[str, Any]:
        """Revokes the Google token and deletes the local connection."""
        conn = self.gmail_repository.get_oauth_tokens(user_id)
        if not conn:
            return {"success": False, "user_id": user_id, "error": "No Gmail connection found"}

        warnings: List[str] = []
        try:
            async with self._get_http_client() as client:
                resp = await client.post(self.REVOKE_URL, params={"token": conn.get("access_token")})
                resp.raise_for_status()
                self._log_oauth_event(user_id, "google_token_revoked", {})
        except httpx.HTTPStatusError as e:
            error_context = f"google_revocation_failed: {e.response.text}"
            warnings.append(error_context)
            self._log_oauth_event(user_id, "google_revoke_failed", {"error": error_context})
        
        deleted = self.gmail_repository.delete_connection(user_id)
        return {"success": deleted, "user_id": user_id, "revoked_at": self._utc_now_iso(), "warnings": warnings}

    async def validate_connection(self, user_id: str) -> Dict[str, Any]:
        """Checks if the current access token is still valid with Google."""
        tokens = self.gmail_repository.get_oauth_tokens(user_id)
        if not tokens:
            return {"valid": False, "user_id": user_id, "error": "No Gmail connection found"}
        try:
            await self._validate_token_with_google(tokens.get("access_token"))
            return {"valid": True, "user_id": user_id, "validated_at": self._utc_now_iso(), "error": None}
        except AuthenticationError as e:
            return {"valid": False, "user_id": user_id, "error": str(e)}

    # --- Public API for Information and Stats ---

    def check_connection_status(self, user_id: str) -> Dict[str, Any]:
        """Checks the connection status from the repository."""
        info = self.gmail_repository.get_connection_info(user_id)
        if not info:
            return {"connected": False, "status": "not_connected", "email": None, "error": None}
        
        status = info.get("connection_status")
        email = info.get("email_address")
        error = info.get("error_info", {}).get("error_description")
        
        return {"connected": status == "connected", "status": status, "email": email, "error": error}

    def get_connection_info(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves connection information from the repository."""
        return self.gmail_repository.get_connection_info(user_id)

    def get_connections_needing_refresh(self, threshold_minutes: int = 5) -> List[Dict[str, Any]]:
        """Finds connections with tokens that are about to expire."""
        return self.gmail_repository.get_connections_needing_refresh(threshold_minutes=threshold_minutes)

    def get_oauth_statistics(self) -> Dict[str, Any]:
        """Returns connection statistics from the repository."""
        return self.gmail_repository.get_connection_stats()

    # --- Bulk Operations and Maintenance ---

    async def bulk_refresh_tokens(self, user_ids: List[str]) -> Dict[str, Any]:
        """Performs token refresh for a list of users."""
        total = len(user_ids)
        success_count = 0
        results: List[Dict[str, Any]] = []
        for uid in user_ids:
            try:
                res = await self.refresh_access_token(uid)
                results.append({"user_id": uid, "success": True, **res})
                success_count += 1
            except Exception:
                results.append({"user_id": uid, "success": False})
        return {"total_requested": total, "successful_refreshes": success_count, "failed_refreshes": total - success_count, "results": results}

    def cleanup_expired_states(self) -> Dict[str, Any]:
        """Cleans up expired OAuth states from memory."""
        count = self._cleanup_expired_oauth_states()
        return {"cleaned_count": count, "cleanup_time": self._utc_now_iso()}

    # --- Auditing and Utilities ---

    def audit_oauth_event(self, user_id: Optional[str], event_type: str, metadata: Dict[str, Any]):
        """Logs an audit event for OAuth activities."""
        self._log_oauth_event(user_id, event_type, metadata)

    def get_oauth_audit_log(self, user_id: str) -> List[Dict[str, Any]]:
        """Retrieves audit logs for a specific user."""
        return self._get_oauth_audit_log(user_id)

    def calculate_token_expiry(self, expires_in: int) -> Dict[str, Any]:
        """Calculates the token's absolute expiry timestamp."""
        now = datetime.utcnow()
        expires_at = now + timedelta(seconds=expires_in or 3599) # Default to ~1hr if not provided
        return {"expires_at": expires_at.isoformat(), "expires_in_seconds": expires_in}

    def validate_scopes(self, required_scopes: List[str], granted_scopes: List[str]) -> Dict[str, Any]:
        """Compares required scopes against granted scopes."""
        required = set(required_scopes)
        granted = set(granted_scopes)
        missing = list(required - granted)
        extra = list(granted - required)
        return {"valid": not missing, "missing_scopes": missing, "extra_scopes": extra}

    # --- Internal Helper Methods ---

    def _get_http_client(self) -> httpx.AsyncClient:
        """Centralized HTTP client creation for easier testing and configuration."""
        # Future-proofing: Add retry/backoff logic here for handling 429/5xx errors
        # from Google APIs using a transport like `httpx.AsyncHTTPTransport(retries=3)`.
        return httpx.AsyncClient()

    async def _exchange_code_for_tokens(self, code: str) -> Dict[str, Any]:
        """Encapsulates the token exchange HTTP request."""
        data = {
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": settings.redirect_uri,
            "grant_type": "authorization_code"
        }
        try:
            async with self._get_http_client() as client:
                resp = await client.post(self.TOKEN_URL, data=data)
                resp.raise_for_status()
                return resp.json()
        except httpx.RequestError as e:
            raise AuthenticationError(f"Network error during token exchange: {e.request.url}")
        except httpx.HTTPStatusError as e:
            error_details = e.response.json()
            raise AuthenticationError(f"API Error during token exchange: {error_details}")

    async def _fetch_user_profile(self, access_token: str) -> Dict[str, Any]:
        """Encapsulates the user info fetching request."""
        headers = self._build_auth_headers(access_token)
        try:
            async with self._get_http_client() as client:
                resp = await client.get(self.USERINFO_URL, headers=headers)
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPStatusError as e:
            raise AuthenticationError(f"Failed to fetch user info: {e.response.text}")
    
    def _validate_oauth_state(self, state: str, user_id: str):
        """Validates the state parameter to ensure it's valid, not expired, and matches the user."""
        rec = self._oauth_states.get(state)
        if not rec:
            raise AuthenticationError("Invalid or expired state parameter.")
        if rec.get("user_id") != user_id:
            raise AuthenticationError("State parameter user mismatch.")
        
        created = datetime.fromisoformat(rec.get("created_at"))
        if created < datetime.utcnow() - timedelta(minutes=10):
            raise AuthenticationError("State parameter has expired.")

    async def _validate_token_with_google(self, token: str) -> bool:
        """Placeholder for using Google's tokeninfo endpoint for validation."""
        # For a real implementation, you would call:
        # https://www.googleapis.com/oauth2/v3/tokeninfo?access_token=TOKEN
        return True

    def _cleanup_expired_oauth_states(self) -> int:
        """Internal implementation for cleaning expired states."""
        cutoff = datetime.utcnow() - timedelta(minutes=15)
        to_delete = [s for s, rec in self._oauth_states.items() if datetime.fromisoformat(rec.get("created_at")) < cutoff]
        for s in to_delete:
            del self._oauth_states[s]
        return len(to_delete)

    def _log_oauth_event(self, user_id: Optional[str], event_type: str, metadata: Dict[str, Any]):
        """Internal implementation for logging audit events."""
        self._oauth_audit_logs.append({
            "log_id": str(uuid4()),
            "user_id": user_id,
            "event_type": event_type,
            "metadata": metadata.copy(),
            "timestamp": self._utc_now_iso()
        })

    def _get_oauth_audit_log(self, user_id: str) -> List[Dict[str, Any]]:
        """Internal implementation for retrieving audit logs."""
        logs = [log for log in self._oauth_audit_logs if log.get("user_id") == user_id]
        logs.sort(key=lambda l: l.get("timestamp"), reverse=True)
        return logs
    
    def _build_auth_headers(self, token: str) -> Dict[str, str]:
        """Creates standardized authorization headers."""
        return {"Authorization": f"Bearer {token}"}

    def _utc_now_iso(self) -> str:
        """Returns the current UTC time as an ISO 8601 string for consistency."""
        return datetime.utcnow().isoformat()