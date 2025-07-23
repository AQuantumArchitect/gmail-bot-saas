# tests/unit/services/test_auth_service.py
"""
Test suite for AuthService - matches clean implementation.
Tests JWT validation, user profile management, and security features.
"""
import pytest
from uuid import uuid4
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from app.services.auth_service import AuthService
from app.core.exceptions import ValidationError, NotFoundError, AuthenticationError
from app.data.repositories.user_repository import UserRepository


class TestAuthService:
    """Test suite for AuthService"""
    
    @pytest.fixture
    def mock_user_repo(self):
        """Mock UserRepository"""
        return Mock(spec=UserRepository)
    
    @pytest.fixture
    def auth_service(self, mock_user_repo):
        """Create AuthService instance"""
        return AuthService(user_repository=mock_user_repo)
    
    @pytest.fixture
    def valid_jwt_payload(self):
        """Valid JWT payload from Supabase"""
        return {
            "sub": str(uuid4()),
            "email": "user@example.com",
            "email_verified": True,
            "aud": "authenticated",
            "exp": int((datetime.now() + timedelta(hours=1)).timestamp()),
            "iat": int(datetime.now().timestamp()),
            "role": "authenticated",
            "app_metadata": {
                "provider": "google",
                "providers": ["google"]
            },
            "user_metadata": {
                "name": "John Doe",
                "picture": "https://example.com/profile.jpg"
            }
        }
    
    @pytest.fixture
    def expired_jwt_payload(self):
        """Expired JWT payload"""
        return {
            "sub": str(uuid4()),
            "email": "user@example.com",
            "email_verified": True,
            "aud": "authenticated",
            "exp": int((datetime.now() - timedelta(hours=1)).timestamp()),
            "iat": int((datetime.now() - timedelta(hours=2)).timestamp()),
            "role": "authenticated",
            "app_metadata": {"provider": "google"},
            "user_metadata": {"name": "John Doe"}
        }

    # --- JWT Token Validation Tests ---
    
    def test_validate_jwt_token_success(self, auth_service, valid_jwt_payload):
        """Test successful JWT token validation"""
        token = "valid.jwt.token"
        
        with patch.object(auth_service, '_decode_jwt_token', return_value=valid_jwt_payload):
            result = auth_service.validate_jwt_token(token)
            
            assert result["valid"] == True
            assert result["user_id"] == valid_jwt_payload["sub"]
            assert result["email"] == valid_jwt_payload["email"]
            assert result["email_verified"] == True
            assert result["role"] == "authenticated"
            assert result["provider"] == "google"
            assert result["expires_at"] is not None
    
    def test_validate_jwt_token_expired(self, auth_service, expired_jwt_payload):
        """Test JWT token validation with expired token"""
        token = "expired.jwt.token"
        
        with patch.object(auth_service, '_decode_jwt_token', return_value=expired_jwt_payload):
            with pytest.raises(AuthenticationError) as exc_info:
                auth_service.validate_jwt_token(token)
            
            assert "expired" in str(exc_info.value).lower()
    
    def test_validate_jwt_token_invalid_format(self, auth_service):
        """Test JWT token validation with invalid format"""
        token = "invalid.token"
        
        with patch.object(auth_service, '_decode_jwt_token', side_effect=ValueError("Invalid token")):
            with pytest.raises(AuthenticationError) as exc_info:
                auth_service.validate_jwt_token(token)
            
            assert "invalid token format" in str(exc_info.value).lower()
    
    def test_validate_jwt_token_missing_claims(self, auth_service):
        """Test JWT token validation with missing required claims"""
        invalid_payload = {
            "sub": str(uuid4()),
            "exp": int((datetime.now() + timedelta(hours=1)).timestamp())
            # Missing email, email_verified, aud, role
        }
        
        with patch.object(auth_service, '_decode_jwt_token', return_value=invalid_payload):
            with pytest.raises(AuthenticationError) as exc_info:
                auth_service.validate_jwt_token("token")
            
            assert "missing required claims" in str(exc_info.value).lower()
    
    def test_validate_jwt_token_unverified_email(self, auth_service, valid_jwt_payload):
        """Test JWT token validation with unverified email"""
        valid_jwt_payload["email_verified"] = False
        
        with patch.object(auth_service, '_decode_jwt_token', return_value=valid_jwt_payload):
            with pytest.raises(AuthenticationError) as exc_info:
                auth_service.validate_jwt_token("token")
            
            assert "email not verified" in str(exc_info.value).lower()
    
    def test_validate_jwt_token_invalid_audience(self, auth_service, valid_jwt_payload):
        """Test JWT token validation with invalid audience"""
        valid_jwt_payload["aud"] = "invalid_audience"
        
        with patch.object(auth_service, '_decode_jwt_token', return_value=valid_jwt_payload):
            with pytest.raises(AuthenticationError) as exc_info:
                auth_service.validate_jwt_token("token")
            
            assert "invalid audience" in str(exc_info.value).lower()

    # --- User Profile Management Tests ---
    
    def test_get_or_create_user_profile_existing(self, auth_service, mock_user_repo, valid_jwt_payload):
        """Test getting existing user profile"""
        user_id = valid_jwt_payload["sub"]
        existing_profile = {
            "user_id": user_id,
            "display_name": "John Doe",
            "credits_remaining": 25,
            "bot_enabled": True,
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z"
        }
        
        mock_user_repo.get_user_profile.return_value = existing_profile
        
        result = auth_service.get_or_create_user_profile(valid_jwt_payload)
        
        assert result == existing_profile
        mock_user_repo.get_user_profile.assert_called_once_with(user_id)
        mock_user_repo.create_user_profile.assert_not_called()
    
    def test_get_or_create_user_profile_new_user(self, auth_service, mock_user_repo, valid_jwt_payload):
        """Test creating new user profile"""
        user_id = valid_jwt_payload["sub"]
        
        # User doesn't exist
        mock_user_repo.get_user_profile.return_value = None
        
        # Mock creation
        new_profile = {
            "user_id": user_id,
            "display_name": "John Doe",
            "credits_remaining": 5,
            "bot_enabled": True,
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z"
        }
        mock_user_repo.create_user_profile.return_value = new_profile
        
        result = auth_service.get_or_create_user_profile(valid_jwt_payload)
        
        assert result == new_profile
        mock_user_repo.get_user_profile.assert_called_once_with(user_id)
        mock_user_repo.create_user_profile.assert_called_once()
        
        # Verify creation data
        create_args = mock_user_repo.create_user_profile.call_args[0][0]
        assert create_args["user_id"] == user_id
        assert create_args["display_name"] == "John Doe"
        assert create_args["credits_remaining"] == 5
        assert create_args["bot_enabled"] == True
    
    def test_get_or_create_user_profile_invalid_jwt(self, auth_service):
        """Test handling invalid JWT payload"""
        invalid_payload = {"email": "test@example.com"}  # Missing 'sub'
        
        with pytest.raises(AuthenticationError) as exc_info:
            auth_service.get_or_create_user_profile(invalid_payload)
        
        assert "missing user id" in str(exc_info.value).lower()
    
    def test_refresh_user_profile_success(self, auth_service, mock_user_repo, valid_jwt_payload):
        """Test refreshing user profile"""
        user_id = valid_jwt_payload["sub"]
        
        # Update name in JWT
        valid_jwt_payload["user_metadata"]["name"] = "John Updated Doe"
        
        updated_profile = {
            "user_id": user_id,
            "display_name": "John Updated Doe",
            "credits_remaining": 25,
            "bot_enabled": True
        }
        
        mock_user_repo.update_user_profile.return_value = updated_profile
        
        result = auth_service.refresh_user_profile(user_id, valid_jwt_payload)
        
        assert result == updated_profile
        mock_user_repo.update_user_profile.assert_called_once()
        
        # Verify update data
        update_args = mock_user_repo.update_user_profile.call_args[0]
        assert update_args[0] == user_id
        assert update_args[1]["display_name"] == "John Updated Doe"
    
    def test_get_current_user_success(self, auth_service, valid_jwt_payload):
        """Test getting current user from token"""
        token = "valid.jwt.token"
        
        with patch.object(auth_service, 'validate_jwt_token', return_value={"valid": True}):
            with patch.object(auth_service, '_decode_jwt_token', return_value=valid_jwt_payload):
                with patch.object(auth_service, 'get_or_create_user_profile', return_value={
                    "user_id": valid_jwt_payload["sub"],
                    "display_name": "John Doe",
                    "credits_remaining": 25
                }) as mock_get_profile:
                    
                    result = auth_service.get_current_user(token)
                    
                    assert result["user_id"] == valid_jwt_payload["sub"]
                    assert result["display_name"] == "John Doe"
                    assert result["credits_remaining"] == 25
                    mock_get_profile.assert_called_once()
    
    def test_get_current_user_no_token(self, auth_service):
        """Test getting current user with no token"""
        with pytest.raises(AuthenticationError) as exc_info:
            auth_service.get_current_user(None)
        
        assert "no token provided" in str(exc_info.value).lower()

    # --- Authorization & Permissions Tests ---
    
    def test_check_user_permissions_email_processing_allowed(self, auth_service):
        """Test email processing permission with sufficient credits"""
        user_data = {
            "user_id": str(uuid4()),
            "credits_remaining": 25,
            "bot_enabled": True
        }
        
        result = auth_service.check_user_permissions(user_data, "email_processing")
        
        assert result["allowed"] == True
        assert result["reason"] is None
    
    def test_check_user_permissions_insufficient_credits(self, auth_service):
        """Test email processing permission with insufficient credits"""
        user_data = {
            "user_id": str(uuid4()),
            "credits_remaining": 0,
            "bot_enabled": True
        }
        
        result = auth_service.check_user_permissions(user_data, "email_processing")
        
        assert result["allowed"] == False
        assert "insufficient credits" in result["reason"].lower()
    
    def test_check_user_permissions_bot_disabled(self, auth_service):
        """Test email processing permission with bot disabled"""
        user_data = {
            "user_id": str(uuid4()),
            "credits_remaining": 25,
            "bot_enabled": False
        }
        
        result = auth_service.check_user_permissions(user_data, "email_processing")
        
        assert result["allowed"] == False
        assert "bot is disabled" in result["reason"].lower()
    
    def test_check_user_permissions_dashboard_access(self, auth_service):
        """Test dashboard access permission"""
        user_data = {"user_id": str(uuid4())}
        
        result = auth_service.check_user_permissions(user_data, "dashboard_access")
        
        assert result["allowed"] == True
        assert result["reason"] is None
    
    def test_check_user_permissions_invalid_action(self, auth_service):
        """Test invalid permission action"""
        user_data = {"user_id": str(uuid4())}
        
        with pytest.raises(ValidationError) as exc_info:
            auth_service.check_user_permissions(user_data, "invalid_action")
        
        assert "unknown permission action" in str(exc_info.value).lower()

    # --- Token Utilities Tests ---
    
    def test_extract_token_from_header_success(self, auth_service):
        """Test extracting token from Authorization header"""
        header = "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
        
        result = auth_service.extract_token_from_header(header)
        
        assert result == "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
    
    def test_extract_token_from_header_invalid_format(self, auth_service):
        """Test extracting token from invalid header format"""
        header = "Invalid eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
        
        with pytest.raises(AuthenticationError) as exc_info:
            auth_service.extract_token_from_header(header)
        
        assert "invalid authorization header format" in str(exc_info.value).lower()
    
    def test_extract_token_from_header_none(self, auth_service):
        """Test extracting token from None header"""
        result = auth_service.extract_token_from_header(None)
        assert result is None

    # --- Session Management Tests ---
    
    def test_create_user_session_success(self, auth_service):
        """Test creating user session"""
        user_data = {
            "user_id": str(uuid4()),
            "display_name": "John Doe"
        }
        
        session_data = {
            "ip_address": "192.168.1.1",
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        
        result = auth_service.create_user_session(user_data, session_data)
        
        assert result["user_id"] == user_data["user_id"]
        assert result["ip_address"] == session_data["ip_address"]
        assert result["user_agent"] == session_data["user_agent"]
        assert "session_id" in result
        assert "created_at" in result
        assert "expires_at" in result
    
    def test_create_user_session_missing_user_id(self, auth_service):
        """Test creating session with missing user_id"""
        with pytest.raises(ValidationError) as exc_info:
            auth_service.create_user_session({}, {})
        
        assert "user_id is required" in str(exc_info.value).lower()
    
    def test_validate_user_session_success(self, auth_service):
        """Test validating user session"""
        user_data = {"user_id": str(uuid4())}
        session = auth_service.create_user_session(user_data, {})
        
        result = auth_service.validate_user_session(session["session_id"])
        
        assert result["valid"] == True
        assert result["user_id"] == user_data["user_id"]
        assert result["expires_at"] is not None
    
    def test_validate_user_session_not_found(self, auth_service):
        """Test validating non-existent session"""
        result = auth_service.validate_user_session("non_existent_session")
        
        assert result["valid"] == False
        assert "not found" in result["reason"].lower()
    
    def test_invalidate_user_session_success(self, auth_service):
        """Test invalidating user session"""
        user_data = {"user_id": str(uuid4())}
        session = auth_service.create_user_session(user_data, {})
        
        result = auth_service.invalidate_user_session(session["session_id"])
        
        assert result == True
        
        # Verify session is invalidated
        validation = auth_service.validate_user_session(session["session_id"])
        assert validation["valid"] == False
    
    def test_invalidate_all_user_sessions_success(self, auth_service):
        """Test invalidating all user sessions"""
        user_id = str(uuid4())
        user_data = {"user_id": user_id}
        
        # Create multiple sessions
        session1 = auth_service.create_user_session(user_data, {"ip_address": "192.168.1.1"})
        session2 = auth_service.create_user_session(user_data, {"ip_address": "192.168.1.2"})
        
        # Invalidate all sessions
        result = auth_service.invalidate_all_user_sessions(user_id)
        
        assert result["invalidated_count"] == 2
        
        # Verify sessions are invalidated
        validation1 = auth_service.validate_user_session(session1["session_id"])
        validation2 = auth_service.validate_user_session(session2["session_id"])
        assert validation1["valid"] == False
        assert validation2["valid"] == False

    # --- Security & Audit Tests ---
    
    def test_audit_log_authentication_success(self, auth_service):
        """Test audit logging for authentication success"""
        user_data = {"user_id": str(uuid4())}
        
        auth_service.audit_log_authentication(user_data, "login_success", {
            "ip_address": "192.168.1.1",
            "user_agent": "Mozilla/5.0"
        })
        
        # Verify audit log was created
        audit_logs = auth_service.get_user_audit_logs(user_data["user_id"], limit=1)
        assert len(audit_logs) == 1
        assert audit_logs[0]["event_type"] == "login_success"
        assert audit_logs[0]["user_id"] == user_data["user_id"]
        assert audit_logs[0]["metadata"]["ip_address"] == "192.168.1.1"
    
    def test_audit_log_authentication_failure(self, auth_service):
        """Test audit logging for authentication failure"""
        auth_service.audit_log_authentication(None, "login_failure", {
            "ip_address": "192.168.1.1",
            "error": "invalid_token"
        })
        
        # Verify security log was created
        security_logs = auth_service.get_security_audit_logs(event_type="login_failure", limit=1)
        assert len(security_logs) == 1
        assert security_logs[0]["event_type"] == "login_failure"
        assert security_logs[0]["user_id"] is None
        assert security_logs[0]["metadata"]["error"] == "invalid_token"

    # --- Rate Limiting Tests ---
    
    def test_rate_limit_check_success(self, auth_service):
        """Test rate limiting check within limits"""
        ip_address = "192.168.1.1"
        
        result = auth_service.check_rate_limit(ip_address, "login")
        
        assert result["allowed"] == True
        assert result["remaining"] > 0
        assert result["reset_time"] is not None
    
    def test_rate_limit_check_exceeded(self, auth_service):
        """Test rate limiting when limit is exceeded"""
        ip_address = "192.168.1.1"
        
        # Exceed rate limit
        for _ in range(61):  # Limit is 60
            auth_service.check_rate_limit(ip_address, "login")
        
        result = auth_service.check_rate_limit(ip_address, "login")
        
        assert result["allowed"] == False
        assert result["remaining"] == 0

    # --- Token Blacklisting Tests ---
    
    def test_check_token_blacklist_not_blacklisted(self, auth_service):
        """Test checking non-blacklisted token"""
        token = "valid.jwt.token"
        
        result = auth_service.check_token_blacklist(token)
        
        assert result["blacklisted"] == False
        assert result["reason"] is None
    
    def test_add_token_to_blacklist_success(self, auth_service):
        """Test adding token to blacklist"""
        token = "token.to.blacklist"
        reason = "user_logout"
        
        result = auth_service.add_token_to_blacklist(token, reason)
        
        assert result == True
        
        # Verify token is blacklisted
        check_result = auth_service.check_token_blacklist(token)
        assert check_result["blacklisted"] == True
        assert check_result["reason"] == reason

    # --- User Context Tests ---
    
    def test_create_user_context_success(self, auth_service):
        """Test creating user context"""
        user_data = {
            "user_id": str(uuid4()),
            "display_name": "John Doe",
            "credits_remaining": 25,
            "bot_enabled": True
        }
        
        result = auth_service.create_user_context(user_data)
        
        assert result["user_id"] == user_data["user_id"]
        assert result["display_name"] == user_data["display_name"]
        assert result["credits_remaining"] == user_data["credits_remaining"]
        assert result["bot_enabled"] == user_data["bot_enabled"]
        assert result["is_authenticated"] == True
        assert "context_id" in result
        assert "created_at" in result
        assert "permissions" in result
        assert result["permissions"]["can_process_emails"] == True
        assert result["permissions"]["can_access_dashboard"] == True

    # --- Statistics Tests ---
    
    def test_get_auth_statistics_success(self, auth_service, mock_user_repo):
        """Test getting authentication statistics"""
        mock_user_repo.count_user_profiles.return_value = 100
        
        result = auth_service.get_auth_statistics()
        
        assert "total_users" in result
        assert "active_sessions" in result
        assert "login_attempts_today" in result
        assert "failed_logins_today" in result
        assert "success_rate" in result
        assert result["total_users"] == 100

    # --- Utility Tests ---
    
    def test_extract_user_data_from_jwt(self, auth_service, valid_jwt_payload):
        """Test extracting user data from JWT payload"""
        result = auth_service.extract_user_data_from_jwt(valid_jwt_payload)
        
        assert result["user_id"] == valid_jwt_payload["sub"]
        assert result["email"] == valid_jwt_payload["email"]
        assert result["display_name"] == valid_jwt_payload["user_metadata"]["name"]
        assert result["picture"] == valid_jwt_payload["user_metadata"]["picture"]
        assert result["provider"] == valid_jwt_payload["app_metadata"]["provider"]
        assert result["email_verified"] == valid_jwt_payload["email_verified"]
    
    def test_extract_user_data_from_jwt_missing_metadata(self, auth_service):
        """Test extracting user data when metadata is missing"""
        payload = {
            "sub": str(uuid4()),
            "email": "user@example.com",
            "email_verified": True
        }
        
        result = auth_service.extract_user_data_from_jwt(payload)
        
        assert result["user_id"] == payload["sub"]
        assert result["email"] == payload["email"]
        assert result["display_name"] is None
        assert result["picture"] is None
        assert result["provider"] == "email"  # Default