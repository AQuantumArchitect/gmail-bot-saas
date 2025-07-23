# tests/unit/api/routes/test_dashboard.py
"""
Unit tests for the dashboard API routes.
"""
import pytest
from uuid import uuid4
from unittest.mock import patch, AsyncMock, Mock

from fastapi import FastAPI
from starlette.testclient import TestClient

# The router we are testing
from app.api.routes.dashboard import router as dashboard_router
# The dependency we need to override
from app.api.dependencies import UserContext
# The module where services are instantiated, so we can patch them
from app.api.routes import dashboard as dashboard_module


@pytest.fixture
def client():
    """Fixture to create a test client with the dashboard router."""
    app = FastAPI()
    app.include_router(dashboard_router)
    return TestClient(app)


@pytest.fixture
def mock_user_context():
    """Fixture to create a mock UserContext for dependency overrides."""
    return UserContext(
        user_data={
            "user_id": str(uuid4()),
            "email": "test@example.com",
            "credits_remaining": 100,
            "bot_enabled": True,
        },
        permissions={"can_access_dashboard": True}
    )

# This is the main test class for the dashboard endpoints
@pytest.mark.asyncio
class TestDashboardDataEndpoint:
    """Tests for the GET /dashboard/data endpoint."""

    @pytest.fixture
    def sample_dashboard_data(self, mock_user_context):
        """Provides a sample of the data returned by the user_service."""
        return {
            "user_profile": {"user_id": mock_user_context.user_id, "display_name": "Test User"},
            "bot_status": {"status": "active", "bot_enabled": True},
            "credits": {"remaining": 100},
            "email_stats": {"total_processed": 50},
            "gmail_status": {"connected": True},
            "recent_activity": [{"event": "processed email"}],
            "timestamp": "2025-07-18T12:00:00Z"
        }

    def test_get_dashboard_data_success(self, client, mock_user_context, sample_dashboard_data):
        """
        Test the successful retrieval of complete dashboard data.
        """
        # --- Arrange ---
        
        # 1. Patch the service instance within the dashboard route module
        with patch.object(dashboard_module, "user_service", new=AsyncMock()) as mock_user_service:
            # 2. Configure the mock service method to return our sample data
            mock_user_service.get_dashboard_data.return_value = sample_dashboard_data

            # 3. Override the dependency to return our mock user context
            # This simulates a successful authentication and permission check
            async def override_dashboard_access():
                return mock_user_context

            client.app.dependency_overrides[dashboard_module.require_dashboard_access] = override_dashboard_access

            # --- Act ---
            # Make the request to the endpoint
            response = client.get("/dashboard/data")

            # --- Assert ---
            # Check that the service method was called correctly
            mock_user_service.get_dashboard_data.assert_awaited_once_with(mock_user_context.user_id)

            # Check for a successful response
            assert response.status_code == 200
            response_data = response.json()

            # Verify the structure and content of the response
            assert response_data["user_profile"]["user_id"] == mock_user_context.user_id
            assert response_data["bot_status"]["status"] == "active"
            assert "recent_activity" in response_data

        # Clean up the dependency override after the test
        client.app.dependency_overrides = {}


    def test_get_dashboard_data_not_found(self, client, mock_user_context):
        """
        Test the case where the user's dashboard data is not found.
        """
        # --- Arrange ---
        from app.core.exceptions import NotFoundError

        with patch.object(dashboard_module, "user_service", new=AsyncMock()) as mock_user_service:
            # Configure the mock to raise a NotFoundError, simulating a user not found in the DB
            mock_user_service.get_dashboard_data.side_effect = NotFoundError("User data not found")

            async def override_dashboard_access():
                return mock_user_context

            client.app.dependency_overrides[dashboard_module.require_dashboard_access] = override_dashboard_access

            # --- Act ---
            response = client.get("/dashboard/data")

            # --- Assert ---
            # The endpoint should catch the NotFoundError and return a 404 status code
            assert response.status_code == 404
            assert "not found" in response.json()["detail"].lower()
        
        client.app.dependency_overrides = {}


    def test_get_dashboard_data_generic_error(self, client, mock_user_context):
        """
        Test how the endpoint handles an unexpected generic exception from the service.
        """
        # --- Arrange ---
        with patch.object(dashboard_module, "user_service", new=AsyncMock()) as mock_user_service:
            # Configure the mock to raise a generic Exception
            mock_user_service.get_dashboard_data.side_effect = Exception("A major database error occurred")

            async def override_dashboard_access():
                return mock_user_context

            client.app.dependency_overrides[dashboard_module.require_dashboard_access] = override_dashboard_access

            # --- Act ---
            response = client.get("/dashboard/data")

            # --- Assert ---
            # The endpoint's generic exception handler should catch this and return a 500
            assert response.status_code == 500
            assert "failed to retrieve dashboard data" in response.json()["detail"].lower()

        client.app.dependency_overrides = {}


@pytest.mark.asyncio
class TestBotStatusEndpoint:
    """Tests for the GET /dashboard/status endpoint."""

    @pytest.fixture
    def sample_bot_status(self):
        """Provides a sample of the data returned by user_service.get_bot_status."""
        return {
            "bot_enabled": True,
            "gmail_connected": True,
            "credits_remaining": 100,
            "status": "active",
            "processing_frequency": "1h",
            "last_processing": "2025-07-18T11:00:00Z"
        }

    def test_get_bot_status_success(self, client, mock_user_context, sample_bot_status):
        """
        Test the successful retrieval of bot status.
        """
        # --- Arrange ---
        with patch.object(dashboard_module, "user_service", new=AsyncMock()) as mock_user_service:
            mock_user_service.get_bot_status.return_value = sample_bot_status
            
            async def override_dashboard_access():
                return mock_user_context
            client.app.dependency_overrides[dashboard_module.require_dashboard_access] = override_dashboard_access

            # --- Act ---
            response = client.get("/dashboard/status")

            # --- Assert ---
            mock_user_service.get_bot_status.assert_awaited_once_with(mock_user_context.user_id)
            assert response.status_code == 200
            response_data = response.json()
            assert response_data["status"] == "active"
            assert response_data["bot_enabled"] is True
            assert response_data["processing_frequency"] == "1h"

        client.app.dependency_overrides = {}

    def test_get_bot_status_generic_error(self, client, mock_user_context):
        """
        Test the endpoint's handling of a generic exception from the service.
        """
        # --- Arrange ---
        with patch.object(dashboard_module, "user_service", new=AsyncMock()) as mock_user_service:
            mock_user_service.get_bot_status.side_effect = Exception("Service unavailable")
            
            async def override_dashboard_access():
                return mock_user_context
            client.app.dependency_overrides[dashboard_module.require_dashboard_access] = override_dashboard_access

            # --- Act ---
            response = client.get("/dashboard/status")

            # --- Assert ---
            assert response.status_code == 500
            assert "failed to get bot status" in response.json()["detail"].lower()

        client.app.dependency_overrides = {}


@pytest.mark.asyncio
class TestBotToggleEndpoint:
    """Tests for the POST /dashboard/bot/toggle endpoint."""

    def test_enable_bot_success(self, client, mock_user_context):
        """Test successfully enabling the bot."""
        # --- Arrange ---
        with patch.object(dashboard_module, "user_service", new=AsyncMock()) as mock_user_service:
            mock_user_service.enable_bot.return_value = {"bot_enabled": True}
            
            async def override_dashboard_access():
                return mock_user_context
            client.app.dependency_overrides[dashboard_module.require_dashboard_access] = override_dashboard_access

            # --- Act ---
            response = client.post("/dashboard/bot/toggle", json={"enabled": True})

            # --- Assert ---
            mock_user_service.enable_bot.assert_awaited_once_with(mock_user_context.user_id)
            assert response.status_code == 200
            response_data = response.json()
            assert response_data["success"] is True
            assert response_data["bot_enabled"] is True
            assert "enabled" in response_data["message"]

        client.app.dependency_overrides = {}

    def test_disable_bot_success(self, client, mock_user_context):
        """Test successfully disabling the bot."""
        # --- Arrange ---
        with patch.object(dashboard_module, "user_service", new=AsyncMock()) as mock_user_service:
            mock_user_service.disable_bot.return_value = {"bot_enabled": False}
            
            async def override_dashboard_access():
                return mock_user_context
            client.app.dependency_overrides[dashboard_module.require_dashboard_access] = override_dashboard_access

            # --- Act ---
            response = client.post("/dashboard/bot/toggle", json={"enabled": False})

            # --- Assert ---
            mock_user_service.disable_bot.assert_awaited_once_with(mock_user_context.user_id)
            assert response.status_code == 200
            response_data = response.json()
            assert response_data["success"] is True
            assert response_data["bot_enabled"] is False
            assert "disabled" in response_data["message"]

        client.app.dependency_overrides = {}

    def test_toggle_bot_generic_error(self, client, mock_user_context):
        """Test a generic error when toggling bot status."""
        # --- Arrange ---
        with patch.object(dashboard_module, "user_service", new=AsyncMock()) as mock_user_service:
            mock_user_service.enable_bot.side_effect = Exception("Failed to update status")
            
            async def override_dashboard_access():
                return mock_user_context
            client.app.dependency_overrides[dashboard_module.require_dashboard_access] = override_dashboard_access

            # --- Act ---
            response = client.post("/dashboard/bot/toggle", json={"enabled": True})

            # --- Assert ---
            assert response.status_code == 500
            assert "failed to toggle bot status" in response.json()["detail"].lower()

        client.app.dependency_overrides = {}


@pytest.mark.asyncio
class TestEmailStatsEndpoint:
    """Tests for the GET /dashboard/stats/email endpoint."""

    @pytest.fixture
    def sample_email_stats(self):
        """Provides a sample of the data returned by user_service.get_user_statistics."""
        return {
            "total_emails_processed": 150,
            "successful_emails": 145,
            "failed_emails": 5,
            "success_rate": 0.967,
            "credits_used": 145,
            "avg_processing_time": 1.25
        }

    def test_get_email_statistics_success(self, client, mock_user_context, sample_email_stats):
        """
        Test the successful retrieval of email processing statistics.
        """
        # --- Arrange ---
        with patch.object(dashboard_module, "user_service", new=AsyncMock()) as mock_user_service:
            mock_user_service.get_user_statistics.return_value = sample_email_stats
            
            async def override_dashboard_access():
                return mock_user_context
            client.app.dependency_overrides[dashboard_module.require_dashboard_access] = override_dashboard_access

            # --- Act ---
            response = client.get("/dashboard/stats/email")

            # --- Assert ---
            mock_user_service.get_user_statistics.assert_awaited_once_with(mock_user_context.user_id)
            assert response.status_code == 200
            response_data = response.json()
            assert response_data["total_processed"] == 150
            assert response_data["success_rate"] == 0.967

        client.app.dependency_overrides = {}

    def test_get_email_statistics_generic_error(self, client, mock_user_context):
        """
        Test the endpoint's handling of a generic exception from the service.
        """
        # --- Arrange ---
        with patch.object(dashboard_module, "user_service", new=AsyncMock()) as mock_user_service:
            mock_user_service.get_user_statistics.side_effect = Exception("Stats DB offline")
            
            async def override_dashboard_access():
                return mock_user_context
            client.app.dependency_overrides[dashboard_module.require_dashboard_access] = override_dashboard_access

            # --- Act ---
            response = client.get("/dashboard/stats/email")

            # --- Assert ---
            assert response.status_code == 500
            assert "failed to get email statistics" in response.json()["detail"].lower()

        client.app.dependency_overrides = {}


@pytest.mark.asyncio
class TestCreditStatsEndpoint:
    """Tests for the GET /dashboard/stats/credits endpoint."""

    def test_get_credit_statistics_success(self, client, mock_user_context):
        """
        Test the successful retrieval of credit statistics.
        """
        # --- Arrange ---
        with patch.object(dashboard_module, "user_service", new=AsyncMock()) as mock_user_service:
            # Configure the mock service methods with sample return data
            mock_user_service.get_credit_balance.return_value = {
                "credits_remaining": 95,
                "last_updated": "2025-07-18T12:30:00Z"
            }
            mock_user_service.get_credit_history.return_value = {
                "transactions": [{"description": "Credit Purchase", "credit_amount": 100}],
                "total_transactions": 5
            }
            
            async def override_dashboard_access():
                return mock_user_context
            client.app.dependency_overrides[dashboard_module.require_dashboard_access] = override_dashboard_access

            # --- Act ---
            response = client.get("/dashboard/stats/credits")

            # --- Assert ---
            mock_user_service.get_credit_balance.assert_awaited_once_with(mock_user_context.user_id)
            mock_user_service.get_credit_history.assert_awaited_once_with(mock_user_context.user_id, limit=10)
            
            assert response.status_code == 200
            response_data = response.json()
            assert response_data["current_balance"] == 95
            assert len(response_data["recent_transactions"]) == 1
            assert response_data["total_transactions"] == 5

        client.app.dependency_overrides = {}

    def test_get_credit_statistics_generic_error(self, client, mock_user_context):
        """
        Test the endpoint's handling of a generic exception from the service.
        """
        # --- Arrange ---
        with patch.object(dashboard_module, "user_service", new=AsyncMock()) as mock_user_service:
            # Make one of the required service calls raise an error
            mock_user_service.get_credit_balance.side_effect = Exception("Billing service offline")
            
            async def override_dashboard_access():
                return mock_user_context
            client.app.dependency_overrides[dashboard_module.require_dashboard_access] = override_dashboard_access

            # --- Act ---
            response = client.get("/dashboard/stats/credits")

            # --- Assert ---
            assert response.status_code == 500
            assert "failed to get credit statistics" in response.json()["detail"].lower()

        client.app.dependency_overrides = {}


@pytest.mark.asyncio
class TestUsageStatsEndpoint:
    """Tests for the GET /dashboard/stats/usage endpoint."""

    def test_get_usage_statistics_success(self, client, mock_user_context):
        """
        Test the successful retrieval of usage statistics.
        """
        # --- Arrange ---
        # This endpoint uses multiple module-level services, so we patch them all.
        with patch.object(dashboard_module, "email_repository", new=Mock()) as mock_email_repo, \
             patch.object(dashboard_module, "gmail_service", new=Mock()) as mock_gmail_service:

            # Configure the mock return values
            mock_email_repo.get_processing_stats.return_value = {
                "total_processed": 77, "total_successful": 75
            }
            mock_gmail_service.get_user_gmail_statistics.return_value = {
                "connection_status": "connected", "total_discovered": 150
            }

            async def override_dashboard_access():
                return mock_user_context
            client.app.dependency_overrides[dashboard_module.require_dashboard_access] = override_dashboard_access

            # --- Act ---
            # Test with a custom 'days' query parameter
            response = client.get("/dashboard/stats/usage?days=60")

            # --- Assert ---
            mock_email_repo.get_processing_stats.assert_called_once_with(mock_user_context.user_id)
            mock_gmail_service.get_user_gmail_statistics.assert_called_once_with(mock_user_context.user_id)

            assert response.status_code == 200
            response_data = response.json()
            assert response_data["period_days"] == 60
            assert response_data["email_processing"]["total_processed"] == 77
            assert response_data["gmail_integration"]["connection_status"] == "connected"
            assert response_data["credits"]["remaining"] == mock_user_context.credits_remaining

        client.app.dependency_overrides = {}

    def test_get_usage_statistics_generic_error(self, client, mock_user_context):
        """
        Test the endpoint's handling of a generic exception from one of its services.
        """
        # --- Arrange ---
        with patch.object(dashboard_module, "email_repository", new=Mock()) as mock_email_repo, \
             patch.object(dashboard_module, "gmail_service", new=Mock()):
            
            # Configure one of the mocks to raise an error
            mock_email_repo.get_processing_stats.side_effect = Exception("Repository connection failed")

            async def override_dashboard_access():
                return mock_user_context
            client.app.dependency_overrides[dashboard_module.require_dashboard_access] = override_dashboard_access

            # --- Act ---
            response = client.get("/dashboard/stats/usage")

            # --- Assert ---
            assert response.status_code == 500
            assert "failed to get usage statistics" in response.json()["detail"].lower()

        client.app.dependency_overrides = {}


@pytest.mark.asyncio
class TestSettingsEndpoints:
    """Tests for the /dashboard/settings endpoints."""

    def test_get_user_settings_success(self, client, mock_user_context):
        """Test the successful retrieval of user settings."""
        # --- Arrange ---
        with patch.object(dashboard_module, "user_service", new=AsyncMock()) as mock_user_service:
            mock_user_service.get_user_preferences.return_value = {
                "email_filters": {"min_email_length": 100},
                "ai_preferences": {"summary_style": "concise"},
                "processing_frequency": "15min"
            }
            mock_user_service.get_user_profile.return_value = {
                "display_name": "Test User", "timezone": "UTC", "email": "test@example.com", "bot_enabled": True
            }

            async def override_dashboard_access():
                return mock_user_context
            client.app.dependency_overrides[dashboard_module.require_dashboard_access] = override_dashboard_access

            # --- Act ---
            response = client.get("/dashboard/settings")

            # --- Assert ---
            assert response.status_code == 200
            response_data = response.json()
            assert response_data["user_profile"]["display_name"] == "Test User"
            assert response_data["ai_preferences"]["summary_style"] == "concise"
            assert response_data["bot_enabled"] is True

        client.app.dependency_overrides = {}

    def test_update_user_settings_success(self, client, mock_user_context):
        """Test successfully updating multiple user settings at once."""
        # --- Arrange ---
        update_payload = {
            "timezone": "America/New_York",
            "ai_preferences": {"summary_length": "short"}
        }
        with patch.object(dashboard_module, "user_service", new=AsyncMock()) as mock_user_service:
            # Configure mocks for the update methods to return success
            mock_user_service.update_timezone.return_value = {"success": True}
            mock_user_service.update_ai_preferences.return_value = {"success": True}

            async def override_dashboard_access():
                return mock_user_context
            client.app.dependency_overrides[dashboard_module.require_dashboard_access] = override_dashboard_access

            # --- Act ---
            response = client.put("/dashboard/settings", json=update_payload)

            # --- Assert ---
            mock_user_service.update_timezone.assert_awaited_once_with(mock_user_context.user_id, "America/New_York")
            mock_user_service.update_ai_preferences.assert_awaited_once_with(mock_user_context.user_id, {"summary_length": "short"})
            mock_user_service.update_email_filters.assert_not_called() # Verify other methods aren't called

            assert response.status_code == 200
            response_data = response.json()
            assert response_data["success"] is True
            assert "timezone" in response_data["updates"]
            assert "ai_preferences" in response_data["updates"]

        client.app.dependency_overrides = {}

    def test_update_user_settings_validation_error(self, client, mock_user_context):
        """Test that a validation error from the service is handled correctly."""
        # --- Arrange ---
        from app.core.exceptions import ValidationError
        update_payload = {"processing_frequency": "invalid-frequency"}
        
        with patch.object(dashboard_module, "user_service", new=AsyncMock()) as mock_user_service:
            mock_user_service.update_processing_frequency.side_effect = ValidationError("Invalid frequency value")

            async def override_dashboard_access():
                return mock_user_context
            client.app.dependency_overrides[dashboard_module.require_dashboard_access] = override_dashboard_access

            # --- Act ---
            response = client.put("/dashboard/settings", json=update_payload)

            # --- Assert ---
            assert response.status_code == 422 # Unprocessable Entity
            assert "invalid frequency" in response.json()["detail"].lower()

        client.app.dependency_overrides = {}

    def test_reset_settings_success(self, client, mock_user_context):
        """Test successfully resetting user settings to default."""
        # --- Arrange ---
        with patch.object(dashboard_module, "user_service", new=AsyncMock()) as mock_user_service:
            mock_user_service.reset_preferences_to_default.return_value = {"preferences_reset": True}

            async def override_dashboard_access():
                return mock_user_context
            client.app.dependency_overrides[dashboard_module.require_dashboard_access] = override_dashboard_access

            # --- Act ---
            response = client.post("/dashboard/settings/reset")

            # --- Assert ---
            mock_user_service.reset_preferences_to_default.assert_awaited_once_with(mock_user_context.user_id)
            assert response.status_code == 200
            response_data = response.json()
            assert response_data["success"] is True
            assert response_data["preferences_reset"] is True

        client.app.dependency_overrides = {}


@pytest.mark.asyncio
class TestActivityEndpoint:
    """Tests for the GET /dashboard/activity endpoint."""

    def test_get_recent_activity_success(self, client, mock_user_context):
        """Test the successful retrieval and combination of recent activity."""
        # --- Arrange ---
        with patch.object(dashboard_module, "email_repository", new=Mock()) as mock_email_repo, \
             patch.object(dashboard_module, "user_service", new=AsyncMock()) as mock_user_service:

            # Configure mock return values for the two data sources
            mock_email_repo.get_processing_history.return_value = [
                {"processing_completed_at": "2025-07-18T12:00:00Z", "subject": "Email 1"}
            ]
            mock_user_service.get_credit_history.return_value = {
                "transactions": [
                    {"created_at": "2025-07-18T13:00:00Z", "description": "Credit Purchase"}
                ],
                "total_transactions": 1
            }

            async def override_dashboard_access():
                return mock_user_context
            client.app.dependency_overrides[dashboard_module.require_dashboard_access] = override_dashboard_access

            # --- Act ---
            response = client.get("/dashboard/activity?limit=10")

            # --- Assert ---
            mock_email_repo.get_processing_history.assert_called_once_with(mock_user_context.user_id, limit=10)
            mock_user_service.get_credit_history.assert_awaited_once_with(mock_user_context.user_id, limit=5)

            assert response.status_code == 200
            response_data = response.json()
            
            # Verify that activities from both sources are present
            assert len(response_data["activities"]) == 2
            # Verify that the activities are sorted correctly by timestamp (descending)
            assert response_data["activities"][0]["type"] == "credit_transaction"
            assert response_data["activities"][1]["type"] == "email_processed"

        client.app.dependency_overrides = {}

    def test_get_recent_activity_generic_error(self, client, mock_user_context):
        """Test the endpoint's handling of a generic exception."""
        # --- Arrange ---
        with patch.object(dashboard_module, "email_repository", new=Mock()) as mock_email_repo, \
             patch.object(dashboard_module, "user_service", new=AsyncMock()):
            
            mock_email_repo.get_processing_history.side_effect = Exception("Activity log is corrupted")

            async def override_dashboard_access():
                return mock_user_context
            client.app.dependency_overrides[dashboard_module.require_dashboard_access] = override_dashboard_access

            # --- Act ---
            response = client.get("/dashboard/activity")

            # --- Assert ---
            assert response.status_code == 500
            assert "failed to get recent activity" in response.json()["detail"].lower()

        client.app.dependency_overrides = {}


@pytest.mark.asyncio
class TestHealthEndpoint:
    """Tests for the GET /dashboard/health endpoint."""

    def test_get_user_system_health_success_healthy(self, client, mock_user_context):
        """Test the health check endpoint when all systems are healthy."""
        # --- Arrange ---
        with patch.object(dashboard_module, "gmail_service", new=Mock()) as mock_gmail_service, \
             patch.object(dashboard_module, "email_repository", new=Mock()) as mock_email_repo:

            mock_gmail_service.get_user_gmail_statistics.return_value = {"connection_status": "connected"}
            mock_email_repo.get_processing_stats.return_value = {"total_pending": 5}

            async def override_dashboard_access():
                return mock_user_context
            client.app.dependency_overrides[dashboard_module.require_dashboard_access] = override_dashboard_access

            # --- Act ---
            response = client.get("/dashboard/health")

            # --- Assert ---
            assert response.status_code == 200
            response_data = response.json()
            assert response_data["overall_status"] == "healthy"
            assert response_data["gmail_connection"]["status"] == "healthy"
            assert response_data["email_processing"]["status"] == "healthy"

        client.app.dependency_overrides = {}

    def test_get_user_system_health_degraded(self, client, mock_user_context):
        """Test the health check endpoint when a system is degraded."""
        # --- Arrange ---
        with patch.object(dashboard_module, "gmail_service", new=Mock()) as mock_gmail_service, \
             patch.object(dashboard_module, "email_repository", new=Mock()) as mock_email_repo:

            # Simulate a disconnected Gmail account, which should degrade the status
            mock_gmail_service.get_user_gmail_statistics.return_value = {"connection_status": "disconnected"}
            mock_email_repo.get_processing_stats.return_value = {"total_pending": 20} # High pending count

            async def override_dashboard_access():
                return mock_user_context
            client.app.dependency_overrides[dashboard_module.require_dashboard_access] = override_dashboard_access

            # --- Act ---
            response = client.get("/dashboard/health")

            # --- Assert ---
            assert response.status_code == 200
            response_data = response.json()
            assert response_data["overall_status"] == "degraded"
            assert response_data["gmail_connection"]["status"] == "unhealthy"
            assert response_data["email_processing"]["status"] == "degraded"

        client.app.dependency_overrides = {}
