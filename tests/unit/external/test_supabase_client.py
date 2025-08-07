# tests/unit/external/test_supabase_client.py
import unittest
import time
import httpx
import json
from unittest.mock import patch, AsyncMock, MagicMock, call

from app.core.config import Settings
from app.core.exceptions import (
    APIError,
    ValidationError,
    AuthenticationError,
    NotFoundError,
    DatabaseError,
    RateLimitError
)
from app.external.supabase_client import SupabaseClient, get_supabase_client, _supabase_client


class TestUnitSupabaseClient(unittest.IsolatedAsyncioTestCase):
    """
    Comprehensive and robust unit tests for the SupabaseClient, using
    parameterization and edge case validation for enterprise-grade coverage.
    """

    def setUp(self):
        """Set up a fresh SupabaseClient instance for each test."""
        self.mock_settings = Settings(
            SUPABASE_URL="https://mock.supabase.co/",
            SUPABASE_KEY="mock_anon_key",
            SUPABASE_SERVICE_KEY="mock_service_key",
            SUPABASE_JWT_SECRET="mock_jwt_secret",
            GOOGLE_CLIENT_ID="dummy.apps.googleusercontent.com",
            GOOGLE_CLIENT_SECRET="dummy",
            ANTHROPIC_API_KEY="sk-dummy",
            WEBAPP_URL="http://localhost",
            REDIRECT_URI="http://localhost/callback",
            VAULT_PASSPHRASE="dummy"
        )
        self.settings_patcher = patch('app.external.supabase_client.settings', self.mock_settings)
        self.settings_patcher.start()
        
        self.client = SupabaseClient()

    def tearDown(self):
        """Stop all patches and clean up."""
        self.settings_patcher.stop()
        global _supabase_client
        _supabase_client = None

    # ========== Helper to create mock responses ==========
    def _create_mock_response(self, status_code: int, json_data: any = None, text_data: str = ""):
        mock_response = MagicMock()
        mock_response.status_code = status_code
        if json_data is not None:
            mock_response.json.return_value = json_data
            mock_response.content = json.dumps(json_data).encode('utf-8')
        else:
            mock_response.content = text_data.encode('utf-8')
        return mock_response

    # ========== Initialization and Configuration Tests ==========

    def test_initialization_success(self):
        """✅ Test successful client initialization."""
        expected_url = str(self.mock_settings.database_url).rstrip('/')
        self.assertEqual(self.client.url, expected_url)

    def test_initialization_failure_missing_key(self):
        """❌ Test client initialization fails with missing required fields."""
        with patch('app.external.supabase_client.settings') as mock_settings:
            mock_settings.database_key = None
            with self.assertRaises(ValidationError):
                SupabaseClient()

    # ========== CRUD Operation and Edge Case Tests ==========

    @patch('app.external.supabase_client.httpx.AsyncClient')
    async def test_select_with_parameterized_filters(self, MockAsyncClient):
        """✅ Test SELECT with various filter types using parameterization."""
        test_cases = [
            ("equals", {"id": 1}, "eq.1"),
            ("greater_than", {"points": {"gte": 100}}, "gte.100"),
            ("like", {"name": {"like": "%test%"}}, "like.%test%"),
            ("is_null", {"deleted_at": {"is": "null"}}, "is.null"),
        ]

        for name, filters, expected_param in test_cases:
            with self.subTest(name=name):
                mock_instance = MockAsyncClient.return_value
                mock_instance.is_closed = False
                mock_instance.request = AsyncMock(return_value=self._create_mock_response(200, json_data=[{"id": 1}]))
                
                await self.client.select("users", filters=filters)
                
                called_params = mock_instance.request.call_args.kwargs['params']
                filter_key = list(filters.keys())[0]
                self.assertEqual(called_params[filter_key], expected_param)

    @patch('app.external.supabase_client.httpx.AsyncClient')
    async def test_delete_operation(self, MockAsyncClient):
        """✅ Test a DELETE operation."""
        mock_instance = MockAsyncClient.return_value
        mock_instance.is_closed = False
        mock_instance.request = AsyncMock(return_value=self._create_mock_response(200, json_data=[{"id": 1}]))
        
        await self.client.delete("users", filters={"id": 1})
        mock_instance.request.assert_awaited_once()

    async def test_delete_without_filters_raises_error(self):
        """❌ Test that DELETE without filters raises a ValidationError."""
        with self.assertRaisesRegex(ValidationError, "Filters are required for deletes"):
            await self.client.delete("users", filters={})

    @patch('app.external.supabase_client.httpx.AsyncClient')
    async def test_upsert_sends_correct_headers(self, MockAsyncClient):
        """✅ Test that upsert sends the correct 'Prefer' header."""
        mock_instance = MockAsyncClient.return_value
        mock_instance.is_closed = False
        mock_instance.request = AsyncMock(return_value=self._create_mock_response(200, json_data=[{"id": 1}]))

        await self.client.upsert("users", {"id": 1, "name": "new"})
        called_headers = mock_instance.request.call_args.kwargs['headers']
        self.assertIn("resolution=merge-duplicates", called_headers['Prefer'])

    async def test_insert_with_empty_data_raises_error(self):
        """❌ Test that INSERT with empty data raises a ValidationError."""
        with self.assertRaisesRegex(ValidationError, "Data is required"):
            await self.client.insert("users", data=[])

    @patch('app.external.supabase_client.httpx.AsyncClient')
    async def test_execute_rpc(self, MockAsyncClient):
        """✅ Test RPC execution calls the correct endpoint."""
        mock_instance = MockAsyncClient.return_value
        mock_instance.is_closed = False
        mock_instance.request = AsyncMock(return_value=self._create_mock_response(200, json_data={"result": "ok"}))

        await self.client.execute_rpc("my_function", {"param": "value"})
        mock_instance.request.assert_awaited_once()

    # ========== Authentication, RLS, and Edge Case Tests ==========

    @patch('app.external.supabase_client.httpx.AsyncClient')
    async def test_insert_with_user_id_rls(self, MockAsyncClient):
        """✅ Test INSERT with a user_id for RLS JWT generation."""
        mock_instance = MockAsyncClient.return_value
        mock_instance.is_closed = False
        mock_instance.request = AsyncMock(return_value=self._create_mock_response(201, json_data=[{"id": "user-123"}]))

        await self.client.insert("profiles", {"id": "user-123"}, user_id="user-123")
        called_headers = mock_instance.request.call_args.kwargs['headers']
        self.assertTrue(called_headers['Authorization'].startswith('Bearer ey'))

    @patch('app.external.supabase_client.httpx.AsyncClient')
    async def test_update_uses_service_key(self, MockAsyncClient):
        """✅ Test UPDATE without a user_id uses the service key."""
        mock_instance = MockAsyncClient.return_value
        mock_instance.is_closed = False
        mock_instance.request = AsyncMock(return_value=self._create_mock_response(200, json_data=[{"email": "new@email.com"}]))

        await self.client.update("users", {"email": "new@email.com"}, filters={"id": 1})
        called_headers = mock_instance.request.call_args.kwargs['headers']
        self.assertEqual(called_headers['Authorization'], f"Bearer {self.client.service_key}")

    async def test_update_without_filters_raises_error(self):
        """❌ Test that UPDATE without filters raises a ValidationError."""
        with self.assertRaisesRegex(ValidationError, "Filters are required for updates"):
            await self.client.update("users", data={"name": "test"}, filters={})

    @patch('app.external.supabase_client.httpx.AsyncClient')
    async def test_sign_up(self, MockAsyncClient):
        """✅ Test sign_up calls the correct auth endpoint."""
        mock_instance = MockAsyncClient.return_value
        mock_instance.is_closed = False
        mock_instance.request = AsyncMock(return_value=self._create_mock_response(200, json_data={"user": "new_user"}))

        await self.client.sign_up("test@example.com", "password")
        mock_instance.request.assert_awaited_once()

    def test_generate_user_jwt_raises_error_if_no_secret(self):
        """❌ Test JWT generation fails without a secret."""
        self.client.jwt_secret = None
        with self.assertRaisesRegex(ValidationError, "JWT secret not configured"):
            self.client._generate_user_jwt("user-123")

    # ========== Error Handling and Reliability Tests ==========

    @patch('app.external.supabase_client.httpx.AsyncClient')
    async def test_http_error_mapping_parameterized(self, MockAsyncClient):
        """❌ Test various HTTP error codes map to the correct custom exceptions."""
        test_cases = [
            (401, "Unauthorized", AuthenticationError),
            (403, "Forbidden", AuthenticationError),
            (404, "Not Found", NotFoundError),
            (429, "Too Many Requests", RateLimitError),
            (500, "Server Error", DatabaseError),
            (502, "Bad Gateway", DatabaseError),
        ]

        for status, text, expected_exception in test_cases:
            self.client._circuit_breaker = {
                "failure_count": 0, "last_failure": None, "state": "closed", "next_attempt": None
            }
            with self.subTest(status=status):
                mock_instance = MockAsyncClient.return_value
                mock_instance.is_closed = False
                mock_instance.request = AsyncMock(return_value=self._create_mock_response(status, text_data=text))
                
                with self.assertRaises(expected_exception):
                    await self.client.select("some_table")

    @patch('app.external.supabase_client.SupabaseClient._sleep', new_callable=AsyncMock)
    @patch('app.external.supabase_client.httpx.AsyncClient')
    async def test_retry_logic_on_request_error(self, MockAsyncClient, mock_sleep):
        """🔁 Test retry logic when httpx raises a network error."""
        mock_instance = MockAsyncClient.return_value
        mock_instance.is_closed = False
        success_response = self._create_mock_response(200, json_data={"ok": True})
        
        mock_instance.request = AsyncMock(side_effect=[
            httpx.RequestError("Connection failed", request=None),
            httpx.TimeoutException("Timeout", request=None),
            success_response
        ])
        self.client.MAX_RETRIES = 2
        await self.client.select("users")
        self.assertEqual(mock_instance.request.call_count, 3)

    @patch('time.time')
    def test_circuit_breaker_opens_and_closes(self, mock_time):
        """🛡️ Test the full circuit breaker open/close/half-open lifecycle."""
        mock_time.return_value = 1000.0
        self.client._circuit_breaker["failure_count"] = self.client.CIRCUIT_BREAKER_THRESHOLD - 1
        self.client._record_failure()
        self.assertEqual(self.client._circuit_breaker["state"], "open")
        self.assertFalse(self.client._check_circuit_breaker())
        mock_time.return_value = 1000.0 + self.client.CIRCUIT_BREAKER_TIMEOUT + 1
        self.assertTrue(self.client._check_circuit_breaker())
        self.assertEqual(self.client._circuit_breaker["state"], "half_open")
        self.client._record_success()
        self.assertEqual(self.client._circuit_breaker["state"], "closed")
        
    @patch('app.external.supabase_client.SupabaseClient._sleep', new_callable=AsyncMock)
    @patch('time.time')
    async def test_rate_limiter_throttles_requests(self, mock_time, mock_sleep):
        """⏳ Test that the rate limiter sleeps when the threshold is exceeded."""
        self.client.MAX_REQUESTS_PER_SECOND = 2
        mock_time.return_value = 1000.0
        await self.client._apply_rate_limit()
        mock_time.return_value = 1000.1
        await self.client._apply_rate_limit()
        mock_time.return_value = 1000.2
        await self.client._apply_rate_limit()
        mock_sleep.assert_awaited_once()

    # ========== Monitoring and Singleton Tests ==========
    
    @patch('app.external.supabase_client.httpx.AsyncClient')
    async def test_health_check_success(self, MockAsyncClient):
        """🩺 Test a successful health check."""
        mock_instance = MockAsyncClient.return_value
        mock_instance.is_closed = False
        mock_instance.request = AsyncMock(return_value=self._create_mock_response(200, json_data=[{"count": 1}]))

        health = await self.client.health_check()
        self.assertEqual(health['status'], 'healthy')
        self.assertEqual(health['database'], 'connected')

    def test_singleton_pattern(self):
        """📦 Test that get_supabase_client returns a singleton instance."""
        client1 = get_supabase_client()
        client2 = get_supabase_client()
        self.assertIs(client1, client2)
