# tests/external/test_anthropic_client.py
"""
Unit tests for the Anthropic AI Client.
"""
import pytest
import httpx
import time
from unittest.mock import patch, AsyncMock, MagicMock

# The client we are testing
from app.external.anthropic_client import AnthropicClient
# The module where settings are imported, so we can patch them
from app.external import anthropic_client as client_module
# Exceptions the client is expected to handle or raise
from app.core.exceptions import ValidationError, APIError, AuthenticationError


@pytest.fixture
def mock_settings():
    """Fixture to provide a mock settings object for the client."""
    settings = MagicMock()
    settings.anthropic_api_key = "sk_test_12345"
    return settings


@pytest.fixture
def client(mock_settings):
    """Fixture to create an instance of the AnthropicClient with mocked settings."""
    # Patch the settings object within the client's module before instantiation
    with patch.object(client_module, "settings", mock_settings):
        yield AnthropicClient()


@pytest.mark.asyncio
class TestGenerateEmailSummary:
    """Tests for the generate_email_summary method."""

    @pytest.fixture
    def sample_api_response(self):
        """A sample raw response from the mocked Anthropic API."""
        return {
            "content": [{
                "type": "text",
                "text": """{
                    "summary": "This is a test summary.",
                    "key_points": ["Point 1", "Point 2"],
                    "action_items": ["Action 1"],
                    "urgency_level": "medium",
                    "sentiment": "neutral",
                    "category": "work",
                    "confidence_score": 0.95
                }"""
            }],
            "usage": {"total_tokens": 150},
            "model": "claude-3-haiku-20240307",
        }

    async def test_generate_summary_success(self, client, sample_api_response):
        """
        Test the successful generation and parsing of an email summary.
        """
        # --- Arrange ---
        with patch.object(client, "_make_completion_request", new=AsyncMock()) as mock_request:
            mock_request.return_value = sample_api_response
            email_content = "Hello team, please review the attached Q3 report."
            email_metadata = {"subject": "Q3 Report Review"}

            # --- Act ---
            result = await client.generate_email_summary(email_content, email_metadata)

            # --- Assert ---
            mock_request.assert_awaited_once()
            assert result["summary"] == "This is a test summary."
            assert result["tokens_used"] == 150

    async def test_generate_summary_with_empty_content_raises_error(self, client):
        """
        Test that providing empty email content raises a ValidationError.
        """
        with pytest.raises(ValidationError, match="Email content cannot be empty"):
            await client.generate_email_summary(email_content="  ")

    async def test_summary_parsing_fallback_for_non_json(self, client):
        """
        Test that the client gracefully handles a non-JSON response from the API.
        """
        non_json_response = {
            "content": [{"type": "text", "text": "Just a plain text summary."}],
            "usage": {"total_tokens": 50}, "model": "claude-3-haiku-20240307",
        }
        with patch.object(client, "_make_completion_request", new=AsyncMock()) as mock_request:
            mock_request.return_value = non_json_response
            result = await client.generate_email_summary(email_content="Some content")
            assert result["summary"] == "Just a plain text summary."
            assert result["confidence_score"] < 0.9


class TestCoreClientLogic:
    """Tests for the client's internal helper methods and logic."""

    def test_create_summary_prompt(self, client):
        """Test that the summary prompt is created with the correct structure."""
        # FIXED: Added all required keys to the test data
        email_data = {
            "subject": "Meeting", "sender": "boss@work.com", "recipient": "me@work.com", "date": "today",
            "content": "Let's meet at 3pm."
        }
        prompt = client._create_summary_prompt(email_data, style="bullet_points", max_length=50)
        assert "Subject: Meeting" in prompt
        assert "From: boss@work.com" in prompt
        assert "JSON format" in prompt

    def test_calculate_cost(self, client):
        """Test that the cost calculation is correct based on the model."""
        cost_haiku = client._calculate_cost(10000, "claude-3-haiku")
        assert cost_haiku == pytest.approx(0.0025)
        cost_opus = client._calculate_cost(10000, "claude-3-opus")
        assert cost_opus == pytest.approx(0.15)


@pytest.mark.asyncio
class TestApiRequestHandling:
    """Tests for the core _make_completion_request method and its error handling."""

    @patch("httpx.AsyncClient")
    async def test_make_request_success(self, MockAsyncClient, client):
        """Test a successful API call, including cost and usage tracking."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value={"usage": {"input_tokens": 100, "output_tokens": 50}})
        
        mock_client_instance = AsyncMock()
        mock_client_instance.post.return_value = mock_response
        MockAsyncClient.return_value.__aenter__.return_value = mock_client_instance

        response_data = await client._make_completion_request(prompt="test prompt")
        
        assert "cost_usd" in response_data
        assert client.get_usage_stats()["total_tokens"] == 150

    @patch("httpx.AsyncClient")
    async def test_make_request_handles_401_auth_error(self, MockAsyncClient, client):
        """Test that a 401 Unauthorized response raises an AuthenticationError."""
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.request = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError("Unauthorized", request=mock_response.request, response=mock_response)
        
        mock_client_instance = AsyncMock()
        mock_client_instance.post.return_value = mock_response
        MockAsyncClient.return_value.__aenter__.return_value = mock_client_instance

        with pytest.raises(AuthenticationError, match="Invalid Anthropic API key"):
            await client._make_completion_request(prompt="test")

    @patch("httpx.AsyncClient")
    async def test_make_request_handles_network_error(self, MockAsyncClient, client):
        """Test that a network-level error raises an APIError."""
        mock_client_instance = AsyncMock()
        mock_client_instance.post.side_effect = httpx.RequestError("Network timeout")
        MockAsyncClient.return_value.__aenter__.return_value = mock_client_instance

        with pytest.raises(APIError, match="Network error: Network timeout"):
            await client._make_completion_request(prompt="test")


@pytest.mark.asyncio
class TestBatchProcessing:
    """Tests for the process_email_batch method."""

    async def test_process_email_batch_success(self, client):
        """Test that a batch of emails is processed concurrently."""
        emails_to_process = [{"content": "Email 1"}, {"content": "Email 2"}]
        with patch.object(client, "generate_email_summary", new=AsyncMock()) as mock_summary:
            mock_summary.return_value = {"summary": "A summary"}
            results = await client.process_email_batch(emails_to_process)
            assert mock_summary.call_count == 2
            assert len(results) == 2

    async def test_process_email_batch_handles_exceptions(self, client):
        """Test that the batch processor handles individual failures gracefully."""
        emails_to_process = [{"id": 1, "content": "Success"}, {"id": 2, "content": "Fail"}]
        with patch.object(client, "generate_email_summary", new=AsyncMock()) as mock_summary:
            mock_summary.side_effect = [{"summary": "Success"}, APIError("Processing failed")]
            results = await client.process_email_batch(emails_to_process)
            assert len(results) == 2
            assert "summary" in results[0]
            assert "error" in results[1]


@pytest.mark.asyncio
class TestCircuitBreaker:
    """Tests for the client's internal circuit breaker logic."""

    async def test_circuit_breaker_opens_after_failures(self, client):
        """Test that the circuit breaker opens after 3 consecutive failures."""
        # --- Arrange ---
        # FIXED: Mock the HTTP client's `post` method to raise the error,
        # ensuring the try/except block in the implementation is triggered.
        with patch("httpx.AsyncClient") as MockAsyncClient:
            mock_client_instance = AsyncMock()
            mock_client_instance.post.side_effect = httpx.RequestError("Connection failed")
            MockAsyncClient.return_value.__aenter__.return_value = mock_client_instance

            # --- Act & Assert ---
            # First 3 calls should fail, be caught, and increment the counter
            for _ in range(3):
                with pytest.raises(APIError):
                    await client._make_completion_request(prompt="test")
            
            # Now the state should be 'open'
            assert client._circuit_breaker["state"] == "open"

            # The 4th call should fail immediately because the circuit is open
            with pytest.raises(APIError, match="Circuit breaker is open"):
                await client._make_completion_request(prompt="test")

    async def test_circuit_breaker_closes_after_success(self, client):
        """Test that a successful call closes the circuit breaker."""
        # --- Arrange ---
        client._circuit_breaker["state"] = "half-open"
        client._circuit_breaker["failure_count"] = 2
        
        with patch("httpx.AsyncClient") as MockAsyncClient:
            mock_response = MagicMock(status_code=200, json=MagicMock(return_value={"usage": {}}))
            mock_client_instance = AsyncMock()
            mock_client_instance.post.return_value = mock_response
            MockAsyncClient.return_value.__aenter__.return_value = mock_client_instance

            # --- Act ---
            await client._make_completion_request(prompt="test")

            # --- Assert ---
            assert client._circuit_breaker["state"] == "closed"
            assert client._circuit_breaker["failure_count"] == 0


@pytest.mark.asyncio
class TestContentAnalysis:
    """Tests for the analyze_email_content method."""

    async def test_analyze_content_success(self, client):
        """Test successful content analysis."""
        # --- Arrange ---
        api_response = {
            "content": [{"text": '{"sentiment": {"label": "positive"}}'}],
            "usage": {"total_tokens": 100}
        }
        with patch.object(client, "_make_completion_request", new=AsyncMock()) as mock_request:
            mock_request.return_value = api_response
            
            # --- Act ---
            result = await client.analyze_email_content("This is great news!")

            # --- Assert ---
            mock_request.assert_awaited_once()
            assert result["sentiment"]["label"] == "positive"
            assert result["tokens_used"] == 100

    async def test_analyze_content_with_empty_content_raises_error(self, client):
        """Test that empty content raises a ValidationError."""
        with pytest.raises(ValidationError, match="Email content cannot be empty"):
            await client.analyze_email_content(email_content="")


class TestUtilityMethods:
    """Tests for the client's various helper and utility methods."""

    def test_get_usage_stats(self, client):
        """Test that usage stats are reported correctly."""
        # Simulate some usage
        client._total_tokens = 5000
        client._total_cost = 0.0125
        
        stats = client.get_usage_stats()
        
        assert stats["total_tokens"] == 5000
        assert stats["total_cost_usd"] == 0.0125
        assert "claude-3-haiku" in stats["available_models"]

    def test_estimate_cost(self, client):
        """Test the cost estimation logic."""
        # Approx 25 tokens for Haiku model
        estimation = client.estimate_cost("This is a test sentence of exactly one hundred characters to test the simple token estimation logic!!", model="claude-3-haiku")
        
        assert estimation["estimated_tokens"] == 25
        assert estimation["estimated_cost_usd"] == pytest.approx(25 * 0.00000025)

    def test_validate_text_length(self, client):
        """Test the text length validation logic."""
        short_text = "This is short."
        # A very long string to just barely fit
        long_text_just_fits = "a" * (200000 * 4) 
        # A very long string to exceed the context length
        long_text_too_long = "a" * (200000 * 4 + 4) # Ensure token estimate is > max_tokens

        valid_result = client.validate_text_length(short_text, model="claude-3-haiku")
        assert valid_result["valid"] is True
        
        # Test the edge case where it just fits
        just_fits_result = client.validate_text_length(long_text_just_fits, model="claude-3-haiku")
        assert just_fits_result["valid"] is True

        # Test the case where it's just over the limit
        invalid_result = client.validate_text_length(long_text_too_long, model="claude-3-haiku")
        assert invalid_result["valid"] is False
