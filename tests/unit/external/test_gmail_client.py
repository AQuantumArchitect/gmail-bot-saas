import pytest
from unittest.mock import patch, AsyncMock, Mock
from urllib.parse import quote
import httpx
import base64
from datetime import datetime, timedelta

# Import the client to be tested and the exceptions it might raise
from app.external.gmail_client import GmailClient
from app.core.exceptions import AuthenticationError, APIError, ValidationError

# Mock the settings object that the client depends on
from app.core import config
config.settings.google_client_id = "test_client_id"
config.settings.google_client_secret = "test_client_secret"
config.settings.redirect_uri = "http://localhost/callback"


@pytest.fixture
def gmail_client():
    """Provides a fresh instance of the GmailClient for each test."""
    return GmailClient()


class TestGmailClientOAuth:
    """Tests for the OAuth 2.0 flow methods of the GmailClient."""

    def test_get_oauth_url_success(self, gmail_client):
        """
        Tests that the OAuth URL is generated with the correct parameters.
        """
        state = "csrf-token-123"
        url = gmail_client.get_oauth_url(state=state)
        assert isinstance(url, str)
        assert gmail_client.OAUTH_URL in url
        assert f"client_id={gmail_client.client_id}" in url
        encoded_redirect_uri = quote(gmail_client.redirect_uri, safe='')
        assert f"redirect_uri={encoded_redirect_uri}" in url

    def test_get_oauth_url_requires_state(self, gmail_client):
        """
        Tests that generating an OAuth URL raises a ValidationError if state is missing.
        """
        with pytest.raises(ValidationError, match="State parameter is required"):
            gmail_client.get_oauth_url(state="")

    @pytest.mark.asyncio
    async def test_exchange_code_for_tokens_success(self, gmail_client):
        """
        Tests a successful exchange of an authorization code for API tokens.
        """
        with patch("app.external.gmail_client.httpx.AsyncClient") as mock_async_client:
            mock_response = Mock()
            mock_response.raise_for_status = Mock()
            mock_response.json.return_value = {
                "access_token": "test-access-token", "refresh_token": "test-refresh-token", "expires_in": 3599
            }
            mock_async_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
            tokens = await gmail_client.exchange_code_for_tokens(code="valid-auth-code")
            assert tokens["access_token"] == "test-access-token"
            mock_async_client.return_value.__aenter__.return_value.post.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_exchange_code_for_tokens_http_error(self, gmail_client):
        """
        Tests that an AuthenticationError is raised when the token exchange fails.
        """
        with patch("app.external.gmail_client.httpx.AsyncClient") as mock_async_client:
            mock_response = Mock()
            http_error = httpx.HTTPStatusError(
                "Bad Request", request=Mock(), response=httpx.Response(status_code=400, json={"error_description": "invalid_grant"})
            )
            mock_response.raise_for_status = Mock(side_effect=http_error)
            mock_async_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
            with pytest.raises(AuthenticationError, match="invalid_grant"):
                await gmail_client.exchange_code_for_tokens(code="invalid-auth-code")

    @pytest.mark.asyncio
    async def test_refresh_access_token_success(self, gmail_client):
        """
        Tests a successful refresh of an access token.
        """
        with patch("app.external.gmail_client.httpx.AsyncClient") as mock_async_client:
            mock_response = Mock()
            mock_response.raise_for_status = Mock()
            mock_response.json.return_value = {"access_token": "new-access-token", "expires_in": 3599}
            mock_async_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
            tokens = await gmail_client.refresh_access_token(refresh_token="valid-refresh-token")
            assert tokens["access_token"] == "new-access-token"

    @pytest.mark.asyncio
    async def test_refresh_access_token_failure(self, gmail_client):
        """
        Tests that an AuthenticationError is raised when the refresh token is invalid.
        """
        with patch("app.external.gmail_client.httpx.AsyncClient") as mock_async_client:
            mock_response = Mock()
            http_error = httpx.HTTPStatusError("Bad Request", request=Mock(), response=httpx.Response(status_code=400))
            mock_response.raise_for_status = Mock(side_effect=http_error)
            mock_async_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
            with pytest.raises(AuthenticationError, match="Invalid refresh token"):
                await gmail_client.refresh_access_token(refresh_token="invalid-refresh-token")

    @pytest.mark.asyncio
    async def test_get_user_info_success(self, gmail_client):
        """
        Tests successfully fetching user information with a valid access token.
        """
        with patch("app.external.gmail_client.httpx.AsyncClient") as mock_async_client:
            mock_response = Mock()
            mock_response.raise_for_status = Mock()
            mock_response.json.return_value = {"email": "test@example.com", "name": "Test User"}
            mock_async_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
            user_info = await gmail_client.get_user_info(access_token="valid-access-token")
            assert user_info["email"] == "test@example.com"
            mock_async_client.return_value.__aenter__.return_value.get.assert_awaited_once()


class TestGmailClientApiOps:
    """Tests for the Gmail API operation methods of the GmailClient."""

    @pytest.mark.asyncio
    async def test_fetch_messages_success(self, gmail_client):
        """
        Tests successfully fetching and parsing a list of emails.
        """
        # --- Arrange ---
        mock_list_response = Mock()
        mock_list_response.raise_for_status = Mock()
        mock_list_response.json.return_value = {"messages": [{"id": "msg1"}]}
        mock_detail_response = Mock()
        mock_detail_response.raise_for_status = Mock()
        mock_detail_response.json.return_value = {
            "id": "msg1", "threadId": "thread1", "payload": { "headers": [{"name": "Subject", "value": "Email 1"}], "body": {"data": base64.urlsafe_b64encode(b"Content 1").decode()} }
        }
        async def mock_get_side_effect(url, headers, params):
            return mock_detail_response if "msg1" in url else mock_list_response

        with patch("app.external.gmail_client.httpx.AsyncClient") as mock_async_client:
            mock_async_client.return_value.__aenter__.return_value.get = AsyncMock(side_effect=mock_get_side_effect)
            # --- Act ---
            messages = await gmail_client.fetch_messages(access_token="valid-token")
            # --- Assert ---
            assert len(messages) == 1
            assert messages[0]["subject"] == "Email 1"
            assert mock_async_client.return_value.__aenter__.return_value.get.call_count == 2

    @pytest.mark.asyncio
    async def test_send_message_success(self, gmail_client):
        """
        Tests successfully sending a message.
        """
        with patch("app.external.gmail_client.httpx.AsyncClient") as mock_async_client:
            mock_response = Mock()
            mock_response.raise_for_status = Mock()
            mock_response.json.return_value = {"id": "sent_msg_123", "threadId": "thread_abc"}
            mock_async_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
            
            message_data = {"to": "recipient@example.com", "subject": "Hello", "body": "World"}
            result = await gmail_client.send_message("valid-token", message_data)

            assert result["id"] == "sent_msg_123"
            post_call = mock_async_client.return_value.__aenter__.return_value.post
            post_call.assert_awaited_once()
            # Check that the raw payload was correctly base64 encoded
            sent_payload = post_call.call_args.kwargs['json']['raw']
            assert isinstance(sent_payload, str)

    def test_parse_message_helper(self, gmail_client):
        """
        Unit tests the internal _parse_message helper function directly.
        """
        raw_message = {
            "id": "test_id", "threadId": "test_thread", "snippet": "Test Snippet",
            "payload": {
                "headers": [{"name": "Subject", "value": "Test Subject"}, {"name": "From", "value": "sender@example.com"}],
                "body": {"data": base64.urlsafe_b64encode(b"This is the email body.").decode()}
            }
        }
        parsed_message = gmail_client._parse_message(raw_message)
        assert parsed_message["subject"] == "Test Subject"
        assert parsed_message["content"] == "This is the email body."


class TestGmailClientInternalState:
    """Tests for the internal state logic like the circuit breaker."""

    def test_circuit_breaker_opens_on_failures(self, gmail_client):
        """
        Tests that the circuit breaker state changes to 'open' after 5 consecutive failures.
        """
        # --- Act ---
        for _ in range(5):
            gmail_client._record_failure()

        # --- Assert ---
        assert gmail_client._circuit_breaker["state"] == "open"
        assert gmail_client._check_circuit_breaker() is False

    def test_circuit_breaker_closes_on_success(self, gmail_client):
        """
        Tests that the circuit breaker state resets to 'closed' after a success.
        """
        # --- Arrange ---
        for _ in range(5):
            gmail_client._record_failure() # Open the circuit
        assert gmail_client._circuit_breaker["state"] == "open"

        # --- Act ---
        gmail_client._record_success()

        # --- Assert ---
        assert gmail_client._circuit_breaker["state"] == "closed"
        assert gmail_client._circuit_breaker["failure_count"] == 0
    
    def test_circuit_breaker_moves_to_half_open(self, gmail_client):
        """
        Tests that an 'open' circuit moves to 'half-open' after the timeout.
        """
        # --- Arrange ---
        # 1. Open the circuit
        for _ in range(5):
            gmail_client._record_failure()
        
        # 2. Use patch to simulate time passing (6 minutes into the future)
        future_time = datetime.utcnow() + timedelta(minutes=6)
        with patch("app.external.gmail_client.datetime") as mock_datetime:
            mock_datetime.utcnow.return_value = future_time
            
            # --- Act ---
            # check_circuit_breaker should see that enough time has passed
            can_request = gmail_client._check_circuit_breaker()

            # --- Assert ---
            assert gmail_client._circuit_breaker["state"] == "half-open"
            assert can_request is True # It should allow one request in half-open state