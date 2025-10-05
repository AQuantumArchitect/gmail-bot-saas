# app_v2/services/auth_service.py
"""
PHOENIX AUTH SERVICE - Clean Supabase Auth Integration
Proper implementation using Supabase Auth + Vault for token management.

PRINCIPLES:
- Native Supabase Auth integration (no custom JWT generation)
- Vault-based OAuth token storage
- Clean JWT validation using python-jose
- Proper error handling and security
- Minimal, focused responsibilities
"""
import logging
from typing import Any, Dict, Optional
from datetime import datetime, timedelta
from uuid import UUID

import jwt
from jwt import PyJWTError

from app_v2.core.config import settings
from app_v2.core.exceptions import (
    ValidationError,
    AuthenticationError,
    NotFoundError
)
from app_v2.external.supabase_client import SupabaseClient
from app_v2.data.repositories.user_repository import UserRepository

logger = logging.getLogger(__name__)


class AuthService:
    """
    PHOENIX AUTH SERVICE

    Clean, focused authentication service that:
    - Validates Supabase JWTs (no custom token generation)
    - Manages user context for API requests
    - Integrates with user repository for profile management
    - Uses Supabase Admin API for vault access
    """

    def __init__(self, supabase_client: SupabaseClient, user_repository: UserRepository):
        self.supabase = supabase_client
        self.user_repository = user_repository
        self.jwt_secret = settings.database_jwt_secret

    # ========== CORE JWT VALIDATION ==========

    def validate_supabase_jwt(self, token: str) -> Dict[str, Any]:
        """
        Validate Supabase JWT token and extract user claims.
        This is the ONLY JWT validation method we need.

        Args:
            token: Supabase JWT token from frontend

        Returns:
            Validated token payload with user info

        Raises:
            AuthenticationError: Invalid or expired token
        """
        if not token:
            raise AuthenticationError("No token provided")

        if not self.jwt_secret:
            raise AuthenticationError("JWT secret not configured")

        try:
            # Decode and validate the Supabase JWT
            payload = jwt.decode(
                token,
                self.jwt_secret,
                algorithms=["HS256"],
                audience="authenticated"  # Supabase default audience
            )

            # Validate required claims
            required_claims = ["sub", "email", "aud", "exp", "role"]
            missing_claims = [claim for claim in required_claims if claim not in payload]
            if missing_claims:
                raise AuthenticationError(f"Missing required claims: {missing_claims}")

            # Validate token hasn't expired
            exp = payload.get("exp")
            if exp < datetime.utcnow().timestamp():
                raise AuthenticationError("Token has expired")

            # Validate role
            role = payload.get("role")
            if role not in ["authenticated", "service_role"]:
                raise AuthenticationError(f"Invalid role: {role}")

            logger.info(f"Valid JWT for user: {payload.get('sub')}")
            return payload

        except PyJWTError as e:
            logger.warning(f"JWT validation failed: {e}")
            raise AuthenticationError(f"Invalid token: {e}")
        except Exception as e:
            logger.error(f"JWT validation error: {e}")
            raise AuthenticationError("Token validation failed")

    def extract_token_from_header(self, authorization_header: Optional[str]) -> Optional[str]:
        """Extract Bearer token from Authorization header."""
        if not authorization_header:
            return None

        parts = authorization_header.split(" ", 1)
        if len(parts) != 2 or parts[0] != "Bearer":
            raise AuthenticationError("Invalid authorization header format")

        return parts[1]

    # ========== USER CONTEXT MANAGEMENT ==========

    async def get_current_user(self, token: str) -> Dict[str, Any]:
        """
        Get current user from validated Supabase JWT.
        Creates user profile if it doesn't exist.

        Args:
            token: Supabase JWT token

        Returns:
            User context with profile data and permissions
        """
        # Validate JWT and get payload
        jwt_payload = self.validate_supabase_jwt(token)
        user_id = UUID(jwt_payload["sub"])

        # Get or create user profile
        user_settings = await self.user_repository.get_user_settings(user_id)

        if not user_settings:
            # Create new user profile from JWT data
            profile_data = {
                "user_id": user_id,
                "email": jwt_payload["email"],
                "display_name": jwt_payload.get("user_metadata", {}).get("name"),
                "timezone": "UTC",
                "bot_enabled": False,  # Default disabled
                "processing_frequency_minutes": 60
            }
            user_settings = await self.user_repository.create_user_settings(profile_data)
            logger.info(f"Created new user profile for {user_id}")

        # Build user context
        return {
            "user_id": str(user_settings.user_id),
            "email": user_settings.email,
            "display_name": user_settings.display_name,
            "timezone": user_settings.timezone,
            "bot_enabled": user_settings.bot_enabled,
            "credits_remaining": 0,  # Will be fetched from billing service
            "created_at": user_settings.created_at.isoformat(),
            "permissions": self._calculate_permissions(user_settings),
            "jwt_claims": jwt_payload
        }

    def _calculate_permissions(self, user_settings) -> Dict[str, bool]:
        """Calculate user permissions based on profile data."""
        return {
            "can_process_emails": user_settings.bot_enabled,
            "can_access_dashboard": True,  # All authenticated users
            "can_connect_gmail": True,     # All authenticated users
            "can_purchase_credits": True,  # All authenticated users
            "can_manage_settings": True    # All authenticated users
        }

    # ========== OAUTH TOKEN MANAGEMENT (VAULT) ==========

    async def get_gmail_tokens(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Get Gmail OAuth tokens from Supabase Auth.
        Uses provider_token from Supabase Auth with optional Vault fallback.

        Args:
            user_id: User UUID string

        Returns:
            OAuth tokens with access_token, or None if not found
        """
        try:
            # Method 1: Get provider token from Supabase Auth
            user_query = """
            SELECT
                raw_user_meta_data,
                identities
            FROM auth.users
            WHERE id = $1
            """

            result = await self.supabase.execute_query(user_query, [user_id])

            if result and len(result) > 0:
                user_data = result[0]
                identities = user_data.get('identities', [])

                # Find Google identity with provider token
                for identity in identities:
                    if identity.get('provider') == 'google':
                        # Check for provider_token or access_token
                        access_token = (
                            identity.get('provider_token') or
                            identity.get('access_token')
                        )

                        if access_token:
                            logger.info(f"✅ Found Google provider token for user {user_id}")
                            return {
                                'access_token': access_token,
                                'refresh_token': identity.get('refresh_token'),
                                'token_type': 'Bearer',
                                'expires_in': identity.get('expires_in'),
                                'source': 'supabase_auth'
                            }

            # Method 2: Fallback to Vault storage (if custom RPC exists)
            try:
                vault_result = await self.supabase.execute_rpc(
                    "get_user_provider_tokens",
                    {"user_uuid": user_id, "provider": "google"}
                )

                if vault_result and "access_token" in vault_result:
                    logger.info(f"✅ Retrieved Gmail tokens from Vault for user {user_id}")
                    return {**vault_result, 'source': 'vault'}
            except Exception as vault_error:
                logger.debug(f"Vault fallback failed (normal if RPC doesn't exist): {vault_error}")

            logger.warning(f"⚠️ No Gmail tokens found for user {user_id}")
            return None

        except Exception as e:
            logger.error(f"❌ Failed to get Gmail tokens for {user_id}: {e}")
            return None

    async def store_gmail_tokens(self, user_id: str, tokens: Dict[str, Any]) -> bool:
        """
        Store Gmail OAuth tokens in Supabase Vault.

        Args:
            user_id: User UUID string
            tokens: OAuth token data from Google

        Returns:
            True if successful, False otherwise
        """
        try:
            # Use Supabase Admin API to store provider tokens
            response = await self.supabase.execute_rpc(
                "store_user_provider_tokens",
                {
                    "user_uuid": user_id,
                    "provider": "google",
                    "tokens": tokens
                }
            )

            logger.info(f"Stored Gmail tokens in vault for user {user_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to store Gmail tokens in vault for {user_id}: {e}")
            return False

    async def refresh_gmail_tokens(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Refresh Gmail OAuth tokens using vault-stored refresh token.

        Args:
            user_id: User UUID string

        Returns:
            New token data, or None if refresh failed
        """
        try:
            # Use Supabase Admin API to refresh provider tokens
            response = await self.supabase.execute_rpc(
                "refresh_user_provider_tokens",
                {"user_uuid": user_id, "provider": "google"}
            )

            if response and "access_token" in response:
                logger.info(f"Refreshed Gmail tokens from vault for user {user_id}")
                return response

            return None

        except Exception as e:
            logger.error(f"Failed to refresh Gmail tokens for {user_id}: {e}")
            return None

    async def revoke_gmail_tokens(self, user_id: str) -> bool:
        """
        Revoke and delete Gmail OAuth tokens from vault.

        Args:
            user_id: User UUID string

        Returns:
            True if successful, False otherwise
        """
        try:
            # Use Supabase Admin API to revoke provider tokens
            response = await self.supabase.execute_rpc(
                "revoke_user_provider_tokens",
                {"user_uuid": user_id, "provider": "google"}
            )

            logger.info(f"Revoked Gmail tokens from vault for user {user_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to revoke Gmail tokens for {user_id}: {e}")
            return False

    # ========== USER MANAGEMENT ==========

    async def update_user_profile(self, user_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update user profile settings.

        Args:
            user_id: User UUID string
            updates: Profile updates

        Returns:
            Updated user context
        """
        user_uuid = UUID(user_id)
        updated_settings = await self.user_repository.update_user_settings(user_uuid, updates)

        # Return updated context
        return {
            "user_id": str(updated_settings.user_id),
            "email": updated_settings.email,
            "display_name": updated_settings.display_name,
            "timezone": updated_settings.timezone,
            "bot_enabled": updated_settings.bot_enabled,
            "updated_at": updated_settings.updated_at.isoformat(),
            "permissions": self._calculate_permissions(updated_settings)
        }

    async def delete_user_account(self, user_id: str) -> bool:
        """
        Delete user account and all associated data.

        Args:
            user_id: User UUID string

        Returns:
            True if successful, False otherwise
        """
        try:
            user_uuid = UUID(user_id)

            # Revoke OAuth tokens first
            await self.revoke_gmail_tokens(user_id)

            # Delete user settings
            settings_deleted = await self.user_repository.delete_user_settings(user_uuid)

            # Delete from Supabase Auth (this would require admin API)
            auth_deleted = await self.supabase.execute_rpc(
                "delete_user_account",
                {"user_uuid": user_id}
            )

            logger.info(f"Deleted user account: {user_id}")
            return settings_deleted and auth_deleted

        except Exception as e:
            logger.error(f"Failed to delete user account {user_id}: {e}")
            return False

    # ========== HEALTH CHECK ==========

    async def health_check(self) -> Dict[str, Any]:
        """Perform health check on auth service."""
        try:
            # Test JWT secret is configured
            jwt_configured = bool(self.jwt_secret)

            # Test user repository connectivity
            repo_health = await self.user_repository.health_check()

            # Test Supabase connectivity
            supabase_health = await self.supabase.health_check()

            healthy = (
                jwt_configured and
                repo_health.get("healthy", False) and
                supabase_health.get("status") == "healthy"
            )

            return {
                "healthy": healthy,
                "service": "auth_service_v2",
                "jwt_configured": jwt_configured,
                "user_repository": repo_health.get("healthy", False),
                "supabase_client": supabase_health.get("status") == "healthy",
                "timestamp": datetime.utcnow().isoformat()
            }

        except Exception as e:
            logger.error(f"Auth service health check failed: {e}")
            return {
                "healthy": False,
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }


# ========== FACTORY ==========

def create_auth_service() -> AuthService:
    """Factory function to create AuthService with dependencies."""
    from app_v2.external.supabase_client import get_supabase_client
    from app_v2.data.repositories.user_repository import create_user_repository

    supabase_client = get_supabase_client()
    user_repository = create_user_repository("production")

    return AuthService(supabase_client, user_repository)