import secrets
from typing import Any, Dict, Optional, List
from datetime import datetime, timedelta
from uuid import uuid4

from app.core.exceptions import ValidationError, NotFoundError, AuthenticationError
from app.data.repositories.user_repository import UserRepository


class AuthService:
    """
    Authentication and authorization service for Gmail Bot SaaS.
    
    Handles:
    - Supabase JWT token validation
    - User profile management (creates profiles from auth.users)
    - Permission checking (credits, bot status)
    - Session management
    - Security audit logging
    - Rate limiting
    """
    
    def __init__(self, user_repository: UserRepository):
        self.user_repository = user_repository
        # In-memory stores for demo/testing - would be Redis/DB in production
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._audit_logs: List[Dict[str, Any]] = []
        self._security_logs: List[Dict[str, Any]] = []
        self._rate_limits: Dict[str, Dict[str, Any]] = {}
        self._blacklisted_tokens: Dict[str, str] = {}

    # --- JWT Token Validation ---
    
    def _decode_jwt_token(self, token: str) -> Dict[str, Any]:
        """Decode JWT token. In production, this would use actual JWT library."""
        # Placeholder - would use python-jose or similar
        raise NotImplementedError("JWT decoding not implemented")

    def validate_jwt_token(self, token: str) -> Dict[str, Any]:
        """
        Validate Supabase JWT token and extract user claims.
        
        Returns validated token data with user info.
        """
        try:
            payload = self._decode_jwt_token(token)
        except Exception as e:
            raise AuthenticationError(f"Invalid token format: {str(e)}")

        # Validate required Supabase claims
        required_claims = ["sub", "email", "email_verified", "aud", "exp", "role"]
        missing_claims = [claim for claim in required_claims if claim not in payload]
        if missing_claims:
            raise AuthenticationError(f"Missing required claims: {missing_claims}")

        # Check token expiration
        exp = payload.get("exp")
        if exp < datetime.now().timestamp():
            raise AuthenticationError("Token has expired")

        # Validate email is verified
        if not payload.get("email_verified"):
            raise AuthenticationError("Email not verified")

        # Validate audience (must be authenticated user)
        if payload.get("aud") != "authenticated":
            raise AuthenticationError("Invalid audience")

        # Extract provider info
        app_metadata = payload.get("app_metadata", {})
        provider = app_metadata.get("provider", "email")

        return {
            "valid": True,
            "user_id": payload["sub"],  # This is auth.users.id
            "email": payload["email"],
            "email_verified": payload["email_verified"],
            "role": payload.get("role", "authenticated"),
            "provider": provider,
            "expires_at": datetime.fromtimestamp(exp).isoformat(),
        }

    def extract_user_data_from_jwt(self, jwt_payload: Dict[str, Any]) -> Dict[str, Any]:
        """Extract user profile data from JWT payload."""
        user_metadata = jwt_payload.get("user_metadata", {}) or {}
        app_metadata = jwt_payload.get("app_metadata", {}) or {}
        
        return {
            "user_id": jwt_payload.get("sub"),
            "email": jwt_payload.get("email"),
            "display_name": user_metadata.get("name") or user_metadata.get("full_name"),
            "picture": user_metadata.get("picture"),
            "provider": app_metadata.get("provider", "email"),
            "email_verified": jwt_payload.get("email_verified", False),
        }

    # --- User Profile Management ---
    
    def get_or_create_user_profile(self, jwt_payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get existing user profile or create new one from JWT data.
        
        This is the main entry point for user authentication.
        """
        user_id = jwt_payload.get("sub")
        if not user_id:
            raise AuthenticationError("Invalid JWT: missing user ID")
        
        # Try to get existing profile
        profile = self.user_repository.get_user_profile(user_id)
        if profile:
            return profile
        
        # Create new profile from JWT data
        user_data = self.extract_user_data_from_jwt(jwt_payload)
        profile_data = {
            "user_id": user_id,
            "display_name": user_data.get("display_name"),
            "timezone": "UTC",
            "credits_remaining": 5,  # Starter credits
            "bot_enabled": True,
        }
        
        return self.user_repository.create_user_profile(profile_data)

    def refresh_user_profile(self, user_id: str, jwt_payload: Dict[str, Any]) -> Dict[str, Any]:
        """Update user profile with latest JWT data."""
        user_data = self.extract_user_data_from_jwt(jwt_payload)
        updates = {
            "display_name": user_data.get("display_name"),
        }
        return self.user_repository.update_user_profile(user_id, updates)

    def get_current_user(self, token: Optional[str]) -> Dict[str, Any]:
        """
        Get current user profile from token.
        
        Main method used by API endpoints to get authenticated user.
        """
        if not token:
            raise AuthenticationError("No token provided")
        
        # Validate token
        validated_token = self.validate_jwt_token(token)
        
        # Get JWT payload for profile creation
        jwt_payload = self._decode_jwt_token(token)
        
        # Get or create user profile
        return self.get_or_create_user_profile(jwt_payload)

    # --- Authorization & Permissions ---
    
    def check_user_permissions(self, user_data: Dict[str, Any], action: str) -> Dict[str, Any]:
        """
        Check if user has permission for specific action.
        
        Based on user profile data (credits, bot status, etc.).
        """
        if action == "email_processing":
            # Check if user has credits for email processing
            credits = user_data.get("credits_remaining", 0)
            if credits <= 0:
                return {"allowed": False, "reason": "Insufficient credits"}
            
            # Check if bot is enabled
            bot_enabled = user_data.get("bot_enabled", False)
            if not bot_enabled:
                return {"allowed": False, "reason": "Bot is disabled"}
            
            return {"allowed": True, "reason": None}
        
        elif action in ["dashboard_access", "gmail_connection", "credit_purchase", "profile_update"]:
            # These actions always allowed for authenticated users
            return {"allowed": True, "reason": None}
        
        else:
            raise ValidationError(f"Unknown permission action: {action}")

    def create_user_context(self, user_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create user context for FastAPI dependency injection.
        
        Includes user info and permission flags.
        """
        permissions = {
            "can_process_emails": self.check_user_permissions(user_data, "email_processing")["allowed"],
            "can_access_dashboard": self.check_user_permissions(user_data, "dashboard_access")["allowed"],
            "can_connect_gmail": self.check_user_permissions(user_data, "gmail_connection")["allowed"],
            "can_purchase_credits": self.check_user_permissions(user_data, "credit_purchase")["allowed"],
        }
        
        return {
            "context_id": uuid4().hex,
            "created_at": datetime.utcnow().isoformat(),
            "user_id": user_data.get("user_id"),
            "display_name": user_data.get("display_name"),
            "credits_remaining": user_data.get("credits_remaining", 0),
            "bot_enabled": user_data.get("bot_enabled", False),
            "is_authenticated": True,
            "permissions": permissions,
        }

    # --- Token Utilities ---
    
    def extract_token_from_header(self, authorization_header: Optional[str]) -> Optional[str]:
        """Extract Bearer token from Authorization header."""
        if not authorization_header:
            return None
        
        parts = authorization_header.split(" ", 1)
        if len(parts) != 2 or parts[0] != "Bearer":
            raise AuthenticationError("Invalid authorization header format")
        
        return parts[1]

    # --- Session Management ---
    
    def create_user_session(self, user_data: Dict[str, Any], session_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create new user session."""
        if not user_data or not user_data.get("user_id"):
            raise ValidationError("user_id is required")
        
        session_id = uuid4().hex
        now = datetime.utcnow()
        expires_at = now + timedelta(hours=24)
        
        session = {
            "session_id": session_id,
            "user_id": user_data["user_id"],
            "ip_address": session_data.get("ip_address"),
            "user_agent": session_data.get("user_agent"),
            "created_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
        }
        
        self._sessions[session_id] = session
        return session.copy()

    def validate_user_session(self, session_id: str) -> Dict[str, Any]:
        """Validate existing user session."""
        session = self._sessions.get(session_id)
        if not session:
            return {"valid": False, "reason": "Session not found"}
        
        expires_at = datetime.fromisoformat(session["expires_at"])
        if expires_at < datetime.utcnow():
            return {"valid": False, "reason": "Session has expired"}
        
        return {
            "valid": True,
            "user_id": session["user_id"],
            "expires_at": session["expires_at"],
        }

    def invalidate_user_session(self, session_id: str) -> bool:
        """Invalidate a user session."""
        return self._sessions.pop(session_id, None) is not None

    def invalidate_all_user_sessions(self, user_id: str) -> Dict[str, Any]:
        """Invalidate all sessions for a user."""
        sessions_to_remove = [
            sid for sid, session in self._sessions.items()
            if session.get("user_id") == user_id
        ]
        
        for session_id in sessions_to_remove:
            del self._sessions[session_id]
        
        return {"invalidated_count": len(sessions_to_remove)}

    def get_user_sessions(self, user_id: str) -> List[Dict[str, Any]]:
        """Get all active sessions for a user."""
        return [
            session.copy() for session in self._sessions.values()
            if session.get("user_id") == user_id
        ]

    def cleanup_expired_sessions(self) -> Dict[str, Any]:
        """Clean up expired sessions."""
        now = datetime.utcnow()
        expired_sessions = []
        
        for session_id, session in list(self._sessions.items()):
            expires_at = datetime.fromisoformat(session["expires_at"])
            if expires_at < now:
                expired_sessions.append(session_id)
        
        for session_id in expired_sessions:
            del self._sessions[session_id]
        
        return {
            "cleaned_count": len(expired_sessions),
            "total_active_sessions": len(self._sessions),
        }

    # --- Security & Audit Logging ---
    
    def audit_log_authentication(self, user_data: Optional[Dict[str, Any]], event_type: str, metadata: Dict[str, Any]) -> None:
        """Log authentication events for security monitoring."""
        log_entry = {
            "user_id": user_data.get("user_id") if user_data else None,
            "event_type": event_type,
            "metadata": metadata.copy(),
            "timestamp": datetime.utcnow().isoformat(),
        }
        
        if user_data:
            self._audit_logs.append(log_entry)
        else:
            self._security_logs.append(log_entry)

    def get_user_audit_logs(self, user_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Get audit logs for a specific user."""
        user_logs = [
            log for log in self._audit_logs
            if log.get("user_id") == user_id
        ]
        user_logs.sort(key=lambda x: x["timestamp"], reverse=True)
        return user_logs[:limit]

    def get_security_audit_logs(self, event_type: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """Get security audit logs."""
        logs = self._security_logs
        if event_type:
            logs = [log for log in logs if log.get("event_type") == event_type]
        
        logs.sort(key=lambda x: x["timestamp"], reverse=True)
        return logs[:limit]

    # --- Rate Limiting ---
    
    def check_rate_limit(self, ip_address: str, action: str) -> Dict[str, Any]:
        """Check if request is within rate limits."""
        key = f"{ip_address}:{action}"
        now = datetime.utcnow()
        
        # Get or create rate limit entry
        if key not in self._rate_limits:
            self._rate_limits[key] = {
                "attempts": 0,
                "window_start": now,
                "limit": 60,  # 60 requests per hour
            }
        
        rate_limit = self._rate_limits[key]
        
        # Reset window if needed
        window_duration = timedelta(hours=1)
        if now - rate_limit["window_start"] > window_duration:
            rate_limit["attempts"] = 0
            rate_limit["window_start"] = now
        
        # Check limit
        rate_limit["attempts"] += 1
        limit = rate_limit["limit"]
        attempts = rate_limit["attempts"]
        
        allowed = attempts <= limit
        remaining = max(limit - attempts, 0)
        reset_time = (rate_limit["window_start"] + window_duration).isoformat()
        
        return {
            "allowed": allowed,
            "remaining": remaining,
            "reset_time": reset_time,
        }

    # --- Token Blacklisting ---
    
    def check_token_blacklist(self, token: str) -> Dict[str, Any]:
        """Check if token is blacklisted."""
        blacklisted = token in self._blacklisted_tokens
        reason = self._blacklisted_tokens.get(token) if blacklisted else None
        
        return {"blacklisted": blacklisted, "reason": reason}

    def add_token_to_blacklist(self, token: str, reason: str) -> bool:
        """Add token to blacklist."""
        self._blacklisted_tokens[token] = reason
        return True

    # --- Statistics ---
    
    def get_auth_statistics(self) -> Dict[str, Any]:
        """Get authentication statistics."""
        today = datetime.utcnow().date().isoformat()
        
        # Count login attempts today
        login_success = len([
            log for log in self._audit_logs
            if log.get("event_type", "").startswith("login") and 
            log.get("timestamp", "").startswith(today)
        ])
        
        login_failure = len([
            log for log in self._security_logs
            if log.get("event_type", "").startswith("login") and 
            log.get("timestamp", "").startswith(today)
        ])
        
        total_attempts = login_success + login_failure
        success_rate = (login_success / total_attempts) if total_attempts > 0 else 0.0
        
        return {
            "total_users": self.user_repository.count_user_profiles(),
            "active_sessions": len(self._sessions),
            "login_attempts_today": total_attempts,
            "failed_logins_today": login_failure,
            "success_rate": round(success_rate, 2),
            "avg_session_duration": 0.0,  # Could be calculated from session data
        }