import pytest
from uuid import uuid4
from unittest.mock import AsyncMock, Mock

from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

# Import functions and classes to test
from app.api.dependencies import (
    UserContext,
    get_auth_token,
    get_current_user,
    get_user_context,
    get_optional_user_context,
    get_request_context,
    require_email_processing_permission,
    require_dashboard_access,
    require_gmail_connection_permission,
    require_credit_purchase_permission,
    require_admin_access,
    validate_user_ownership,
    check_rate_limit,
    get_error_response
)
from app.core.exceptions import AuthenticationError, ValidationError, NotFoundError

# Because the dependencies file has global services, we patch them during tests
from app.api import dependencies as dependencies_to_mock


@pytest.fixture
def sample_user_data():
    """Provides a sample dictionary of user data for creating a context."""
    return {
        "user_id": str(uuid4()),
        "email": "user@example.com",
        "display_name": "Test User",
        "credits_remaining": 50,
        "bot_enabled": True,
        "timezone": "UTC",
        "created_at": "2025-01-01T00:00:00"
    }

# #################################################################
# ## Tests for Token Extraction
# #################################################################

@pytest.mark.asyncio
class TestGetAuthToken:
    """Tests the get_auth_token dependency for extracting a bearer token."""

    async def test_get_auth_token_success(self):
        """
        Tests successful extraction of the token string from credentials.
        """
        # --- Arrange ---
        token = "a-valid-jwt-token"
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

        # --- Act ---
        extracted_token = await get_auth_token(credentials=credentials)

        # --- Assert ---
        assert extracted_token == token

    async def test_get_auth_token_no_credentials(self):
        """
        Tests that a 401 HTTPException is raised when no credentials are provided.
        """
        # --- Act & Assert ---
        with pytest.raises(HTTPException) as exc_info:
            await get_auth_token(credentials=None)
        
        assert exc_info.value.status_code == 401
        assert "authorization header required" in exc_info.value.detail.lower()


# #################################################################
# ## Tests for Core Authentication & Context Dependencies
# #################################################################

@pytest.mark.asyncio
class TestAuthenticationAndContext:
    """Tests core authentication and user context creation."""

    async def test_get_current_user_success(self, sample_user_data):
        """
        Tests that get_current_user returns a user profile from the auth_service.
        """
        # --- Arrange ---
        dependencies_to_mock.auth_service.get_current_user = AsyncMock(return_value=sample_user_data)
        valid_token = "a-valid-jwt-token"

        # --- Act ---
        result_user = await get_current_user(token=valid_token)

        # --- Assert ---
        assert result_user == sample_user_data
        dependencies_to_mock.auth_service.get_current_user.assert_awaited_once_with(valid_token)

    async def test_get_current_user_auth_error(self):
        """
        Tests that get_current_user raises a 401 HTTPException on AuthenticationError.
        """
        # --- Arrange ---
        auth_error = AuthenticationError("Token has expired")
        dependencies_to_mock.auth_service.get_current_user = AsyncMock(side_effect=auth_error)
        invalid_token = "an-invalid-jwt-token"

        # --- Act & Assert ---
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(token=invalid_token)

        assert exc_info.value.status_code == 401
        assert "token has expired" in exc_info.value.detail.lower()

    async def test_get_user_context_success(self, sample_user_data):
        """
        Tests that get_user_context correctly builds a UserContext object.
        """
        # --- Arrange ---
        dependencies_to_mock.get_current_user = AsyncMock(return_value=sample_user_data)
        
        def permission_checker(user_data, action):
            if action == "email_processing":
                return {"allowed": True}
            return {"allowed": False}

        dependencies_to_mock.auth_service.check_user_permissions = Mock(side_effect=permission_checker)

        # --- Act ---
        user_data = await dependencies_to_mock.get_current_user()
        result_context = await get_user_context(user_data=user_data)

        # --- Assert ---
        assert isinstance(result_context, UserContext)
        assert result_context.user_id == sample_user_data["user_id"]
        assert result_context.email == sample_user_data["email"]
        assert result_context.can_process_emails is True
        assert result_context.can_purchase_credits is False

    async def test_get_request_context_success(self, sample_user_data):
        """
        Tests that get_request_context correctly extracts data from the request.
        """
        # --- Arrange ---
        context = UserContext(sample_user_data, permissions={})

        # Create a mock Request object with necessary attributes
        mock_request = Mock()
        mock_request.method = "POST"
        mock_request.url = "http://test.com/api/some/path"
        mock_request.client.host = "127.0.0.1"
        mock_request.headers = {"user-agent": "pytest-client"}

        # --- Act ---
        result = await get_request_context(request=mock_request, context=context)

        # --- Assert ---
        assert result["user_id"] == context.user_id
        assert result["method"] == "POST"
        assert result["url"] == "http://test.com/api/some/path"
        assert result["client_ip"] == "127.0.0.1"
        assert result["user_agent"] == "pytest-client"


# #################################################################
# ## Tests for Optional Authentication
# #################################################################

@pytest.mark.asyncio
class TestOptionalAuthentication:
    """Tests the get_optional_user_context dependency."""

    async def test_get_optional_user_context_with_token(self, sample_user_data):
        """
        Tests that a UserContext is returned when a valid token is provided.
        """
        # --- Arrange ---
        token = "a-valid-jwt-token"
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        dependencies_to_mock.auth_service.get_current_user = AsyncMock(return_value=sample_user_data)
        dependencies_to_mock.auth_service.check_user_permissions = Mock(return_value={"allowed": True})

        # --- Act ---
        result = await get_optional_user_context(credentials=credentials)

        # --- Assert ---
        assert isinstance(result, UserContext)
        assert result.user_id == sample_user_data["user_id"]
        dependencies_to_mock.auth_service.get_current_user.assert_awaited_once_with(token)

    async def test_get_optional_user_context_no_token(self):
        """
        Tests that None is returned when no credentials are provided.
        """
        # --- Act ---
        result = await get_optional_user_context(credentials=None)

        # --- Assert ---
        assert result is None

    async def test_get_optional_user_context_invalid_token(self):
        """
        Tests that None is returned when an invalid token is provided.
        """
        # --- Arrange ---
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="invalid-token")
        dependencies_to_mock.auth_service.get_current_user = AsyncMock(side_effect=AuthenticationError)

        # --- Act ---
        result = await get_optional_user_context(credentials=credentials)

        # --- Assert ---
        assert result is None


# #################################################################
# ## Tests for Permission & Validation Dependencies
# #################################################################

@pytest.mark.asyncio
class TestPermissionDependencies:
    """Tests dependencies that check for specific user permissions."""

    async def test_require_email_processing_permission_no_credits(self, sample_user_data):
        """
        Tests that a 402 Payment Required error is raised for insufficient credits.
        """
        # --- Arrange ---
        sample_user_data["credits_remaining"] = 0
        permissions = {"can_process_emails": False}
        no_credits_context = UserContext(sample_user_data, permissions)
        dependencies_to_mock.get_user_context = AsyncMock(return_value=no_credits_context)

        # --- Act & Assert ---
        with pytest.raises(HTTPException) as exc_info:
            mock_context = await dependencies_to_mock.get_user_context()
            await require_email_processing_permission(context=mock_context)

        assert exc_info.value.status_code == 402
        assert "insufficient credits" in exc_info.value.detail.lower()

    @pytest.mark.parametrize(
        "dependency_func, permission_key",
        [
            (require_dashboard_access, "can_access_dashboard"),
            (require_gmail_connection_permission, "can_connect_gmail"),
            (require_credit_purchase_permission, "can_purchase_credits"),
        ]
    )
    async def test_simple_permission_dependencies(self, sample_user_data, dependency_func, permission_key):
        """
        Tests simple permission dependencies that should always pass for authenticated users.
        """
        # --- Test Success Path ---
        permissions = {permission_key: True}
        valid_context = UserContext(sample_user_data, permissions)
        result = await dependency_func(context=valid_context)
        assert result is valid_context

        # --- Test Failure Path ---
        permissions = {permission_key: False}
        invalid_context = UserContext(sample_user_data, permissions)
        with pytest.raises(HTTPException) as exc_info:
            await dependency_func(context=invalid_context)
        assert exc_info.value.status_code == 403

    async def test_validate_user_ownership_failure(self, sample_user_data):
        """
        Tests that validate_user_ownership raises a 403 HTTPException on user ID mismatch.
        """
        # --- Arrange ---
        context = UserContext(sample_user_data, permissions={})
        different_user_id = str(uuid4())

        # --- Act & Assert ---
        with pytest.raises(HTTPException) as exc_info:
            await validate_user_ownership(user_id=different_user_id, context=context)

        assert exc_info.value.status_code == 403
        assert "access denied" in exc_info.value.detail.lower()
    
    async def test_require_admin_access_failure(self):
        """
        Tests that the admin check fails for a context without a user_id (placeholder logic).
        """
        # --- Arrange ---
        no_user_context = UserContext(user_data={"user_id": None}, permissions={})

        # --- Act & Assert ---
        with pytest.raises(HTTPException) as exc_info:
            await require_admin_access(context=no_user_context)
        
        assert exc_info.value.status_code == 403

# #################################################################
# ## Tests for Rate Limiting Dependencies
# #################################################################

@pytest.mark.asyncio
class TestRateLimiting:
    """Tests the check_rate_limit dependency."""

    async def test_check_rate_limit_exceeded(self, sample_user_data):
        """
        Tests that a 429 HTTPException is raised when the rate limit is exceeded.
        """
        # --- Arrange ---
        context = UserContext(sample_user_data, permissions={})
        mock_request = Mock()
        mock_request.client.host = "127.0.0.1"
        
        rate_limit_response = {
            "allowed": False,
            "remaining": 0,
            "reset_time": "2025-07-18T12:30:00Z"
        }
        dependencies_to_mock.auth_service.check_rate_limit = Mock(
            return_value=rate_limit_response
        )

        # --- Act & Assert ---
        with pytest.raises(HTTPException) as exc_info:
            await check_rate_limit(request=mock_request, context=context)
        
        assert exc_info.value.status_code == 429
        assert "rate limit exceeded" in exc_info.value.detail.lower()
        assert exc_info.value.headers["X-RateLimit-Remaining"] == "0"


# #################################################################
# ## Tests for Utility Functions
# #################################################################

class TestUtilityFunctions:
    """Tests utility functions like get_error_response."""

    @pytest.mark.parametrize(
        "error_instance, expected_status, expected_error_key",
        [
            (ValidationError("Bad input"), 422, "validation_error"),
            (NotFoundError("Item not found"), 404, "not_found"),
            (AuthenticationError("Invalid token"), 401, "authentication_error"),
            (ValueError("A generic error"), 500, "internal_error"),
        ]
    )
    def test_get_error_response(self, error_instance, expected_status, expected_error_key):
        """
        Tests that get_error_response correctly converts exceptions to dicts.
        """
        # --- Act ---
        response = get_error_response(error_instance)

        # --- Assert ---
        assert response["status_code"] == expected_status
        assert response["error"] == expected_error_key
        assert isinstance(response["message"], str)