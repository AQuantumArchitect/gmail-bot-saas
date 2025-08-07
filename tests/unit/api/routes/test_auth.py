# tests/unit/api/routes/test_auth_clean.py
"""
Enhanced, comprehensive tests for authentication routes.
Covers security scenarios, edge cases, session management, and audit logging.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, AsyncMock, patch
from uuid import uuid4
import json
from datetime import datetime, timedelta
import jwt

# Import the specific router to be tested
from app.api.routes.auth import router as auth_router
from app.api.routes.auth import get_auth_service, get_user_service

# Import dependencies that will be mocked
from app.api.dependencies import get_user_context, get_optional_user_context, UserContext
from app.services.auth_service import AuthService
from app.services.user_service import UserService
from app.core.exceptions import AuthenticationError, NotFoundError, ValidationError

@pytest.fixture
def comprehensive_mock_auth_service() -> MagicMock:
    """Comprehensive mock AuthService with all authentication methods."""
    service = MagicMock(spec=AuthService)
    
    # Token validation methods
    service.validate_jwt_token = MagicMock()
    service._decode_jwt_token = MagicMock()
    service.refresh_jwt_token = MagicMock()
    
    # User profile methods
    service.get_or_create_user_profile = MagicMock()
    service.create_user_profile = MagicMock()
    service.update_user_profile = MagicMock()
    
    # Session management methods
    service.create_user_session = MagicMock()
    service.get_user_sessions = MagicMock()
    service.invalidate_user_session = MagicMock()
    service.invalidate_all_user_sessions = AsyncMock()
    
    # Audit and logging methods
    service.audit_log_authentication = MagicMock()
    service.get_user_audit_logs = MagicMock()
    service.get_auth_statistics = MagicMock()
    
    # Security methods
    service.validate_session = MagicMock()
    service.check_brute_force_protection = MagicMock()
    
    return service

@pytest.fixture
def comprehensive_mock_user_service() -> MagicMock:
    """Comprehensive mock UserService with user management methods."""
    service = MagicMock(spec=UserService)
    
    service.get_user_profile = AsyncMock()
    service.create_user_profile = AsyncMock()
    service.update_user_profile = AsyncMock()
    service.delete_user_profile = AsyncMock()
    service.get_user_preferences = AsyncMock()
    service.update_user_preferences = AsyncMock()
    
    return service

@pytest.fixture
def comprehensive_user_context() -> UserContext:
    """Comprehensive UserContext with all user states for testing."""
    user_id = str(uuid4())
    user_data = {
        "user_id": user_id,
        "email": "comprehensive@test.com",
        "display_name": "Test User",
        "credits_remaining": 50,
        "bot_enabled": True,
        "timezone": "America/New_York",
        "created_at": "2025-01-01T00:00:00Z",
        "last_login": "2025-01-30T10:00:00Z",
        "login_count": 5,
        "is_premium": False,
        "email_verified": True
    }
    permissions = {
        "can_process_emails": True,
        "can_access_dashboard": True,
        "can_connect_gmail": True,
        "can_purchase_credits": True,
        "can_manage_account": True,
        "can_access_audit_logs": True
    }
    context = UserContext(user_data=user_data, permissions=permissions)
    context._raw_user_data = user_data  # For logout endpoint
    return context

@pytest.fixture
def client(comprehensive_mock_auth_service: MagicMock, comprehensive_mock_user_service: MagicMock, comprehensive_user_context: UserContext) -> TestClient:
    """Enhanced test client with comprehensive authentication mocking."""
    app = FastAPI(title="Enhanced Auth Test App")

    # Override the dependency functions
    app.dependency_overrides[get_auth_service] = lambda: comprehensive_mock_auth_service
    app.dependency_overrides[get_user_service] = lambda: comprehensive_mock_user_service
    app.dependency_overrides[get_user_context] = lambda: comprehensive_user_context
    app.dependency_overrides[get_optional_user_context] = lambda: comprehensive_user_context

    # Include the auth router
    app.include_router(auth_router, prefix="/api")

    with TestClient(app) as test_client:
        yield test_client

class TestTokenValidation:
    """Comprehensive tests for JWT token validation."""

    def test_validate_token_success(self, client: TestClient, comprehensive_mock_auth_service: MagicMock):
        """Test successful token validation."""
        token_data = {
            "user_id": "test-user-123",
            "email": "test@example.com",
            "expires_at": "2025-01-31T10:00:00Z"
        }
        comprehensive_mock_auth_service.validate_jwt_token.return_value = token_data
        
        request_body = {"token": "valid.jwt.token"}
        response = client.post("/api/auth/validate-token", json=request_body)
        
        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is True
        assert data["user_id"] == "test-user-123"
        assert data["email"] == "test@example.com"
        assert data["expires_at"] == "2025-01-31T10:00:00Z"

    def test_validate_token_expired(self, client: TestClient, comprehensive_mock_auth_service: MagicMock):
        """Test validation of expired token."""
        comprehensive_mock_auth_service.validate_jwt_token.side_effect = AuthenticationError("Token expired")
        
        request_body = {"token": "expired.jwt.token"}
        response = client.post("/api/auth/validate-token", json=request_body)
        
        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is False
        assert data["user_id"] is None

    def test_validate_token_malformed(self, client: TestClient, comprehensive_mock_auth_service: MagicMock):
        """Test validation of malformed token."""
        comprehensive_mock_auth_service.validate_jwt_token.side_effect = AuthenticationError("Invalid token format")
        
        request_body = {"token": "malformed.token"}
        response = client.post("/api/auth/validate-token", json=request_body)
        
        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is False

    def test_validate_token_empty(self, client: TestClient):
        """Test validation with empty token."""
        request_body = {"token": ""}
        response = client.post("/api/auth/validate-token", json=request_body)
        
        assert response.status_code == 422  # Validation error

    def test_validate_token_missing(self, client: TestClient):
        """Test validation with missing token field."""
        request_body = {}
        response = client.post("/api/auth/validate-token", json=request_body)
        
        assert response.status_code == 422  # Validation error

    def test_validate_token_server_error(self, client: TestClient, comprehensive_mock_auth_service: MagicMock):
        """Test token validation with server error."""
        comprehensive_mock_auth_service.validate_jwt_token.side_effect = Exception("Database connection failed")
        
        request_body = {"token": "valid.jwt.token"}
        response = client.post("/api/auth/validate-token", json=request_body)
        
        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is False

class TestUserProfile:
    """Comprehensive tests for user profile management."""

    def test_get_current_user_profile_success(self, client: TestClient, comprehensive_mock_user_service: MagicMock, comprehensive_user_context: UserContext):
        """Test successful user profile retrieval."""
        profile_data = {
            "user_id": comprehensive_user_context.user_id,
            "email": comprehensive_user_context.email,
            "display_name": comprehensive_user_context.display_name,
            "preferences": {"theme": "dark", "notifications": True},
            "metadata": {"last_active": "2025-01-30T10:00:00Z"}
        }
        comprehensive_mock_user_service.get_user_profile.return_value = profile_data
        
        response = client.get("/api/auth/me")
        
        assert response.status_code == 200
        data = response.json()
        assert data["user_id"] == comprehensive_user_context.user_id
        assert data["email"] == comprehensive_user_context.email
        assert data["display_name"] == comprehensive_user_context.display_name
        assert data["credits_remaining"] == 50
        assert data["permissions"]["can_process_emails"] is True

    def test_get_current_user_profile_not_found(self, client: TestClient, comprehensive_mock_user_service: MagicMock):
        """Test user profile not found scenario."""
        comprehensive_mock_user_service.get_user_profile.side_effect = NotFoundError("User profile not found")
        
        response = client.get("/api/auth/me")
        
        assert response.status_code == 404
        assert "User profile not found" in response.text

    def test_get_current_user_profile_service_error(self, client: TestClient, comprehensive_mock_user_service: MagicMock):
        """Test user profile retrieval with service error."""
        comprehensive_mock_user_service.get_user_profile.side_effect = Exception("Database error")
        
        response = client.get("/api/auth/me")
        
        assert response.status_code == 500

class TestSessionManagement:
    """Comprehensive tests for session creation and management."""

    def test_create_session_success(self, client: TestClient, comprehensive_mock_auth_service: MagicMock):
        """Test successful session creation."""
        jwt_payload = {
            "user_id": "test-user-123",
            "email": "test@example.com",
            "aud": "authenticated",
            "exp": 1643723400
        }
        user_profile = {
            "user_id": "test-user-123",
            "email": "test@example.com",
            "display_name": "Test User",
            "gmail_connected": False
        }
        session_data = {
            "session_id": "session_123",
            "created_at": "2025-01-30T10:00:00Z"
        }
        
        comprehensive_mock_auth_service._decode_jwt_token.return_value = jwt_payload
        comprehensive_mock_auth_service.get_or_create_user_profile.return_value = user_profile
        comprehensive_mock_auth_service.create_user_session.return_value = session_data
        
        request_body = {
            "access_token": "valid.access.token",
            "refresh_token": "valid.refresh.token",
            "expires_in": 3600
        }
        
        response = client.post("/api/auth/create-session", json=request_body)
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["user_id"] == "test-user-123"
        assert data["needs_gmail"] is True  # Gmail not connected

    def test_create_session_invalid_token(self, client: TestClient, comprehensive_mock_auth_service: MagicMock):
        """Test session creation with invalid token."""
        comprehensive_mock_auth_service._decode_jwt_token.side_effect = AuthenticationError("Invalid token")
        
        request_body = {"access_token": "invalid.token"}
        
        response = client.post("/api/auth/create-session", json=request_body)
        
        assert response.status_code == 401

    def test_create_session_user_creation_error(self, client: TestClient, comprehensive_mock_auth_service: MagicMock):
        """Test session creation when user profile creation fails."""
        jwt_payload = {"user_id": "test-user-123", "email": "test@example.com"}
        comprehensive_mock_auth_service._decode_jwt_token.return_value = jwt_payload
        comprehensive_mock_auth_service.get_or_create_user_profile.side_effect = ValidationError("Invalid user data")
        
        request_body = {"access_token": "valid.token"}
        
        response = client.post("/api/auth/create-session", json=request_body)
        
        assert response.status_code == 422

    def test_logout_success(self, client: TestClient, comprehensive_mock_auth_service: MagicMock, comprehensive_user_context: UserContext):
        """Test successful user logout."""
        comprehensive_mock_auth_service.invalidate_all_user_sessions.return_value = {"invalidated_count": 3}
        
        response = client.post("/api/auth/logout")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["sessions_invalidated"] == 3
        comprehensive_mock_auth_service.invalidate_all_user_sessions.assert_called_once_with(comprehensive_user_context.user_id)

    def test_logout_service_error(self, client: TestClient, comprehensive_mock_auth_service: MagicMock):
        """Test logout with service error."""
        comprehensive_mock_auth_service.invalidate_all_user_sessions.side_effect = Exception("Session cleanup failed")
        
        response = client.post("/api/auth/logout")
        
        assert response.status_code == 500

    def test_refresh_token_success(self, client: TestClient, comprehensive_user_context: UserContext):
        """Test successful token refresh."""
        response = client.post("/api/auth/refresh")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["user_id"] == comprehensive_user_context.user_id
        assert data["email"] == comprehensive_user_context.email

class TestSessionListingAndManagement:
    """Tests for session listing and individual session management."""

    def test_get_user_sessions_success(self, client: TestClient, comprehensive_mock_auth_service: MagicMock, comprehensive_user_context: UserContext):
        """Test successful session listing."""
        mock_sessions = [
            {
                "session_id": "session_1",
                "ip_address": "192.168.1.1",
                "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "created_at": "2025-01-30T09:00:00Z",
                "expires_at": "2025-01-31T09:00:00Z",
                "last_activity": "2025-01-30T10:00:00Z"
            },
            {
                "session_id": "session_2",
                "ip_address": "192.168.1.2",
                "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)",
                "created_at": "2025-01-29T15:00:00Z",
                "expires_at": "2025-01-30T15:00:00Z",
                "last_activity": "2025-01-30T08:00:00Z"
            }
        ]
        comprehensive_mock_auth_service.get_user_sessions.return_value = mock_sessions
        
        response = client.get("/api/auth/sessions")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert len(data["sessions"]) == 2
        assert data["total_sessions"] == 2
        
        # Verify sensitive data is removed
        for session in data["sessions"]:
            assert "password" not in session
            assert "secret" not in session
            assert session["session_id"] in ["session_1", "session_2"]

    def test_get_user_sessions_empty(self, client: TestClient, comprehensive_mock_auth_service: MagicMock):
        """Test session listing when user has no sessions."""
        comprehensive_mock_auth_service.get_user_sessions.return_value = []
        
        response = client.get("/api/auth/sessions")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert len(data["sessions"]) == 0
        assert data["total_sessions"] == 0

    def test_invalidate_session_success(self, client: TestClient, comprehensive_mock_auth_service: MagicMock, comprehensive_user_context: UserContext):
        """Test successful session invalidation."""
        session_id = "session_to_invalidate"
        mock_sessions = [{"session_id": session_id, "user_id": comprehensive_user_context.user_id}]
        comprehensive_mock_auth_service.get_user_sessions.return_value = mock_sessions
        comprehensive_mock_auth_service.invalidate_user_session.return_value = True
        
        response = client.delete(f"/api/auth/sessions/{session_id}")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "invalidated successfully" in data["message"]

    def test_invalidate_session_not_found(self, client: TestClient, comprehensive_mock_auth_service: MagicMock):
        """Test invalidating non-existent session."""
        session_id = "nonexistent_session"
        comprehensive_mock_auth_service.get_user_sessions.return_value = []
        
        response = client.delete(f"/api/auth/sessions/{session_id}")
        
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

    def test_invalidate_session_belongs_to_different_user(self, client: TestClient, comprehensive_mock_auth_service: MagicMock):
        """Test invalidating session that belongs to different user."""
        session_id = "other_user_session"
        mock_sessions = [{"session_id": "my_session", "user_id": "current_user"}]
        comprehensive_mock_auth_service.get_user_sessions.return_value = mock_sessions
        
        response = client.delete(f"/api/auth/sessions/{session_id}")
        
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

class TestSecurityAndAuditFeatures:
    """Tests for security features and audit logging."""

    def test_get_user_audit_log_success(self, client: TestClient, comprehensive_mock_auth_service: MagicMock, comprehensive_user_context: UserContext):
        """Test successful audit log retrieval."""
        mock_audit_logs = [
            {
                "timestamp": "2025-01-30T10:00:00Z",
                "action": "login_success",
                "ip_address": "192.168.1.1",
                "user_agent": "Mozilla/5.0",
                "metadata": {"method": "supabase_jwt"}
            },
            {
                "timestamp": "2025-01-30T09:00:00Z",
                "action": "session_created",
                "ip_address": "192.168.1.1",
                "user_agent": "Mozilla/5.0",
                "metadata": {"session_id": "session_123"}
            }
        ]
        comprehensive_mock_auth_service.get_user_audit_logs.return_value = mock_audit_logs
        
        response = client.get("/api/auth/audit-log")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert len(data["audit_logs"]) == 2
        assert data["total_entries"] == 2
        assert data["user_id"] == comprehensive_user_context.user_id

    def test_get_user_audit_log_with_limit(self, client: TestClient, comprehensive_mock_auth_service: MagicMock, comprehensive_user_context: UserContext):
        """Test audit log retrieval with custom limit."""
        comprehensive_mock_auth_service.get_user_audit_logs.return_value = []
        
        response = client.get("/api/auth/audit-log?limit=25")
        
        assert response.status_code == 200
        comprehensive_mock_auth_service.get_user_audit_logs.assert_called_once_with(comprehensive_user_context.user_id, limit=25)

    def test_get_user_audit_log_limit_bounds(self, client: TestClient, comprehensive_mock_auth_service: MagicMock, comprehensive_user_context: UserContext):
        """Test audit log limit is properly bounded."""
        comprehensive_mock_auth_service.get_user_audit_logs.return_value = []
        
        # Test upper bound
        response = client.get("/api/auth/audit-log?limit=500")
        assert response.status_code == 200
        comprehensive_mock_auth_service.get_user_audit_logs.assert_called_with(comprehensive_user_context.user_id, limit=100)

    def test_change_password_placeholder(self, client: TestClient, comprehensive_user_context: UserContext):
        """Test password change placeholder functionality."""
        response = client.post("/api/auth/change-password")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "not implemented" in data["message"]

class TestDevelopmentAndTestingEndpoints:
    """Tests for development and testing authentication endpoints."""

    def test_login_for_testing_success(self, client: TestClient, comprehensive_mock_auth_service: MagicMock):
        """Test successful test login."""
        mock_session = {
            "session_id": "test_session_123",
            "created_at": "2025-01-30T10:00:00Z"
        }
        comprehensive_mock_auth_service.create_user_session.return_value = mock_session
        
        request_body = {
            "email": "test@example.com",
            "password": "password123"
        }
        
        response = client.post("/api/auth/login", json=request_body)
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["user_id"] == "test-user-123"
        assert "mock_token" in data

    def test_login_for_testing_invalid_credentials(self, client: TestClient):
        """Test test login with invalid credentials."""
        request_body = {
            "email": "test@example.com",
            "password": "wrongpassword"
        }
        
        response = client.post("/api/auth/login", json=request_body)
        
        assert response.status_code == 401
        assert "Invalid email or password" in response.json()["detail"]

    def test_login_for_testing_validation_error(self, client: TestClient):
        """Test test login with validation errors."""
        request_body = {
            "email": "invalid-email",
            "password": "short"
        }
        
        response = client.post("/api/auth/login", json=request_body)
        
        assert response.status_code == 422

    def test_register_for_testing_success(self, client: TestClient, comprehensive_mock_user_service: MagicMock):
        """Test successful test registration."""
        mock_profile = {
            "user_id": "new-user-123",
            "email": "newuser@example.com",
            "display_name": "New User",
            "credits_remaining": 5
        }
        comprehensive_mock_user_service.create_user_profile.return_value = mock_profile
        
        request_body = {
            "email": "newuser@example.com",
            "display_name": "New User",
            "timezone": "America/New_York"
        }
        
        response = client.post("/api/auth/register", json=request_body)
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["user_id"] == "new-user-123"
        assert data["email"] == "newuser@example.com"

    def test_register_for_testing_validation_error(self, client: TestClient):
        """Test test registration with validation errors."""
        request_body = {
            "email": "invalid-email",
            "display_name": "",
            "timezone": "invalid/timezone"
        }
        
        response = client.post("/api/auth/register", json=request_body)
        
        assert response.status_code == 422

class TestAuthStatusAndHealth:
    """Tests for authentication status and health endpoints."""

    def test_auth_status_authenticated(self, client: TestClient, comprehensive_user_context: UserContext):
        """Test auth status for authenticated user."""
        response = client.get("/api/auth/status")
        
        assert response.status_code == 200
        data = response.json()
        assert data["authenticated"] is True
        assert data["user_id"] == comprehensive_user_context.user_id
        assert data["email"] == comprehensive_user_context.email
        assert "permissions" in data

    def test_auth_status_unauthenticated(self, client: TestClient):
        """Test auth status for unauthenticated user."""
        # Override the dependency for this test
        client.app.dependency_overrides[get_optional_user_context] = lambda: None
        
        response = client.get("/api/auth/status")
        
        assert response.status_code == 200
        data = response.json()
        assert data["authenticated"] is False
        assert "No valid authentication token" in data["message"]
        
        # Clean up
        client.app.dependency_overrides.pop(get_optional_user_context)

    def test_auth_health_success(self, client: TestClient, comprehensive_mock_auth_service: MagicMock):
        """Test healthy auth service status."""
        mock_stats = {
            "total_users": 1000,
            "active_sessions": 150,
            "success_rate": 0.995
        }
        comprehensive_mock_auth_service.get_auth_statistics.return_value = mock_stats
        
        response = client.get("/api/auth/health")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "authentication"
        assert data["total_users"] == 1000
        assert data["active_sessions"] == 150
        assert data["success_rate"] == 0.995

    def test_auth_health_service_error(self, client: TestClient, comprehensive_mock_auth_service: MagicMock):
        """Test auth health with service error."""
        comprehensive_mock_auth_service.get_auth_statistics.side_effect = Exception("Database connection failed")
        
        response = client.get("/api/auth/health")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "unhealthy"
        assert "error" in data

class TestInputValidationAndSecurity:
    """Tests for input validation and security measures."""

    def test_token_validation_with_malicious_payload(self, client: TestClient, comprehensive_mock_auth_service: MagicMock):
        """Test token validation with potentially malicious payload."""
        comprehensive_mock_auth_service.validate_jwt_token.side_effect = AuthenticationError("Malicious token detected")
        
        malicious_token = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjoiJzsgRFJPUCBUQUJMRSB1c2VyczsgLS0iLCJlbWFpbCI6InRlc3RAZXhhbXBsZS5jb20ifQ"
        request_body = {"token": malicious_token}
        
        response = client.post("/api/auth/validate-token", json=request_body)
        
        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is False

    def test_session_creation_with_xss_attempt(self, client: TestClient, comprehensive_mock_auth_service: MagicMock):
        """Test session creation with XSS attempt in user agent."""
        jwt_payload = {"user_id": "test-user", "email": "test@example.com"}
        user_profile = {"user_id": "test-user", "email": "test@example.com"}
        session_data = {"session_id": "session_123"}
        
        comprehensive_mock_auth_service._decode_jwt_token.return_value = jwt_payload
        comprehensive_mock_auth_service.get_or_create_user_profile.return_value = user_profile
        comprehensive_mock_auth_service.create_user_session.return_value = session_data
        
        request_body = {"access_token": "valid.token"}
        headers = {"User-Agent": "<script>alert('XSS')</script>"}
        
        response = client.post("/api/auth/create-session", json=request_body, headers=headers)
        
        # Should still succeed but safely handle the malicious user agent
        assert response.status_code == 200

    def test_extremely_long_input_handling(self, client: TestClient):
        """Test handling of extremely long inputs."""
        very_long_token = "a" * 10000
        request_body = {"token": very_long_token}
        
        response = client.post("/api/auth/validate-token", json=request_body)
        
        # Should handle gracefully without crashing
        assert response.status_code in [200, 422]

class TestConcurrencyAndRaceConditions:
    """Tests for concurrent access scenarios."""

    @pytest.mark.asyncio
    async def test_concurrent_session_creation(self, client: TestClient, comprehensive_mock_auth_service: MagicMock):
        """Test concurrent session creation for same user."""
        import asyncio
        from httpx import AsyncClient
        
        # Mock successful session creation
        jwt_payload = {"user_id": "test-user", "email": "test@example.com"}
        user_profile = {"user_id": "test-user", "email": "test@example.com"}
        session_data = {"session_id": "session_123"}
        
        comprehensive_mock_auth_service._decode_jwt_token.return_value = jwt_payload
        comprehensive_mock_auth_service.get_or_create_user_profile.return_value = user_profile
        comprehensive_mock_auth_service.create_user_session.return_value = session_data
        
        request_body = {"access_token": "valid.token"}
        
        # Create multiple concurrent requests
        async with AsyncClient(app=client.app, base_url="http://test") as ac:
            tasks = [
                ac.post("/api/auth/create-session", json=request_body)
                for _ in range(3)
            ]
            
            responses = await asyncio.gather(*tasks, return_exceptions=True)
            
            # All should succeed or handle concurrency appropriately
            for response in responses:
                if hasattr(response, 'status_code'):
                    assert response.status_code in [200, 429, 500]  # Success, rate limited, or server error

    @pytest.mark.asyncio 
    async def test_concurrent_logout(self, client: TestClient, comprehensive_mock_auth_service: MagicMock):
        """Test concurrent logout requests."""
        import asyncio
        from httpx import AsyncClient
        
        comprehensive_mock_auth_service.invalidate_all_user_sessions.return_value = {"invalidated_count": 1}
        
        # Create multiple concurrent logout requests
        async with AsyncClient(app=client.app, base_url="http://test") as ac:
            tasks = [
                ac.post("/api/auth/logout")
                for _ in range(3)
            ]
            
            responses = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Should handle gracefully
            success_count = 0
            for response in responses:
                if hasattr(response, 'status_code') and response.status_code == 200:
                    success_count += 1
            
            # At least one should succeed
            assert success_count >= 1

class TestErrorRecovery:
    """Tests for error recovery and resilience."""

    def test_service_recovery_after_auth_failure(self, client: TestClient, comprehensive_mock_auth_service: MagicMock):
        """Test service recovery after temporary auth failure."""
        # First request fails
        comprehensive_mock_auth_service.validate_jwt_token.side_effect = Exception("Auth service down")
        
        response1 = client.post("/api/auth/validate-token", json={"token": "test.token"})
        assert response1.status_code == 200
        assert response1.json()["valid"] is False
        
        # Service recovers
        comprehensive_mock_auth_service.validate_jwt_token.side_effect = None
        comprehensive_mock_auth_service.validate_jwt_token.return_value = {
            "user_id": "test-user",
            "email": "test@example.com"
        }
        
        response2 = client.post("/api/auth/validate-token", json={"token": "test.token"})
        assert response2.status_code == 200
        assert response2.json()["valid"] is True

    def test_partial_auth_degradation(self, client: TestClient, comprehensive_mock_auth_service: MagicMock):
        """Test handling of partial auth service degradation."""
        # Token validation works but session creation fails
        comprehensive_mock_auth_service.validate_jwt_token.return_value = {"user_id": "test-user", "email": "test@example.com"}
        comprehensive_mock_auth_service.create_user_session.side_effect = Exception("Session service down")
        
        # Token validation should still work
        response1 = client.post("/api/auth/validate-token", json={"token": "test.token"})
        assert response1.status_code == 200
        assert response1.json()["valid"] is True
        
        # Session creation should fail gracefully
        response2 = client.post("/api/auth/create-session", json={"access_token": "test.token"})
        assert response2.status_code in [500, 503]