# tests/unit/api/test_middleware.py
"""
Unit tests for the API middleware.
"""
import logging
import time
import uuid
import json
from unittest.mock import patch, AsyncMock, MagicMock

import pytest
from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.testclient import TestClient
from starlette.responses import JSONResponse

# Import the middleware to be tested
from app.api.middleware import (
    RequestLoggingMiddleware,
    SecurityHeadersMiddleware,
    RateLimitMiddleware,
    ErrorHandlingMiddleware,
    DebugMiddleware,
    setup_cors_middleware,
    setup_all_middleware,
    setup_development_middleware,
    get_request_id,
    get_processing_time,
    add_audit_context,
)
# We need to patch the settings dependency within the middleware module
from app.api import middleware as middleware_module
from app.core.config import Settings


# A simple async endpoint for testing
async def success_endpoint(request: Request):
    """An endpoint that always succeeds."""
    return JSONResponse({"message": "Hello, World!"})

# An endpoint that always raises an error
async def exception_endpoint(request: Request):
    """An endpoint that always raises a ValueError."""
    raise ValueError("This is a test error")


@pytest.fixture
def mock_settings():
    """
    Fixture for a mock settings object.
    This uses a simple mock to avoid Pydantic validation issues in tests.
    """
    # Using MagicMock to bypass the complex Pydantic validation for tests.
    # This avoids having to create a perfect Settings object every time.
    settings = MagicMock(spec=Settings)
    settings.environment = "testing"
    settings.is_production = False
    settings.webapp_url = "http://localhost:3000"
    return settings

@pytest.mark.asyncio
class TestRequestLoggingMiddleware:
    """Tests for the RequestLoggingMiddleware."""

    @pytest.fixture
    def client(self):
        """Client fixture that ONLY includes the RequestLoggingMiddleware."""
        app = FastAPI()
        app.add_middleware(RequestLoggingMiddleware, log_level="DEBUG")
        app.add_route("/", success_endpoint)
        app.add_route("/error", exception_endpoint)
        return TestClient(app)

    @patch("app.api.middleware.time.time")
    @patch("app.api.middleware.uuid.uuid4")
    @patch("app.api.middleware.logger")
    async def test_successful_request_logging(self, mock_logger, mock_uuid, mock_time, client):
        """Test that a successful request is logged correctly with headers."""
        mock_uuid.return_value = uuid.UUID("12345678-1234-5678-1234-567812345678")
        # Add more buffer values to the side_effect list to prevent StopIteration.
        mock_time.side_effect = [1000.0, 1000.5, 1001.0, 1002.0, 1003.0]

        response = client.get("/")

        assert response.status_code == 200
        assert response.headers["X-Request-ID"] == "12345678-1234-5678-1234-567812345678"
        
        log_messages = [call.args[1] for call in mock_logger.log.call_args_list]
        assert any("REQUEST 12345678-1234-5678-1234-567812345678" in msg for msg in log_messages)
        assert any("RESPONSE 12345678-1234-5678-1234-567812345678 - 200" in msg for msg in log_messages)

    @patch("app.api.middleware.time.time")
    @patch("app.api.middleware.uuid.uuid4")
    @patch("app.api.middleware.logger")
    async def test_exception_handling_and_logging(self, mock_logger, mock_uuid, mock_time, client):
        """Test that the middleware's own exception handler works correctly."""
        mock_uuid.return_value = "error-uuid"
        mock_time.side_effect = [2000.0, 2000.8, 2001.0]

        response = client.get("/error")

        assert response.status_code == 500
        assert response.json()["error"] == "internal_server_error"

        mock_logger.error.assert_called_once()
        log_message = mock_logger.error.call_args[0][0]
        assert "ERROR error-uuid - ValueError: This is a test error" in log_message
        assert "in 0.800s" in log_message

    @pytest.mark.parametrize("headers, expected_ip", [
        ({"x-forwarded-for": "1.1.1.1, 2.2.2.2"}, "1.1.1.1"),
        ({"x-real-ip": "3.3.3.3"}, "3.3.3.3"),
    ])
    async def test_get_client_ip(self, headers, expected_ip):
        """Test the _get_client_ip helper method with various headers."""
        middleware = RequestLoggingMiddleware(app=FastAPI())
        encoded_headers = [(k.encode(), v.encode()) for k, v in headers.items()]
        mock_scope = {"type": "http", "headers": encoded_headers, "client": ("testclient", 123)}
        mock_request = Request(mock_scope)
        assert middleware._get_client_ip(mock_request) == expected_ip


@pytest.mark.asyncio
class TestSecurityHeadersMiddleware:
    """Tests for the SecurityHeadersMiddleware."""

    @pytest.fixture
    def client(self):
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)
        app.add_route("/", success_endpoint)
        return TestClient(app)

    async def test_headers_are_added(self, client):
        """Test that security headers are added to every response."""
        response = client.get("/")
        headers = response.headers
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["X-Frame-Options"] == "DENY"


@pytest.mark.asyncio
class TestRateLimitMiddleware:
    """Tests for the RateLimitMiddleware."""

    @pytest.fixture
    def client(self):
        app = FastAPI()
        app.add_middleware(RateLimitMiddleware, max_requests=3, window_seconds=10)
        app.add_route("/", success_endpoint)
        return TestClient(app)

    async def test_rate_limiting_works(self, client):
        """Test that requests are rate-limited after exceeding the max."""
        for i in range(3):
            assert client.get("/").status_code == 200
        
        response = client.get("/")
        assert response.status_code == 429
        assert response.json()["error"] == "rate_limit_exceeded"


@pytest.mark.asyncio
class TestErrorHandlingMiddleware:
    """Tests for the ErrorHandlingMiddleware."""

    @pytest.fixture
    def client(self):
        app = FastAPI()
        async def add_request_id_middleware(request: Request, call_next):
            request.state.request_id = "test-error-id"
            response = await call_next(request)
            return response
            
        app.add_middleware(ErrorHandlingMiddleware)
        app.add_middleware(BaseHTTPMiddleware, dispatch=add_request_id_middleware)
        app.add_route("/error", exception_endpoint)
        return TestClient(app)

    @patch("app.api.middleware.logger")
    async def test_unhandled_exception_is_caught(self, mock_logger, client):
        """Test that an unhandled exception is caught and formatted."""
        response = client.get("/error")

        assert response.status_code == 500
        content = response.json()
        assert content["error"] == "internal_server_error"
        assert content["request_id"] == "test-error-id"
        mock_logger.error.assert_called_once()


@pytest.mark.asyncio
class TestDebugMiddleware:
    """Tests for the DebugMiddleware."""

    @pytest.fixture
    def client(self):
        app = FastAPI()
        app.add_middleware(DebugMiddleware)
        app.add_route("/", success_endpoint)
        return TestClient(app)

    @patch("app.api.middleware.logger")
    async def test_debug_logging(self, mock_logger, client):
        """Test that debug middleware logs request and response details robustly."""
        client.get("/?param=value")

        header_log_call = next((c.args[0] for c in mock_logger.debug.call_args_list if "REQUEST HEADERS" in c.args[0]), None)
        assert header_log_call is not None
        
        header_dict_str = header_log_call.split("REQUEST HEADERS: ")[1]
        header_dict = json.loads(header_dict_str.replace("'", '"'))
        
        assert header_dict['host'] == 'testserver'
        assert header_dict['user-agent'] == 'testclient'
        mock_logger.debug.assert_any_call("REQUEST QUERY: {'param': 'value'}")
        mock_logger.debug.assert_any_call("RESPONSE STATUS: 200")


@pytest.mark.asyncio
class TestSetupFunctions:
    """Tests for middleware setup functions."""

    def test_setup_cors_middleware(self, mock_settings):
        """Test the setup_cors_middleware function for different environments."""
        with patch.object(middleware_module, "settings", mock_settings):
            mock_settings.environment = "production"
            prod_app = FastAPI()
            setup_cors_middleware(prod_app, environment="production")
            prod_middleware = prod_app.user_middleware[0]
            assert prod_middleware.options["allow_origins"] == [mock_settings.webapp_url]

            mock_settings.environment = "development"
            dev_app = FastAPI()
            setup_cors_middleware(dev_app, environment="development")
            dev_middleware = dev_app.user_middleware[0]
            assert dev_middleware.options["allow_origins"] == ["*"]

    def test_setup_development_middleware(self, mock_settings):
        """Test that development middleware is added only when not in production."""
        with patch.object(middleware_module, "settings", mock_settings):
            # Should not add middleware in production
            mock_settings.is_production = True
            prod_app = FastAPI()
            setup_development_middleware(prod_app)
            assert len(prod_app.user_middleware) == 0

            # Should add middleware in development
            mock_settings.is_production = False
            dev_app = FastAPI()
            setup_development_middleware(dev_app)
            assert len(dev_app.user_middleware) == 1
            assert dev_app.user_middleware[0].cls == DebugMiddleware

    def test_setup_all_middleware_order(self, mock_settings):
        """Test that setup_all_middleware adds all middleware in the correct order."""
        with patch.object(middleware_module, "settings", mock_settings):
            app = FastAPI()
            setup_all_middleware(app)

            middleware_classes = [mw.cls for mw in app.user_middleware]
            
            # CORRECTED: The list is in reverse order of addition because
            # Starlette uses `insert(0, ...)` to add middleware.
            # The last one added is the first in the list.
            expected_order = [
                middleware_module.CORSMiddleware,
                RequestLoggingMiddleware,
                RateLimitMiddleware,
                SecurityHeadersMiddleware,
                ErrorHandlingMiddleware,
            ]
            
            assert middleware_classes == expected_order


@pytest.mark.asyncio
class TestUtilityFunctions:
    """Tests for the utility functions in the middleware module."""

    async def test_get_request_id(self):
        """Test get_request_id correctly retrieves ID from request state."""
        mock_request_with_id = MagicMock(spec=Request)
        mock_request_with_id.state = MagicMock()
        mock_request_with_id.state.request_id = "my-uuid"
        assert get_request_id(mock_request_with_id) == "my-uuid"

        mock_request_no_id = MagicMock(spec=Request)
        mock_request_no_id.state = MagicMock()
        del mock_request_no_id.state.request_id
        assert get_request_id(mock_request_no_id) == "unknown"
        
    async def test_add_audit_context(self):
        """Test add_audit_context builds the context dictionary correctly."""
        with patch("app.api.middleware.time.time", return_value=1005.5):
            mock_scope = {
                "type": "http",
                "method": "POST",
                "path": "/test/audit",
                "headers": {b"user-agent": b"auditor-agent"}.items(),
                "client": ("5.5.5.5", 123),
                "state": {"request_id": "audit-id", "start_time": 1000.0}
            }
            mock_request = Request(mock_scope)
            context = add_audit_context(mock_request, user_id="user-123")

            assert context["request_id"] == "audit-id"
            assert context["user_id"] == "user-123"
            assert context["method"] == "POST"
