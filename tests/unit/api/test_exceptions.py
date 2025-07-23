import pytest
import json
from unittest.mock import Mock

from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

# Import the custom exceptions and their handlers
from app.core.exceptions import (
    ValidationError,
    NotFoundError,
    InsufficientCreditsError,
    AuthenticationError,
    RateLimitError,
    APIError,
)
from app.api.exceptions import (
    validation_error_handler,
    not_found_error_handler,
    insufficient_credits_error_handler,
    authentication_error_handler,
    rate_limit_error_handler,
    api_error_handler,
    generic_exception_handler,
    request_validation_error_handler,
    http_exception_handler,
)


@pytest.fixture
def mock_request():
    """Creates a mock FastAPI Request object for testing handlers."""
    request = Mock()
    request.method = "POST"
    request.url.path = "/api/test/endpoint"
    # Mock the request state to simulate having a request_id
    request.state.request_id = "test-request-id-123"
    return request


@pytest.mark.asyncio
class TestAppExceptionHandlers:
    """
    Tests for the custom exception handlers that map application
    errors to standardized JSON API responses.
    """

    async def test_validation_error_handler(self, mock_request):
        """
        Tests that the ValidationError handler returns a 422 status code
        with a correctly formatted JSON response.
        """
        # --- Arrange ---
        error_message = "Invalid input provided for field: email"
        exc = ValidationError(error_message)

        # --- Act ---
        response = await validation_error_handler(mock_request, exc)

        # --- Assert ---
        assert isinstance(response, JSONResponse)
        assert response.status_code == 422

        response_body = json.loads(response.body.decode())
        assert response_body["status_code"] == 422
        assert response_body["error"] == "validation_error"
        assert response_body["message"] == error_message
        assert response_body["request_id"] == "test-request-id-123"

    async def test_not_found_error_handler(self, mock_request):
        """
        Tests that the NotFoundError handler returns a 404 status code
        with a correctly formatted JSON response.
        """
        # --- Arrange ---
        error_message = "User with ID 'user-123' not found."
        exc = NotFoundError(error_message)

        # --- Act ---
        response = await not_found_error_handler(mock_request, exc)

        # --- Assert ---
        assert isinstance(response, JSONResponse)
        assert response.status_code == 404

        response_body = json.loads(response.body.decode())
        assert response_body["status_code"] == 404
        assert response_body["error"] == "not_found"
        assert response_body["message"] == error_message
        assert response_body["details"]["path"] == "/api/test/endpoint"

    @pytest.mark.parametrize(
        "handler_func, exception_class, expected_status, expected_error_code",
        [
            (insufficient_credits_error_handler, InsufficientCreditsError, 402, "insufficient_credits"),
            (authentication_error_handler, AuthenticationError, 401, "authentication_error"),
            (rate_limit_error_handler, RateLimitError, 429, "rate_limit_exceeded"),
            (api_error_handler, APIError, 503, "service_unavailable"),
            (generic_exception_handler, Exception, 500, "internal_server_error"),
        ],
    )
    async def test_core_error_handlers(
        self, mock_request, handler_func, exception_class, expected_status, expected_error_code
    ):
        """
        Tests multiple core exception handlers for correct status code and error format.
        """
        # --- Arrange ---
        error_message = f"A test {exception_class.__name__} occurred"
        expected_message = (
            "An unexpected error occurred"
            if exception_class is Exception
            else error_message
        )
        exc = exception_class(error_message)

        # --- Act ---
        response = await handler_func(mock_request, exc)

        # --- Assert ---
        assert response.status_code == expected_status
        response_body = json.loads(response.body.decode())
        assert response_body["error"] == expected_error_code
        assert response_body["message"] == expected_message

    async def test_insufficient_credits_handler_with_details(self, mock_request):
        """
        Tests that the insufficient credits handler includes extra details if present.
        """
        # --- Arrange ---
        exc = InsufficientCreditsError("Not enough credits")
        exc.balance = 10
        exc.requested = 20

        # --- Act ---
        response = await insufficient_credits_error_handler(mock_request, exc)

        # --- Assert ---
        assert response.status_code == 402
        response_body = json.loads(response.body.decode())
        details = response_body.get("details", {})
        assert details.get("current_balance") == 10
        assert details.get("credits_requested") == 20

    async def test_authentication_error_handler_headers(self, mock_request):
        """
        Tests that the authentication error handler includes the WWW-Authenticate header.
        """
        # --- Arrange ---
        exc = AuthenticationError("Invalid token")

        # --- Act ---
        response = await authentication_error_handler(mock_request, exc)

        # --- Assert ---
        assert response.status_code == 401
        assert response.headers.get("WWW-Authenticate") == "Bearer"


@pytest.mark.asyncio
class TestFastAPIExceptionHandlers:
    """
    Tests handlers for FastAPI's built-in exceptions to ensure they are
    intercepted and formatted into the standard API error response.
    """

    async def test_request_validation_error_handler(self, mock_request):
        """
        Tests that Pydantic validation errors from FastAPI are formatted correctly.
        """
        # --- Arrange ---
        # Create a sample list of errors that RequestValidationError expects
        raw_errors = [
            {
                "loc": ("body", "email"),
                "msg": "value is not a valid email address",
                "type": "value_error",
                "input": "not-an-email"
            }
        ]
        exc = RequestValidationError(errors=raw_errors)

        # --- Act ---
        response = await request_validation_error_handler(mock_request, exc)

        # --- Assert ---
        assert response.status_code == 422
        response_body = json.loads(response.body.decode())

        assert response_body["error"] == "request_validation_error"
        assert response_body["message"] == "Request validation failed"
        
        details = response_body.get("details", {})
        validation_errors = details.get("validation_errors", [])
        assert len(validation_errors) == 1
        assert validation_errors[0]["field"] == "body.email"
        assert "not a valid email" in validation_errors[0]["message"]

    async def test_http_exception_handler(self, mock_request):
        """
        Tests that a standard FastAPI HTTPException is correctly formatted.
        """
        # --- Arrange ---
        exc = HTTPException(
            status_code=403,
            detail="You do not have permission to access this resource."
        )

        # --- Act ---
        response = await http_exception_handler(mock_request, exc)

        # --- Assert ---
        assert response.status_code == 403
        response_body = json.loads(response.body.decode())
        
        assert response_body["error"] == "forbidden"
        assert response_body["message"] == "You do not have permission to access this resource."