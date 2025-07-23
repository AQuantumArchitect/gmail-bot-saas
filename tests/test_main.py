import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

# Import the new factory functions and helpers from main
from main import create_production_app, get_test_client
from app.api.dependencies import get_user_context
from app.core.exceptions import NotFoundError

# Use the provided helper to create a client configured specifically for testing
client = get_test_client()


class TestMainApp:
    """
    Tests for the main FastAPI application created via the application factory.
    """

    def test_root_endpoint(self):
        """
        Tests the root GET / endpoint for a successful response.
        """
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Email Bot API"

    def test_root_health_check(self):
        """
        Tests the root GET /health endpoint for a healthy status.
        """
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    def test_api_router_integration(self):
        """
        Tests that API routers are correctly included by checking a known sub-route.
        """
        response = client.get("/api/health")
        assert response.status_code == 200

    def test_catch_all_route_for_undefined_path(self):
        """
        Tests the catch-all route returns a formatted 404 for undefined paths.
        """
        response = client.get("/this/path/does/not/exist")
        assert response.status_code == 404
        data = response.json()
        assert data["error"] == "not_found"

    def test_docs_are_available_on_test_app(self):
        """
        Tests that API docs are available when using the test client, as it's non-production.
        """
        # The client is created by get_test_client(), which uses non-production settings
        response = client.get("/docs")
        assert response.status_code == 200

    def test_docs_are_not_available_in_production(self):
        """
        Tests that API docs are disabled when using the production factory.
        """
        # --- Arrange ---
        # We patch the configuration validator to prevent it from failing
        # on missing production environment variables in a test environment.
        with patch("main.validate_configuration", return_value=True):
            prod_app = create_production_app()
            prod_client = TestClient(prod_app)

            # --- Act ---
            response = prod_client.get("/docs")

            # --- Assert ---
            assert response.status_code == 404

    def test_custom_exception_handler_is_active(self):
        """
        Tests that the custom exception handlers are correctly wired up by the factory.
        """
        # --- Arrange ---
        # This function will raise a NotFoundError when the dependency is called
        def override_dependency_to_raise_error():
            raise NotFoundError("This error should be caught by the custom handler")

        # Hijack the dependency for a known route for the duration of this test
        client.app.dependency_overrides[get_user_context] = override_dependency_to_raise_error

        # --- Act ---
        # Call a route that uses the overridden dependency
        response = client.get("/api/auth/me", headers={"Authorization": "Bearer fake-token"})

        # --- Assert ---
        assert response.status_code == 404
        data = response.json()
        # Check for the specific structure produced by our custom handler
        assert data.get("error") == "not_found"
        assert data.get("message") == "This error should be caught by the custom handler"
        
        # --- Cleanup ---
        client.app.dependency_overrides = {}