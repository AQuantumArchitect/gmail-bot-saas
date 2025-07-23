import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock

# Import the router and settings to be tested/used
from app.api.routes.health import router as health_router
from app.core.config import settings

# Create a minimal FastAPI app instance and include the health router
app = FastAPI()
app.include_router(health_router)

# Instantiate the test client
client = TestClient(app)


class TestHealthRoutes:
    """
    Tests for the health check API endpoints located in app/api/routes/health.py.
    """

    def test_health_check_success(self):
        """
        Tests the basic GET /health endpoint for a successful 200 response and correct structure.
        """
        # --- Act ---
        response = client.get("/health")

        # --- Assert ---
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "healthy"
        assert data["version"] == "1.0.0"
        assert "timestamp" in data
        assert "environment" in data

    def test_liveness_check_success(self):
        """
        Tests the GET /health/live endpoint for a successful 200 response
        and confirmation that the service is alive.
        """
        # --- Act ---
        response = client.get("/health/live")

        # --- Assert ---
        assert response.status_code == 200
        
        data = response.json()
        assert data["alive"] is True
        assert "timestamp" in data

    def test_readiness_check_success(self):
        """
        Tests the GET /health/ready endpoint for a successful 200 response
        and confirmation that the service is ready.
        """
        # --- Act ---
        response = client.get("/health/ready")

        # --- Assert ---
        assert response.status_code == 200
        
        data = response.json()
        assert data["ready"] is True
        assert data["status_code"] == 200
        assert data["checks"]["database"]["ready"] is True
        assert data["checks"]["services"]["auth_service"] is True

    def test_readiness_check_handles_stripe_setting(self, monkeypatch):
        """
        Tests that the readiness check correctly reflects the Stripe setting.
        """
        # --- Arrange: Stripe Disabled ---
        monkeypatch.setattr(settings, "enable_stripe", False)

        # --- Act: Stripe Disabled ---
        response_stripe_disabled = client.get("/health/ready")
        data_disabled = response_stripe_disabled.json()

        # --- Assert: Stripe Disabled ---
        assert data_disabled["checks"]["services"]["billing_service"] is False

        # --- Arrange: Stripe Enabled ---
        monkeypatch.setattr(settings, "enable_stripe", True)

        # --- Act: Stripe Enabled ---
        response_stripe_enabled = client.get("/health/ready")
        data_enabled = response_stripe_enabled.json()

        # --- Assert: Stripe Enabled ---
        assert data_enabled["checks"]["services"]["billing_service"] is True
    
    @patch("app.api.routes.health._check_system_resources", return_value={"status": "healthy"})
    @patch("app.api.routes.health._check_configuration", return_value={"status": "healthy"})
    @patch("app.api.routes.health._check_external_services", new_callable=AsyncMock, return_value={"status": "healthy"})
    def test_detailed_health_check_all_healthy(self, mock_external, mock_config, mock_system):
        """
        Tests the GET /health/detailed endpoint when all components are healthy.
        """
        # --- Act ---
        response = client.get("/health/detailed")

        # --- Assert ---
        assert response.status_code == 200
        data = response.json()

        assert data["status"] == "healthy"
        assert data["checks"]["database"]["status"] == "healthy"
        assert data["checks"]["external_services"]["status"] == "healthy"
        assert data["checks"]["configuration"]["status"] == "healthy"
        assert data["checks"]["system"]["status"] == "healthy"
        
        # Verify our mocks were called
        mock_external.assert_awaited_once()
        mock_config.assert_called_once()
        mock_system.assert_called_once()

    @patch("app.api.routes.health._check_system_resources", return_value={"status": "healthy"})
    @patch("app.api.routes.health._check_configuration", return_value={"status": "unhealthy"})
    @patch("app.api.routes.health._check_external_services", new_callable=AsyncMock, return_value={"status": "healthy"})
    def test_detailed_health_check_one_unhealthy_component(self, mock_external, mock_config, mock_system):
        """
        Tests that the overall status is 'unhealthy' if even one component is unhealthy.
        """
        # --- Act ---
        response = client.get("/health/detailed")

        # --- Assert ---
        assert response.status_code == 200
        data = response.json()

        assert data["status"] == "unhealthy"
        assert data["checks"]["configuration"]["status"] == "unhealthy"

    @patch("app.api.routes.health._check_system_resources", return_value={"status": "healthy"})
    @patch("app.api.routes.health._check_configuration", return_value={"status": "degraded"})
    @patch("app.api.routes.health._check_external_services", new_callable=AsyncMock, return_value={"status": "healthy"})
    def test_detailed_health_check_degraded_status(self, mock_external, mock_config, mock_system):
        """
        Tests that the overall status is 'degraded' if one component is degraded
        and none are unhealthy.
        """
        # --- Act ---
        response = client.get("/health/detailed")

        # --- Assert ---
        assert response.status_code == 200
        data = response.json()

        assert data["status"] == "degraded"
        assert data["checks"]["configuration"]["status"] == "degraded"