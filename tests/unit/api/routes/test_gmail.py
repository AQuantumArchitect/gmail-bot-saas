import pytest
from uuid import uuid4
from unittest.mock import patch, AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

# Import the router and dependencies to be tested and overridden
from app.api.routes.gmail import router as gmail_router
from app.api.dependencies import (
    get_user_context,
    require_email_processing_permission,
    require_gmail_connection_permission,
    UserContext
)
from app.core.exceptions import APIError, ValidationError

# Create a minimal FastAPI app instance and include the gmail router
app = FastAPI()
app.include_router(gmail_router)

# Instantiate the test client
client = TestClient(app)


@pytest.fixture
def sample_user_context():
    """Provides a fully formed UserContext object for dependency overrides."""
    user_data = {
        "user_id": str(uuid4()),
        "email": "test@example.com",
    }
    permissions = {"can_process_emails": True, "can_connect_gmail": True}
    return UserContext(user_data=user_data, permissions=permissions)


class TestGmailRoutes:
    """Tests for the Gmail API endpoints."""

    def test_get_gmail_connection_status_success(self, sample_user_context):
        """
        Tests the GET /gmail/connection endpoint for a user with an active connection.
        """
        app.dependency_overrides[get_user_context] = lambda: sample_user_context
        with patch("app.api.routes.gmail.gmail_oauth_service") as mock_oauth_service:
            mock_oauth_service.check_connection_status.return_value = {
                "connected": True, "email": "test@example.com", "status": "connected", "error": None
            }
            mock_oauth_service.get_connection_info.return_value = {
                "scopes": ["scope1", "scope2"], "last_sync": "2025-01-01T12:00:00Z"
            }
            response = client.get("/gmail/connection", headers={"Authorization": "Bearer fake-token"})
            assert response.status_code == 200
            data = response.json()
            assert data["connected"] is True
            assert data["email_address"] == "test@example.com"
        app.dependency_overrides = {}

    def test_initiate_gmail_connection_success(self, sample_user_context):
        """
        Tests the POST /gmail/connect endpoint for initiating the OAuth flow.
        """
        app.dependency_overrides[require_gmail_connection_permission] = lambda: sample_user_context
        with patch("app.api.routes.gmail.gmail_oauth_service") as mock_oauth_service:
            mock_oauth_service.generate_oauth_url.return_value = {
                "oauth_url": "https://accounts.google.com/o/oauth2/v2/auth?...",
                "state": "gmail_oauth_state_123"
            }
            response = client.post("/gmail/connect", headers={"Authorization": "Bearer fake-token"})
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert "https://accounts.google.com" in data["oauth_url"]
            mock_oauth_service.generate_oauth_url.assert_called_once()
        app.dependency_overrides = {}

    def test_disconnect_gmail_success(self, sample_user_context):
        """
        Tests the POST /gmail/disconnect endpoint for revoking a Gmail connection.
        """
        app.dependency_overrides[get_user_context] = lambda: sample_user_context
        with patch("app.api.routes.gmail.gmail_oauth_service.revoke_connection", new_callable=AsyncMock) as mock_revoke:
            mock_revoke.return_value = {"success": True, "revoked_at": "2025-07-18T12:00:00Z"}
            response = client.post("/gmail/disconnect", headers={"Authorization": "Bearer fake-token"})
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            mock_revoke.assert_awaited_once_with(sample_user_context.user_id)
        app.dependency_overrides = {}

    def test_discover_emails_success(self, sample_user_context):
        """
        Tests the POST /gmail/discover endpoint for a successful discovery run.
        """
        app.dependency_overrides[require_email_processing_permission] = lambda: sample_user_context
        with patch("app.api.routes.gmail.email_service.discover_user_emails", new_callable=AsyncMock) as mock_discover:
            mock_discover.return_value = {
                "success": True, "emails_discovered": 10, "new_emails": 5, "filtered_emails": 2, "discovery_time": "..."
            }
            response = client.post("/gmail/discover", headers={"Authorization": "Bearer fake-token"})
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["new_emails"] == 5
            mock_discover.assert_awaited_once_with(sample_user_context.user_id, apply_filters=True)
        app.dependency_overrides = {}

    def test_process_email_success(self, sample_user_context):
        """
        Tests the POST /gmail/process endpoint for a successful email processing request.
        """
        app.dependency_overrides[require_email_processing_permission] = lambda: sample_user_context
        with patch("app.api.routes.gmail.email_service.process_single_email", new_callable=AsyncMock) as mock_process:
            mock_process.return_value = {
                "success": True, "message_id": "msg-123", "processing_time": 1.23, "credits_used": 1, "summary_sent": True
            }
            response = client.post(
                "/gmail/process", headers={"Authorization": "Bearer fake-token"}, json={"message_id": "msg-123"}
            )
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            mock_process.assert_awaited_once_with(sample_user_context.user_id, "msg-123")
        app.dependency_overrides = {}
    
    def test_process_email_api_error(self, sample_user_context):
        """
        Tests that the /gmail/process endpoint handles APIErrors and returns a 503 status code.
        """
        app.dependency_overrides[require_email_processing_permission] = lambda: sample_user_context
        with patch("app.api.routes.gmail.email_service.process_single_email", new_callable=AsyncMock) as mock_process:
            mock_process.side_effect = APIError("External service is down")
            response = client.post(
                "/gmail/process", headers={"Authorization": "Bearer fake-token"}, json={"message_id": "msg-123"}
            )
            assert response.status_code == 503
            assert "external service is down" in response.json()["detail"].lower()
        app.dependency_overrides = {}

    def test_process_email_validation_error(self, sample_user_context):
        """
        Tests that the /gmail/process endpoint handles ValidationErrors and returns a 422 status code.
        """
        app.dependency_overrides[require_email_processing_permission] = lambda: sample_user_context
        with patch("app.api.routes.gmail.email_service.process_single_email", new_callable=AsyncMock) as mock_process:
            mock_process.side_effect = ValidationError("Invalid message ID format")
            response = client.post(
                "/gmail/process", headers={"Authorization": "Bearer fake-token"}, json={"message_id": "invalid-id"}
            )
            assert response.status_code == 422
            assert "invalid message id format" in response.json()["detail"].lower()
        app.dependency_overrides = {}
    
    def test_process_all_emails_full_pipeline_success(self, sample_user_context):
        """
        Tests the POST /gmail/process-all endpoint for a successful pipeline run.
        """
        app.dependency_overrides[require_email_processing_permission] = lambda: sample_user_context
        with patch("app.api.routes.gmail.email_service.run_full_processing_pipeline", new_callable=AsyncMock) as mock_pipeline:
            mock_pipeline.return_value = {
                "success": True, "user_id": sample_user_context.user_id, "pipeline_completed": True,
                "emails_discovered": 5, "emails_processed": 5, "credits_used": 5
            }
            response = client.post("/gmail/process-all", headers={"Authorization": "Bearer fake-token"})
            assert response.status_code == 200
            data = response.json()
            assert data["pipeline_completed"] is True
            mock_pipeline.assert_awaited_once_with(sample_user_context.user_id)
        app.dependency_overrides = {}

    def test_get_processing_history_success(self, sample_user_context):
        """
        Tests the GET /gmail/history endpoint.
        """
        app.dependency_overrides[get_user_context] = lambda: sample_user_context
        with patch("app.api.routes.gmail.email_service.get_user_processing_history") as mock_get_history:
            mock_get_history.return_value = {"processing_history": [{"id": "1"}, {"id": "2"}]}
            response = client.get("/gmail/history?limit=2", headers={"Authorization": "Bearer fake-token"})
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert len(data["processing_history"]) == 2
            mock_get_history.assert_called_once_with(sample_user_context.user_id, limit=2)
        app.dependency_overrides = {}

    def test_get_gmail_statistics_success(self, sample_user_context):
        """
        Tests the GET /gmail/stats endpoint for aggregating data.
        """
        app.dependency_overrides[get_user_context] = lambda: sample_user_context
        # Patch both services called by the endpoint
        with patch("app.api.routes.gmail.gmail_service.get_user_gmail_statistics") as mock_gmail_stats, \
             patch("app.api.routes.gmail.email_service.get_user_email_statistics") as mock_email_stats:
            
            mock_gmail_stats.return_value = {"connection_status": "connected", "success_rate": 0.99}
            mock_email_stats.return_value = {"total_processed": 100, "total_credits_used": 98}

            response = client.get("/gmail/stats", headers={"Authorization": "Bearer fake-token"})
            assert response.status_code == 200
            data = response.json()
            assert data["user_id"] == sample_user_context.user_id
            assert data["gmail_connection"]["status"] == "connected"
            assert data["email_processing"]["total_processed"] == 100

        app.dependency_overrides = {}

    def test_process_batch_emails_success(self, sample_user_context):
        """
        Tests the POST /gmail/process-batch endpoint.
        """
        app.dependency_overrides[require_email_processing_permission] = lambda: sample_user_context
        with patch("app.api.routes.gmail.email_service.process_user_emails", new_callable=AsyncMock) as mock_process_batch:
            mock_process_batch.return_value = {
                "success": True, "user_id": sample_user_context.user_id, "emails_processed": 5
            }
            response = client.post("/gmail/process-batch?max_emails=5", headers={"Authorization": "Bearer fake-token"})
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["emails_processed"] == 5
            mock_process_batch.assert_awaited_once_with(sample_user_context.user_id, max_emails=5)

        app.dependency_overrides = {}