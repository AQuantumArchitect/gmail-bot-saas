import pytest
from uuid import uuid4
from unittest.mock import patch, AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

# Import the router and dependencies to be tested and overridden
from app.api.routes.auth import router as auth_router
from app.api.dependencies import get_user_context, get_optional_user_context, UserContext
from app.core.exceptions import AuthenticationError, NotFoundError

# Create a minimal FastAPI app instance and include the auth router
app = FastAPI()
app.include_router(auth_router)

# Instantiate the test client
client = TestClient(app)


@pytest.fixture
def sample_user_profile():
    """Provides a sample user profile dictionary."""
    return {
        "user_id": str(uuid4()),
        "email": "test@example.com",
        "display_name": "Test User",
        "credits_remaining": 100,
        "bot_enabled": True,
        "timezone": "UTC",
        "created_at": "2025-01-01T00:00:00"
    }


@pytest.fixture
def sample_user_context(sample_user_profile):
    """Provides a fully formed UserContext object for dependency overrides."""
    permissions = {
        "can_process_emails": True,
        "can_access_dashboard": True,
        "can_connect_gmail": True,
        "can_purchase_credits": True
    }
    context = UserContext(user_data=sample_user_profile, permissions=permissions)
    # The context object needs the raw data for the logout audit log
    context._raw_user_data = sample_user_profile
    return context


class TestAuthRoutes:
    """Tests for the authentication API endpoints."""

    def test_get_current_user_profile_success(self, sample_user_context, sample_user_profile):
        """
        Tests the GET /auth/me endpoint for a successful authenticated request.
        """
        # --- Arrange ---
        app.dependency_overrides[get_user_context] = lambda: sample_user_context
        with patch("app.api.routes.auth.user_service.get_user_profile", new_callable=AsyncMock) as mock_get_profile:
            mock_get_profile.return_value = sample_user_profile

            # --- Act ---
            response = client.get("/auth/me", headers={"Authorization": "Bearer fake-token"})

            # --- Assert ---
            assert response.status_code == 200
            data = response.json()
            assert data["user_id"] == sample_user_context.user_id
            mock_get_profile.assert_awaited_once_with(sample_user_context.user_id)
        
        app.dependency_overrides = {}

    def test_get_current_user_profile_not_found(self, sample_user_context):
        """
        Tests the GET /auth/me endpoint when the user profile is not found.
        """
        # --- Arrange ---
        app.dependency_overrides[get_user_context] = lambda: sample_user_context
        with patch("app.api.routes.auth.user_service.get_user_profile", new_callable=AsyncMock) as mock_get_profile:
            mock_get_profile.side_effect = NotFoundError("Profile does not exist")

            # --- Act ---
            response = client.get("/auth/me", headers={"Authorization": "Bearer fake-token"})
            
            # --- Assert ---
            assert response.status_code == 404
            assert "user profile not found" in response.json()["detail"].lower()

        app.dependency_overrides = {}

    def test_validate_token_success(self):
        """
        Tests the POST /auth/validate-token endpoint for a valid token.
        """
        # --- Arrange ---
        token_data = {
            "valid": True, "user_id": str(uuid4()), "email": "valid@example.com", "expires_at": "2025-12-31T23:59:59"
        }
        with patch("app.api.routes.auth.auth_service.validate_jwt_token") as mock_validate:
            mock_validate.return_value = token_data

            # --- Act ---
            response = client.post("/auth/validate-token", json={"token": "a-valid-token"})

            # --- Assert ---
            assert response.status_code == 200
            data = response.json()
            assert data["valid"] is True
            assert data["user_id"] == token_data["user_id"]

    def test_validate_token_failure(self):
        """
        Tests the POST /auth/validate-token endpoint for an invalid token.
        """
        # --- Arrange ---
        with patch("app.api.routes.auth.auth_service.validate_jwt_token") as mock_validate:
            mock_validate.side_effect = AuthenticationError("Token expired")

            # --- Act ---
            response = client.post("/auth/validate-token", json={"token": "an-invalid-token"})

            # --- Assert ---
            assert response.status_code == 200
            data = response.json()
            assert data["valid"] is False

    def test_create_session_success(self, sample_user_profile):
        """
        Tests the POST /auth/create-session endpoint for a successful session creation.
        """
        # --- Arrange ---
        with patch("app.api.routes.auth.auth_service") as mock_auth_service:
            mock_auth_service._decode_jwt_token.return_value = {"sub": sample_user_profile["user_id"]}
            mock_auth_service.get_or_create_user_profile.return_value = sample_user_profile
            mock_auth_service.create_user_session.return_value = {"session_id": "new-session-123"}

            # --- Act ---
            response = client.post("/auth/create-session", json={"access_token": "valid-supabase-token"})

            # --- Assert ---
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["user_id"] == sample_user_profile["user_id"]
            mock_auth_service.get_or_create_user_profile.assert_called_once()
            mock_auth_service.create_user_session.assert_called_once()
            mock_auth_service.audit_log_authentication.assert_called_once()
    
    def test_logout_success(self, sample_user_context):
        """
        Tests the POST /auth/logout endpoint for a successful user logout.
        """
        # --- Arrange ---
        app.dependency_overrides[get_user_context] = lambda: sample_user_context
        with patch("app.api.routes.auth.auth_service") as mock_auth_service:
            mock_auth_service.invalidate_all_user_sessions.return_value = {"invalidated_count": 2}

            # --- Act ---
            response = client.post("/auth/logout", headers={"Authorization": "Bearer fake-token"})
            
            # --- Assert ---
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["sessions_invalidated"] == 2
            mock_auth_service.invalidate_all_user_sessions.assert_called_once_with(sample_user_context.user_id)

        app.dependency_overrides = {}

    def test_auth_status_authenticated(self, sample_user_context):
        """
        Tests the GET /auth/status endpoint when a valid token is provided.
        """
        # --- Arrange ---
        app.dependency_overrides[get_optional_user_context] = lambda: sample_user_context

        # --- Act ---
        response = client.get("/auth/status", headers={"Authorization": "Bearer fake-token"})

        # --- Assert ---
        assert response.status_code == 200
        data = response.json()
        assert data["authenticated"] is True
        assert data["user_id"] == sample_user_context.user_id

        app.dependency_overrides = {}

    def test_auth_status_unauthenticated(self):
        """
        Tests the GET /auth/status endpoint when no token is provided.
        """
        # --- Arrange ---
        app.dependency_overrides[get_optional_user_context] = lambda: None

        # --- Act ---
        response = client.get("/auth/status")

        # --- Assert ---
        assert response.status_code == 200
        data = response.json()
        assert data["authenticated"] is False
        assert "no valid authentication token" in data["message"].lower()

        app.dependency_overrides = {}

    def test_get_user_sessions_success(self, sample_user_context):
        """
        Tests the GET /auth/sessions endpoint for listing active sessions.
        """
        # --- Arrange ---
        app.dependency_overrides[get_user_context] = lambda: sample_user_context
        mock_sessions = [
            {"session_id": "session1", "ip_address": "1.1.1.1", "user_agent": "Chrome", "created_at": "...", "expires_at": "..."},
            {"session_id": "session2", "ip_address": "2.2.2.2", "user_agent": "Firefox", "created_at": "...", "expires_at": "..."}
        ]
        with patch("app.api.routes.auth.auth_service.get_user_sessions") as mock_get_sessions:
            mock_get_sessions.return_value = mock_sessions

            # --- Act ---
            response = client.get("/auth/sessions", headers={"Authorization": "Bearer fake-token"})

            # --- Assert ---
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["total_sessions"] == 2
            assert len(data["sessions"]) == 2
            assert data["sessions"][0]["session_id"] == "session1"
            mock_get_sessions.assert_called_once_with(sample_user_context.user_id)

        app.dependency_overrides = {}

    def test_invalidate_session_success(self, sample_user_context):
        """
        Tests the DELETE /auth/sessions/{session_id} endpoint for a successful invalidation.
        """
        # --- Arrange ---
        session_to_delete = "session-to-delete-123"
        app.dependency_overrides[get_user_context] = lambda: sample_user_context
        with patch("app.api.routes.auth.auth_service") as mock_auth_service:
            # Mock the ownership check to succeed
            mock_auth_service.get_user_sessions.return_value = [{"session_id": session_to_delete}]
            # Mock the invalidation call to succeed
            mock_auth_service.invalidate_user_session.return_value = True

            # --- Act ---
            response = client.delete(f"/auth/sessions/{session_to_delete}", headers={"Authorization": "Bearer fake-token"})

            # --- Assert ---
            assert response.status_code == 200
            assert response.json()["success"] is True
            mock_auth_service.get_user_sessions.assert_called_once_with(sample_user_context.user_id)
            mock_auth_service.invalidate_user_session.assert_called_once_with(session_to_delete)

        app.dependency_overrides = {}
    
    def test_invalidate_session_not_owned(self, sample_user_context):
        """
        Tests that a user cannot delete a session they do not own.
        """
        # --- Arrange ---
        app.dependency_overrides[get_user_context] = lambda: sample_user_context
        with patch("app.api.routes.auth.auth_service.get_user_sessions") as mock_get_sessions:
            # Mock sessions to not include the one being deleted
            mock_get_sessions.return_value = [{"session_id": "some-other-session"}]

            # --- Act ---
            response = client.delete("/auth/sessions/session-i-dont-own", headers={"Authorization": "Bearer fake-token"})

            # --- Assert ---
            assert response.status_code == 404
            assert "session not found" in response.json()["detail"].lower()

        app.dependency_overrides = {}

    def test_get_user_audit_log_success(self, sample_user_context):
        """
        Tests the GET /auth/audit-log endpoint.
        """
        # --- Arrange ---
        app.dependency_overrides[get_user_context] = lambda: sample_user_context
        mock_logs = [{"event_type": "login_success", "timestamp": "..."}]
        with patch("app.api.routes.auth.auth_service.get_user_audit_logs") as mock_get_logs:
            mock_get_logs.return_value = mock_logs

            # --- Act ---
            response = client.get("/auth/audit-log?limit=5", headers={"Authorization": "Bearer fake-token"})

            # --- Assert ---
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert len(data["audit_logs"]) == 1
            mock_get_logs.assert_called_once_with(sample_user_context.user_id, limit=5)

        app.dependency_overrides = {}