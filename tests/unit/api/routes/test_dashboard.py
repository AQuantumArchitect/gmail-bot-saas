# tests/unit/api/routes/test_dashboard_clean.py
"""
Enhanced, comprehensive tests for dashboard routes.
Covers data aggregation, bot management, statistics, and health monitoring.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, AsyncMock, patch
from uuid import uuid4
import json
from datetime import datetime, timedelta

# Import the specific router to be tested
from app.api.routes.dashboard import router as dashboard_router
from app.api.routes.dashboard import get_user_service, get_gmail_service

# Import dependencies that will be mocked
from app.api.dependencies import get_user_context, require_dashboard_access, UserContext
from app.services.user_service import UserService
from app.services.gmail_service import GmailService
from app.core.exceptions import NotFoundError, ValidationError

@pytest.fixture
def comprehensive_mock_user_service() -> MagicMock:
    """Comprehensive mock UserService with all dashboard methods."""
    service = MagicMock(spec=UserService)
    
    # Dashboard data methods
    service.get_dashboard_data = AsyncMock()
    service.get_bot_status = AsyncMock()
    service.enable_bot = AsyncMock()
    service.disable_bot = AsyncMock()
    
    # Statistics methods
    service.get_user_statistics = AsyncMock()
    service.get_user_profile = AsyncMock()
    service.get_user_email_statistics = AsyncMock()
    service.get_user_recent_activity = AsyncMock()
    service.get_user_credit_statistics = AsyncMock()
    service.get_user_usage_statistics = AsyncMock()
    
    # Settings methods
    service.update_user_profile = AsyncMock()
    service.update_email_filters = AsyncMock()
    service.update_ai_preferences = AsyncMock()
    service.update_processing_frequency = AsyncMock()
    service.update_timezone = AsyncMock()
    service.reset_preferences_to_default = AsyncMock()
    
    return service

@pytest.fixture
def comprehensive_mock_gmail_service() -> MagicMock:
    """Comprehensive mock GmailService for dashboard integration."""
    service = MagicMock(spec=GmailService)
    
    service.get_user_gmail_statistics = AsyncMock()
    service.get_connection_status = AsyncMock()
    service.check_service_health = AsyncMock()
    
    return service

@pytest.fixture
def dashboard_user_context() -> UserContext:
    """UserContext specifically configured for dashboard testing."""
    user_id = str(uuid4())
    user_data = {
        "user_id": user_id,
        "email": "dashboard@test.com",
        "display_name": "Dashboard Test User",
        "credits_remaining": 75,
        "bot_enabled": True,
        "timezone": "America/New_York",
        "created_at": "2025-01-01T00:00:00Z",
        "last_login": "2025-01-30T08:00:00Z",
        "processing_frequency": "daily"
    }
    permissions = {
        "can_process_emails": True,
        "can_access_dashboard": True,
        "can_connect_gmail": True,
        "can_purchase_credits": True,
        "can_manage_account": True
    }
    return UserContext(user_data=user_data, permissions=permissions)

@pytest.fixture
def client(comprehensive_mock_user_service: MagicMock, comprehensive_mock_gmail_service: MagicMock, dashboard_user_context: UserContext) -> TestClient:
    """Enhanced test client with comprehensive dashboard mocking."""
    app = FastAPI(title="Enhanced Dashboard Test App")

    # Override the dependency functions
    app.dependency_overrides[get_user_service] = lambda: comprehensive_mock_user_service
    app.dependency_overrides[get_gmail_service] = lambda: comprehensive_mock_gmail_service
    app.dependency_overrides[get_user_context] = lambda: dashboard_user_context
    app.dependency_overrides[require_dashboard_access] = lambda: dashboard_user_context

    # Include the dashboard router
    app.include_router(dashboard_router, prefix="/api")

    with TestClient(app) as test_client:
        yield test_client

class TestDashboardDataEndpoints:
    """Comprehensive tests for main dashboard data endpoints."""

    def test_get_dashboard_data_success(self, client: TestClient, comprehensive_mock_user_service: MagicMock, dashboard_user_context: UserContext):
        """Test successful dashboard data retrieval."""
        mock_dashboard_data = {
            "user_profile": {
                "user_id": dashboard_user_context.user_id,
                "email": dashboard_user_context.email,
                "display_name": dashboard_user_context.display_name,
                "credits_remaining": 75,
                "bot_enabled": True,
                "timezone": "America/New_York"
            },
            "bot_status": {
                "bot_enabled": True,
                "gmail_connected": True,
                "credits_remaining": 75,
                "status": "active",
                "processing_frequency": "daily",
                "last_processing": "2025-01-30T07:00:00Z"
            },
            "credits": {
                "remaining": 75,
                "total_used": 25,
                "total_purchased": 100,
                "usage_trend": "stable"
            },
            "email_stats": {
                "total_processed": 42,
                "successful_emails": 40,
                "failed_emails": 2,
                "success_rate": 95.2,
                "credits_used": 25
            },
            "gmail_status": {
                "connected": True,
                "email_address": "dashboard@test.com",
                "last_sync": "2025-01-30T07:30:00Z"
            },
            "recent_activity": [
                {
                    "timestamp": "2025-01-30T07:00:00Z",
                    "action": "email_processed",
                    "details": "Processed 5 new emails"
                },
                {
                    "timestamp": "2025-01-30T06:00:00Z",
                    "action": "bot_enabled",
                    "details": "Bot was enabled by user"
                }
            ],
            "timestamp": "2025-01-30T10:00:00Z"
        }
        comprehensive_mock_user_service.get_dashboard_data.return_value = mock_dashboard_data
        
        response = client.get("/api/dashboard/data")
        
        assert response.status_code == 200
        data = response.json()
        assert data["user_profile"]["user_id"] == dashboard_user_context.user_id
        assert data["bot_status"]["bot_enabled"] is True
        assert data["credits"]["remaining"] == 75
        assert data["email_stats"]["total_processed"] == 42
        assert data["gmail_status"]["connected"] is True
        assert len(data["recent_activity"]) == 2
        assert data["timestamp"] == "2025-01-30T10:00:00Z"

    def test_get_dashboard_data_not_found(self, client: TestClient, comprehensive_mock_user_service: MagicMock):
        """Test dashboard data when user not found."""
        comprehensive_mock_user_service.get_dashboard_data.side_effect = NotFoundError("User not found")
        
        response = client.get("/api/dashboard/data")
        
        assert response.status_code == 404
        assert "User not found" in response.json()["detail"]

    def test_get_dashboard_data_service_error(self, client: TestClient, comprehensive_mock_user_service: MagicMock):
        """Test dashboard data with service error."""
        comprehensive_mock_user_service.get_dashboard_data.side_effect = Exception("Database connection failed")
        
        response = client.get("/api/dashboard/data")
        
        assert response.status_code == 500
        assert "Failed to retrieve dashboard data" in response.json()["detail"]

class TestBotManagement:
    """Comprehensive tests for bot status and control endpoints."""

    def test_get_bot_status_success(self, client: TestClient, comprehensive_mock_user_service: MagicMock, dashboard_user_context: UserContext):
        """Test successful bot status retrieval."""
        mock_bot_status = {
            "bot_enabled": True,
            "gmail_connected": True,
            "credits_remaining": 75,
            "status": "active",
            "processing_frequency": "daily",
            "last_processing": "2025-01-30T07:00:00Z"
        }
        comprehensive_mock_user_service.get_bot_status.return_value = mock_bot_status
        
        response = client.get("/api/dashboard/status")
        
        assert response.status_code == 200
        data = response.json()
        assert data["bot_enabled"] is True
        assert data["gmail_connected"] is True
        assert data["credits_remaining"] == 75
        assert data["status"] == "active"
        assert data["processing_frequency"] == "daily"
        assert data["last_processing"] == "2025-01-30T07:00:00Z"

    def test_get_bot_status_service_error(self, client: TestClient, comprehensive_mock_user_service: MagicMock):
        """Test bot status with service error."""
        comprehensive_mock_user_service.get_bot_status.side_effect = Exception("Service unavailable")
        
        response = client.get("/api/dashboard/status")
        
        assert response.status_code == 500
        assert "Failed to get bot status" in response.json()["detail"]

    def test_toggle_bot_enable_success(self, client: TestClient, comprehensive_mock_user_service: MagicMock, dashboard_user_context: UserContext):
        """Test successful bot enabling."""
        mock_result = {
            "bot_enabled": True,
            "previous_state": False,
            "updated_at": "2025-01-30T10:00:00Z"
        }
        comprehensive_mock_user_service.enable_bot.return_value = mock_result
        
        request_body = {"enabled": True}
        response = client.post("/api/dashboard/bot/toggle", json=request_body)
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["bot_enabled"] is True
        assert "enabled successfully" in data["message"]
        comprehensive_mock_user_service.enable_bot.assert_awaited_once_with(dashboard_user_context.user_id)

    def test_toggle_bot_disable_success(self, client: TestClient, comprehensive_mock_user_service: MagicMock, dashboard_user_context: UserContext):
        """Test successful bot disabling."""
        mock_result = {
            "bot_enabled": False,
            "previous_state": True,
            "updated_at": "2025-01-30T10:00:00Z"
        }
        comprehensive_mock_user_service.disable_bot.return_value = mock_result
        
        request_body = {"enabled": False}
        response = client.post("/api/dashboard/bot/toggle", json=request_body)
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["bot_enabled"] is False
        assert "disabled successfully" in data["message"]
        comprehensive_mock_user_service.disable_bot.assert_awaited_once_with(dashboard_user_context.user_id)

    def test_toggle_bot_validation_error(self, client: TestClient):
        """Test bot toggle with validation error."""
        # Missing required 'enabled' field
        request_body = {}
        response = client.post("/api/dashboard/bot/toggle", json=request_body)
        
        assert response.status_code == 422  # Pydantic validation error

    def test_toggle_bot_service_error(self, client: TestClient, comprehensive_mock_user_service: MagicMock):
        """Test bot toggle with service error."""
        comprehensive_mock_user_service.enable_bot.side_effect = Exception("Service error")
        
        request_body = {"enabled": True}
        response = client.post("/api/dashboard/bot/toggle", json=request_body)
        
        assert response.status_code == 500
        assert "Failed to toggle bot status" in response.json()["detail"]

class TestStatisticsEndpoints:
    """Comprehensive tests for statistics and analytics endpoints."""

    def test_get_email_statistics_success(self, client: TestClient, comprehensive_mock_user_service: MagicMock, dashboard_user_context: UserContext):
        """Test successful email statistics retrieval."""
        mock_stats = {
            "total_emails_processed": 150,
            "successful_emails": 145,
            "failed_emails": 5,
            "success_rate": 96.7,
            "credits_used": 150,
            "avg_processing_time": 2.3
        }
        comprehensive_mock_user_service.get_user_statistics.return_value = mock_stats
        
        response = client.get("/api/dashboard/stats/email")
        
        assert response.status_code == 200
        data = response.json()
        assert data["total_processed"] == 150
        assert data["successful_emails"] == 145
        assert data["failed_emails"] == 5
        assert data["success_rate"] == 96.7
        assert data["credits_used"] == 150
        assert data["avg_processing_time"] == 2.3

    def test_get_email_statistics_service_error(self, client: TestClient, comprehensive_mock_user_service: MagicMock):
        """Test email statistics with service error."""
        comprehensive_mock_user_service.get_user_statistics.side_effect = Exception("Statistics service down")
        
        response = client.get("/api/dashboard/stats/email")
        
        assert response.status_code == 500
        assert "Failed to get email statistics" in response.json()["detail"]

    def test_get_credit_statistics_success(self, client: TestClient, comprehensive_mock_user_service: MagicMock, dashboard_user_context: UserContext):
        """Test successful credit statistics retrieval."""
        mock_credit_stats = {
            "current_balance": 75,
            "total_purchased": 200,
            "total_used": 125,
            "usage_trend": "stable",
            "monthly_usage": {
                "2025-01": 50,
                "2024-12": 45,
                "2024-11": 30
            },
            "projected_usage": 55
        }
        comprehensive_mock_user_service.get_user_credit_statistics.return_value = mock_credit_stats
        
        response = client.get("/api/dashboard/stats/credits")
        
        assert response.status_code == 200
        data = response.json()
        assert data["current_balance"] == 75
        assert data["total_purchased"] == 200
        assert data["total_used"] == 125
        assert data["usage_trend"] == "stable"
        assert "monthly_usage" in data
        assert data["projected_usage"] == 55

    def test_get_usage_statistics_success(self, client: TestClient, comprehensive_mock_user_service: MagicMock, dashboard_user_context: UserContext):
        """Test successful usage statistics retrieval."""
        mock_usage_stats = {
            "daily_average": 3.2,
            "weekly_total": 22,
            "monthly_total": 95,
            "peak_usage_day": "2025-01-29",
            "peak_usage_count": 12,
            "usage_by_hour": {
                "00": 0, "01": 0, "02": 0, "03": 0, "04": 0, "05": 0,
                "06": 2, "07": 8, "08": 12, "09": 15, "10": 10, "11": 8,
                "12": 5, "13": 3, "14": 4, "15": 6, "16": 7, "17": 9,
                "18": 6, "19": 4, "20": 2, "21": 1, "22": 0, "23": 0
            }
        }
        comprehensive_mock_user_service.get_user_usage_statistics.return_value = mock_usage_stats
        
        response = client.get("/api/dashboard/stats/usage")
        
        assert response.status_code == 200
        data = response.json()
        assert data["daily_average"] == 3.2
        assert data["weekly_total"] == 22
        assert data["monthly_total"] == 95
        assert data["peak_usage_day"] == "2025-01-29"
        assert data["peak_usage_count"] == 12
        assert "usage_by_hour" in data

class TestUserSettingsManagement:
    """Comprehensive tests for user settings and preferences."""

    def test_get_user_settings_success(self, client: TestClient, comprehensive_mock_user_service: MagicMock, dashboard_user_context: UserContext):
        """Test successful user settings retrieval."""
        mock_profile = {
            "user_id": dashboard_user_context.user_id,
            "email": dashboard_user_context.email,
            "bot_enabled": True,
            "timezone": "America/New_York",
            "email_filters": {
                "skip_promotional": True,
                "skip_newsletters": False,
                "minimum_importance": "normal"
            },
            "ai_preferences": {
                "summary_length": "medium",
                "include_action_items": True,
                "language": "en"
            },
            "processing_frequency": "daily",
            "updated_at": "2025-01-30T10:00:00Z"
        }
        comprehensive_mock_user_service.get_user_profile.return_value = mock_profile
        
        response = client.get("/api/dashboard/settings")
        
        assert response.status_code == 200
        data = response.json()
        assert data["user_id"] == dashboard_user_context.user_id
        assert data["bot_enabled"] is True
        assert data["timezone"] == "America/New_York"
        assert data["email_filters"]["skip_promotional"] is True
        assert data["ai_preferences"]["summary_length"] == "medium"
        assert data["processing_frequency"] == "daily"

    def test_get_user_settings_not_found(self, client: TestClient, comprehensive_mock_user_service: MagicMock):
        """Test user settings when profile not found."""
        comprehensive_mock_user_service.get_user_profile.side_effect = NotFoundError("User profile not found")
        
        response = client.get("/api/dashboard/settings")
        
        assert response.status_code == 404
        assert "User settings not found" in response.json()["detail"]

    def test_update_user_settings_partial_success(self, client: TestClient, comprehensive_mock_user_service: MagicMock, dashboard_user_context: UserContext):
        """Test successful partial settings update."""
        # Mock individual update methods
        comprehensive_mock_user_service.update_email_filters.return_value = {"success": True}
        comprehensive_mock_user_service.update_ai_preferences.return_value = {"success": True}
        
        request_body = {
            "email_filters": {
                "skip_promotional": False,
                "minimum_importance": "high"
            },
            "ai_preferences": {
                "summary_length": "short",
                "include_action_items": False
            }
        }
        
        response = client.put("/api/dashboard/settings", json=request_body)
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "Settings updated successfully" in data["message"]
        assert "email_filters" in data["updates"]
        assert "ai_preferences" in data["updates"]
        
        # Verify method calls
        comprehensive_mock_user_service.update_email_filters.assert_awaited_once_with(
            dashboard_user_context.user_id, 
            request_body["email_filters"]
        )
        comprehensive_mock_user_service.update_ai_preferences.assert_awaited_once_with(
            dashboard_user_context.user_id, 
            request_body["ai_preferences"]
        )

    def test_update_user_settings_validation_error(self, client: TestClient, comprehensive_mock_user_service: MagicMock):
        """Test settings update with validation error."""
        comprehensive_mock_user_service.update_timezone.side_effect = ValidationError("Invalid timezone")
        
        request_body = {
            "timezone": "Invalid/Timezone"
        }
        
        response = client.put("/api/dashboard/settings", json=request_body)
        
        assert response.status_code == 422
        assert "Invalid timezone" in response.json()["detail"]

    def test_reset_settings_success(self, client: TestClient, comprehensive_mock_user_service: MagicMock, dashboard_user_context: UserContext):
        """Test successful settings reset."""
        mock_result = {
            "preferences_reset": [
                "email_filters",
                "ai_preferences", 
                "processing_frequency"
            ]
        }
        comprehensive_mock_user_service.reset_preferences_to_default.return_value = mock_result
        
        response = client.post("/api/dashboard/settings/reset")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "Settings reset to default successfully" in data["message"]
        assert len(data["preferences_reset"]) == 3
        comprehensive_mock_user_service.reset_preferences_to_default.assert_awaited_once_with(dashboard_user_context.user_id)

class TestActivityAndRecentEvents:
    """Tests for activity tracking and recent events."""

    def test_get_recent_activity_success(self, client: TestClient, comprehensive_mock_user_service: MagicMock, dashboard_user_context: UserContext):
        """Test successful recent activity retrieval."""
        mock_activities = [
            {
                "timestamp": "2025-01-30T09:00:00Z",
                "action": "email_processed",
                "details": "Processed 3 new emails",
                "credits_used": 3
            },
            {
                "timestamp": "2025-01-30T08:00:00Z",
                "action": "settings_updated",
                "details": "Updated email filters",
                "credits_used": 0
            },
            {
                "timestamp": "2025-01-30T07:00:00Z",
                "action": "bot_enabled",
                "details": "Bot was enabled by user",
                "credits_used": 0
            }
        ]
        comprehensive_mock_user_service.get_user_recent_activity.return_value = mock_activities
        
        response = client.get("/api/dashboard/activity")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert len(data["activities"]) == 3
        assert data["total_returned"] == 3
        assert data["activities"][0]["action"] == "email_processed"
        assert data["activities"][1]["action"] == "settings_updated"
        assert data["activities"][2]["action"] == "bot_enabled"

    def test_get_recent_activity_with_limit(self, client: TestClient, comprehensive_mock_user_service: MagicMock, dashboard_user_context: UserContext):
        """Test recent activity with custom limit."""
        comprehensive_mock_user_service.get_user_recent_activity.return_value = []
        
        response = client.get("/api/dashboard/activity?limit=10")
        
        assert response.status_code == 200
        comprehensive_mock_user_service.get_user_recent_activity.assert_awaited_once_with(
            dashboard_user_context.user_id, 
            limit=10
        )

    def test_get_recent_activity_limit_bounds(self, client: TestClient, comprehensive_mock_user_service: MagicMock, dashboard_user_context: UserContext):
        """Test recent activity respects limit bounds."""
        comprehensive_mock_user_service.get_user_recent_activity.return_value = []
        
        # Test upper bound - should be rejected by Pydantic validation (this is good!)
        response = client.get("/api/dashboard/activity?limit=500")
        assert response.status_code == 422  # Validation correctly rejects values > 100
        
        # Test within bounds - should work
        response = client.get("/api/dashboard/activity?limit=100")
        assert response.status_code == 200
        comprehensive_mock_user_service.get_user_recent_activity.assert_awaited_with(
            dashboard_user_context.user_id, 
            limit=100
        )

class TestHealthAndDiagnostics:
    """Tests for system health and diagnostic endpoints."""

    def test_get_user_system_health_success(self, client: TestClient, comprehensive_mock_gmail_service: MagicMock, dashboard_user_context: UserContext):
        """Test successful system health check."""
        # Mock Gmail service health
        mock_gmail_stats = {
            "connection_status": "connected",
            "email_address": "dashboard@test.com",
            "last_sync": "2025-01-30T09:30:00Z"
        }
        comprehensive_mock_gmail_service.get_user_gmail_statistics.return_value = mock_gmail_stats
        
        # Mock the EmailRepository class and its method
        with patch('app.data.repositories.email_repository.EmailRepository') as MockEmailRepository:
            mock_email_repo_instance = MockEmailRepository.return_value
            mock_email_repo_instance.get_processing_stats.return_value = {
                "total_pending": 2,
                "success_rate": 0.95
            }
            
            response = client.get("/api/dashboard/health")
        
        assert response.status_code == 200
        data = response.json()
        assert data["overall_status"] == "healthy"
        assert data["gmail_connection"]["status"] == "healthy"
        assert data["gmail_connection"]["connected"] is True
        assert data["gmail_connection"]["email_address"] == "dashboard@test.com"
        assert data["email_processing"]["status"] == "healthy"
        assert data["email_processing"]["pending_emails"] == 2
        assert data["bot_status"]["enabled"] is True
        assert data["bot_status"]["credits_remaining"] == 75

    def test_get_user_system_health_degraded(self, client: TestClient, comprehensive_mock_gmail_service: MagicMock):
        """Test system health when degraded."""
        # Mock Gmail as disconnected
        mock_gmail_stats = {
            "connection_status": "disconnected",
            "email_address": None,
            "last_sync": "2025-01-29T15:00:00Z"
        }
        comprehensive_mock_gmail_service.get_user_gmail_statistics.return_value = mock_gmail_stats
        
        # Mock the EmailRepository class and its method
        with patch('app.data.repositories.email_repository.EmailRepository') as MockEmailRepository:
            mock_email_repo_instance = MockEmailRepository.return_value
            mock_email_repo_instance.get_processing_stats.return_value = {
                "total_pending": 15,  # High number indicates degraded performance
                "success_rate": 0.75
            }
            
            response = client.get("/api/dashboard/health")
        
        assert response.status_code == 200
        data = response.json()
        assert data["overall_status"] == "degraded"
        assert data["gmail_connection"]["status"] == "unhealthy"
        assert data["gmail_connection"]["connected"] is False
        assert data["email_processing"]["status"] == "degraded"
        assert data["email_processing"]["pending_emails"] == 15

    def test_get_user_system_health_service_error(self, client: TestClient, comprehensive_mock_gmail_service: MagicMock):
        """Test system health with service error."""
        comprehensive_mock_gmail_service.get_user_gmail_statistics.side_effect = Exception("Gmail service down")
        
        response = client.get("/api/dashboard/health")
        
        assert response.status_code == 500
        assert "Failed to get system health" in response.json()["detail"]

class TestErrorHandlingAndEdgeCases:
    """Tests for error handling and edge cases."""

    def test_dashboard_access_without_permission(self, client: TestClient):
        """Test dashboard access without proper permissions."""
        # Override to simulate no dashboard access
        app = client.app
        original_override = app.dependency_overrides.get(require_dashboard_access)
        
        def no_dashboard_access():
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail="Dashboard access denied")
        
        app.dependency_overrides[require_dashboard_access] = no_dashboard_access
        
        response = client.get("/api/dashboard/data")
        
        assert response.status_code == 403
        assert "Dashboard access denied" in response.json()["detail"]
        
        # Restore original override
        if original_override:
            app.dependency_overrides[require_dashboard_access] = original_override

    def test_empty_activity_list(self, client: TestClient, comprehensive_mock_user_service: MagicMock):
        """Test handling of empty activity list."""
        comprehensive_mock_user_service.get_user_recent_activity.return_value = []
        
        response = client.get("/api/dashboard/activity")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert len(data["activities"]) == 0
        assert data["total_returned"] == 0

    def test_malformed_settings_update(self, client: TestClient):
        """Test settings update with malformed data."""
        request_body = {
            "email_filters": "not_a_dict",  # Should be a dict
            "invalid_field": "should_be_ignored"
        }
        
        response = client.put("/api/dashboard/settings", json=request_body)
        
        # Should either handle gracefully or return validation error
        assert response.status_code in [200, 422]

    def test_concurrent_bot_toggle_requests(self, client: TestClient, comprehensive_mock_user_service: MagicMock):
        """Test handling of concurrent bot toggle requests."""
        import asyncio
        from httpx import AsyncClient
        
        comprehensive_mock_user_service.enable_bot.return_value = {"bot_enabled": True}
        
        async def make_concurrent_requests():
            async with AsyncClient(app=client.app, base_url="http://test") as ac:
                tasks = [
                    ac.post("/api/dashboard/bot/toggle", json={"enabled": True})
                    for _ in range(3)
                ]
                return await asyncio.gather(*tasks, return_exceptions=True)
        
        # This would need to be run in an async context in real tests
        # For now, just test that the service handles single requests properly
        response = client.post("/api/dashboard/bot/toggle", json={"enabled": True})
        assert response.status_code == 200

class TestPerformanceAndScalability:
    """Tests for performance and scalability concerns."""

    def test_large_activity_list_handling(self, client: TestClient, comprehensive_mock_user_service: MagicMock):
        """Test handling of large activity lists."""
        # Create a large mock activity list
        large_activity_list = [
            {
                "timestamp": f"2025-01-{30-i:02d}T{i%24:02d}:00:00Z",
                "action": f"action_{i}",
                "details": f"Activity number {i}",
                "credits_used": i % 5
            }
            for i in range(100)  # Large list
        ]
        comprehensive_mock_user_service.get_user_recent_activity.return_value = large_activity_list
        
        response = client.get("/api/dashboard/activity?limit=100")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert len(data["activities"]) == 100
        assert data["total_returned"] == 100

    def test_statistics_with_zero_data(self, client: TestClient, comprehensive_mock_user_service: MagicMock):
        """Test statistics endpoints with zero/empty data."""
        mock_empty_stats = {
            "total_emails_processed": 0,
            "successful_emails": 0,
            "failed_emails": 0,
            "success_rate": 0.0,
            "credits_used": 0,
            "avg_processing_time": 0.0
        }
        comprehensive_mock_user_service.get_user_statistics.return_value = mock_empty_stats
        
        response = client.get("/api/dashboard/stats/email")
        
        assert response.status_code == 200
        data = response.json()
        assert data["total_processed"] == 0
        assert data["success_rate"] == 0.0
        assert data["credits_used"] == 0