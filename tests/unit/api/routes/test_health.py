# tests/unit/api/routes/test_health.py
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import patch

# Import the specific router to be tested
from app.api.routes.health import router as health_router
from app.api.dependencies import no_auth_required

# This is the test for the first, simplest route file.
# If this test passes, the testing pattern is correct.
# If it fails, the error is contained within `health.py` or its direct dependencies.

@pytest.fixture
def client() -> TestClient:
    """
    Provides a TestClient for the health router in complete isolation.
    """
    app = FastAPI(title="Test Health App")

    # The health routes depend on `no_auth_required` and `settings`.
    # We must provide mocks for them.
    def override_no_auth():
        return True

    app.dependency_overrides[no_auth_required] = override_no_auth

    # Use patch to mock the settings object used inside the health routes
    with patch('app.api.routes.health.settings') as mock_settings:
        # Define mock values for settings attributes accessed by health.py
        mock_settings.environment = "testing"
        mock_settings.debug_mode = True
        mock_settings.enable_stripe = False
        mock_settings.database_url = "mock_db_url"
        mock_settings.google_client_id = "mock_google_id"
        mock_settings.google_client_secret = "mock_google_secret"
        mock_settings.anthropic_api_key = "mock_anthropic_key"
        mock_settings.webapp_url = "http://mock-webapp.com"

        # Include ONLY the health router, replicating the prefix from main.py
        # The router's own prefix ("/health") will be added automatically.
        app.include_router(health_router, prefix="/api")

        with TestClient(app) as test_client:
            yield test_client

class TestHealthRoutes:
    """Test suite for the health check endpoints."""

    def test_health_check(self, client: TestClient):
        """Tests the basic /api/health/ endpoint."""
        response = client.get("/api/health/")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["environment"] == "testing"
        assert "timestamp" in data

    def test_detailed_health_check(self, client: TestClient):
        """Tests the /api/health/detailed endpoint."""
        response = client.get("/api/health/detailed")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "checks" in data
        assert "database" in data["checks"]
        assert data["checks"]["database"]["status"] == "healthy"

    def test_readiness_check(self, client: TestClient):
        """Tests the /api/health/ready endpoint."""
        response = client.get("/api/health/ready")
        assert response.status_code == 200
        data = response.json()
        assert data["ready"] is True
        assert data["checks"]["database"]["ready"] is True

    def test_liveness_check(self, client: TestClient):
        """Tests the /api/health/live endpoint."""
        response = client.get("/api/health/live")
        assert response.status_code == 200
        data = response.json()
        assert data["alive"] is True
        assert "uptime_seconds" in data

    def test_metrics_endpoint(self, client: TestClient):
        """Tests the /api/health/metrics endpoint."""
        response = client.get("/api/health/metrics")
        assert response.status_code == 200
        data = response.json()
        assert "metrics" in data
        assert "system" in data
        assert data["metrics"]["http_requests_total"] is not None

    def test_status_page_data(self, client: TestClient):
        """Tests the /api/health/status endpoint."""
        response = client.get("/api/health/status")
        assert response.status_code == 200
        data = response.json()
        assert "overall_status" in data
        assert "services" in data
        assert data["services"]["api"]["status"] == "operational"