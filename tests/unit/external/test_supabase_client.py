# tests/external/test_supabase_client.py
"""
Unit tests for the Supabase Database Client.
"""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

# The client we are testing
from app.external.supabase_client import SupabaseClient
# The module where settings are imported, so we can patch them
from app.external import supabase_client as client_module
# Exceptions the client is expected to handle or raise
from app.core.exceptions import ValidationError, APIError, NotFoundError


@pytest.fixture
def mock_settings():
    """Fixture to provide a mock settings object for the client."""
    settings = MagicMock()
    settings.database_url = "http://mock.supabase.co"
    settings.database_key = "test_anon_key"
    settings.database_service_key = "test_service_key"
    settings.database_jwt_secret = "test_jwt_secret"
    return settings


@pytest.fixture
def client(mock_settings):
    """Fixture to create an instance of the SupabaseClient with mocked settings."""
    # Patch the settings object within the client's module before instantiation
    with patch.object(client_module, "settings", mock_settings):
        yield SupabaseClient()


@pytest.mark.asyncio
class TestDatabaseOperations:
    """Tests for the core database operations (SELECT, INSERT, etc.)."""

    async def test_select_success(self, client):
        """
        Test a successful SELECT operation.
        Verifies that the correct parameters are constructed and passed to the request method.
        """
        # --- Arrange ---
        with patch.object(client, "_make_request", new=AsyncMock()) as mock_request:
            mock_request.return_value = [{"id": 1, "name": "Test Item"}]
            
            table = "products"
            filters = {"category": "electronics"}
            limit = 10

            # --- Act ---
            results = await client.select(table=table, filters=filters, limit=limit)

            # --- Assert ---
            mock_request.assert_awaited_once()
            
            # FIXED: Check positional args for method and endpoint
            call_args, call_kwargs = mock_request.call_args
            assert call_args[0] == "GET"
            assert call_args[1] == "/rest/v1/products"
            
            expected_params = {"category": "eq.electronics", "limit": "10"}
            assert call_kwargs["params"] == expected_params
            
            assert len(results) == 1
            assert results[0]["name"] == "Test Item"

    async def test_select_with_no_table_raises_error(self, client):
        """
        Test that calling select without a table name raises a ValidationError.
        """
        with pytest.raises(ValidationError, match="Table name is required"):
            await client.select(table="")

    async def test_insert_success(self, client):
        """
        Test a successful INSERT operation.
        """
        with patch.object(client, "_make_request", new=AsyncMock()) as mock_request:
            insert_data = {"name": "New Product", "price": 99.99}
            mock_request.return_value = [{"id": 2, **insert_data}]

            result = await client.insert(table="products", data=insert_data)

            mock_request.assert_awaited_once()
            # FIXED: Check positional args for method and endpoint
            call_args, call_kwargs = mock_request.call_args
            assert call_args[0] == "POST"
            assert call_args[1] == "/rest/v1/products"
            assert call_kwargs["json"] == insert_data
            assert "return=representation" in call_kwargs["headers"]["Prefer"]
            
            assert len(result) == 1
            assert result[0]["name"] == "New Product"

    async def test_update_success(self, client):
        """Test a successful UPDATE operation."""
        with patch.object(client, "_make_request", new=AsyncMock()) as mock_request:
            update_data = {"price": 129.99}
            filters = {"id": 1}
            mock_request.return_value = [{"id": 1, "price": 129.99}]

            result = await client.update(table="products", data=update_data, filters=filters)

            mock_request.assert_awaited_once()
            call_args, call_kwargs = mock_request.call_args
            assert call_args[0] == "PATCH"
            assert call_args[1] == "/rest/v1/products"
            assert call_kwargs["json"] == update_data
            assert call_kwargs["params"] == {"id": "eq.1"}
            assert "return=representation" in call_kwargs["headers"]["Prefer"]
            assert result[0]["price"] == 129.99

    async def test_delete_success(self, client):
        """Test a successful DELETE operation."""
        with patch.object(client, "_make_request", new=AsyncMock()) as mock_request:
            filters = {"id": 1}
            mock_request.return_value = [{"id": 1, "name": "Deleted Product"}]

            result = await client.delete(table="products", filters=filters)

            mock_request.assert_awaited_once()
            call_args, call_kwargs = mock_request.call_args
            assert call_args[0] == "DELETE"
            assert call_args[1] == "/rest/v1/products"
            assert call_kwargs["params"] == {"id": "eq.1"}
            assert result[0]["name"] == "Deleted Product"

    async def test_upsert_success(self, client):
        """Test a successful UPSERT operation."""
        with patch.object(client, "_make_request", new=AsyncMock()) as mock_request:
            upsert_data = {"id": 1, "name": "Upserted Product"}
            mock_request.return_value = [upsert_data]

            result = await client.upsert(table="products", data=upsert_data)

            mock_request.assert_awaited_once()
            call_args, call_kwargs = mock_request.call_args
            assert call_args[0] == "POST"
            assert call_args[1] == "/rest/v1/products"
            assert "resolution=merge-duplicates" in call_kwargs["headers"]["Prefer"]
            assert result[0]["name"] == "Upserted Product"

    async def test_execute_rpc_success(self, client):
        """Test a successful RPC function call."""
        with patch.object(client, "_make_request", new=AsyncMock()) as mock_request:
            mock_request.return_value = {"result": "ok"}

            result = await client.execute_rpc("test_function", params={"key": "value"})

            mock_request.assert_awaited_once()
            call_args, call_kwargs = mock_request.call_args
            assert call_args[0] == "POST"
            assert call_args[1] == "/rest/v1/rpc/test_function"
            assert call_kwargs["json"] == {"key": "value"}
            assert result["result"] == "ok"

    async def test_execute_rpc_missing_name_raises(self, client):
        """Test that missing function name in RPC raises ValidationError."""
        with pytest.raises(ValidationError, match="Function name is required"):
            await client.execute_rpc(function_name="")

    async def test_execute_sql_delegates_to_rpc(self, client):
        """Test that execute_sql properly delegates to execute_rpc."""
        with patch.object(client, "execute_rpc", new=AsyncMock()) as mock_rpc:
            mock_rpc.return_value = [{"id": 1}]

            result = await client.execute_sql("SELECT * FROM table", params=["table"])

            mock_rpc.assert_awaited_once_with("execute_sql", {"query": "SELECT * FROM table", "params": ["table"]}, user_id=None)
            assert isinstance(result, list)
            assert result[0]["id"] == 1

    async def test_execute_sql_missing_query_raises(self, client):
        """Test that missing SQL query raises ValidationError."""
        with pytest.raises(ValidationError, match="Query is required"):
            await client.execute_sql(query="")

    async def test_sign_up_success(self, client):
        """Test successful user sign-up."""
        with patch.object(client, "_make_request", new=AsyncMock()) as mock_request:
            mock_request.return_value = {"user": {"email": "test@example.com"}, "session": {}}

            result = await client.sign_up("test@example.com", "securepassword")

            mock_request.assert_awaited_once()
            call_args, call_kwargs = mock_request.call_args
            assert call_args[0] == "POST"
            assert call_args[1] == "/auth/v1/signup"
            assert call_kwargs["json"]["email"] == "test@example.com"
            assert call_kwargs["json"]["password"] == "securepassword"
            assert result["user"]["email"] == "test@example.com"

    async def test_sign_up_missing_fields(self, client):
        """Test sign-up with missing email or password raises error."""
        with pytest.raises(ValidationError, match="Email and password are required"):
            await client.sign_up("", "pass")

        with pytest.raises(ValidationError, match="Email and password are required"):
            await client.sign_up("test@example.com", "")

    async def test_sign_in_success(self, client):
        """Test successful user sign-in."""
        with patch.object(client, "_make_request", new=AsyncMock()) as mock_request:
            mock_request.return_value = {"user": {"email": "test@example.com"}, "session": {}}

            result = await client.sign_in("test@example.com", "securepassword")

            mock_request.assert_awaited_once()
            call_args, call_kwargs = mock_request.call_args
            assert call_args[0] == "POST"
            assert call_args[1] == "/auth/v1/token?grant_type=password"
            assert call_kwargs["json"]["email"] == "test@example.com"
            assert call_kwargs["json"]["password"] == "securepassword"
            assert result["user"]["email"] == "test@example.com"

    async def test_sign_in_missing_fields(self, client):
        """Test sign-in with missing email or password raises error."""
        with pytest.raises(ValidationError, match="Email and password are required"):
            await client.sign_in("", "pass")

        with pytest.raises(ValidationError, match="Email and password are required"):
            await client.sign_in("test@example.com", "")

    async def test_upload_file_success(self, client):
        """Test successful file upload."""
        with patch.object(client, "_make_request", new=AsyncMock()) as mock_request:
            mock_request.return_value = {"key": "value"}
            bucket = "public"
            path = "test.txt"
            data = b"hello"
            result = await client.upload_file(bucket, path, data, content_type="text/plain")

            mock_request.assert_awaited_once()
            call_args, call_kwargs = mock_request.call_args
            assert call_args[0] == "POST"
            assert call_args[1] == f"/storage/v1/object/{bucket}/{path}"
            assert call_kwargs["data"] == data
            assert call_kwargs["headers"]["Content-Type"] == "text/plain"
            assert result["key"] == "value"

    async def test_upload_file_missing_fields(self, client):
        """Test upload_file raises ValidationError if required fields are missing."""
        with pytest.raises(ValidationError, match="Bucket and file path are required"):
            await client.upload_file("", "path.txt", b"data")

        with pytest.raises(ValidationError, match="Bucket and file path are required"):
            await client.upload_file("bucket", "", b"data")

    async def test_download_file_success(self, client):
        """Test successful file download."""
        with patch.object(client, "_make_request", new=AsyncMock()) as mock_request:
            mock_request.return_value = b"file content"
            result = await client.download_file("mybucket", "file.txt")

            mock_request.assert_awaited_once()
            call_args, call_kwargs = mock_request.call_args
            assert call_args[0] == "GET"
            assert call_args[1] == "/storage/v1/object/mybucket/file.txt"
            assert call_kwargs["return_raw"] is True
            assert result == b"file content"

    async def test_download_file_missing_fields(self, client):
        """Test download_file raises ValidationError if required fields are missing."""
        with pytest.raises(ValidationError, match="Bucket and file path are required"):
            await client.download_file("", "path.txt")

        with pytest.raises(ValidationError, match="Bucket and file path are required"):
            await client.download_file("bucket", "")

    async def test_delete_file_success(self, client):
        """Test successful file deletion."""
        with patch.object(client, "_make_request", new=AsyncMock()) as mock_request:
            mock_request.return_value = {"deleted": True}
            result = await client.delete_file("mybucket", "file.txt")

            mock_request.assert_awaited_once()
            call_args, call_kwargs = mock_request.call_args
            assert call_args[0] == "DELETE"
            assert call_args[1] == "/storage/v1/object/mybucket/file.txt"
            assert result["deleted"] is True

    async def test_delete_file_missing_fields(self, client):
        """Test delete_file raises ValidationError if required fields are missing."""
        with pytest.raises(ValidationError, match="Bucket and file path are required"):
            await client.delete_file("", "file.txt")

        with pytest.raises(ValidationError, match="Bucket and file path are required"):
            await client.delete_file("mybucket", "")


    async def test_sign_out_success(self, client):
        """Test successful user sign-out."""
        with patch.object(client, "_make_request", new=AsyncMock()) as mock_request:
            mock_request.return_value = {"revoked": True}

            result = await client.sign_out("mock_token")

            mock_request.assert_awaited_once()
            call_args, call_kwargs = mock_request.call_args
            assert call_args[0] == "POST"
            assert call_args[1] == "/auth/v1/logout"
            assert call_kwargs["headers"]["Authorization"] == "Bearer mock_token"
            assert result["revoked"] is True

    async def test_sign_out_missing_token(self, client):
        """Test sign-out with missing token raises error."""
        with pytest.raises(ValidationError, match="Access token is required"):
            await client.sign_out("")

    async def test_get_user_success(self, client):
        """Test fetching current user info."""
        with patch.object(client, "_make_request", new=AsyncMock()) as mock_request:
            mock_request.return_value = {"email": "user@example.com"}

            result = await client.get_user("access123")

            mock_request.assert_awaited_once()
            call_args, call_kwargs = mock_request.call_args
            assert call_args[0] == "GET"
            assert call_args[1] == "/auth/v1/user"
            assert call_kwargs["headers"]["Authorization"] == "Bearer access123"
            assert result["email"] == "user@example.com"

    async def test_get_user_missing_token(self, client):
        """Test get_user with missing token raises error."""
        with pytest.raises(ValidationError, match="Access token is required"):
            await client.get_user("")

    async def test_update_user_success(self, client):
        """Test updating user profile info."""
        with patch.object(client, "_make_request", new=AsyncMock()) as mock_request:
            updates = {"data": {"full_name": "John Doe"}}
            mock_request.return_value = {"user": {"full_name": "John Doe"}}

            result = await client.update_user("access123", updates)

            mock_request.assert_awaited_once()
            call_args, call_kwargs = mock_request.call_args
            assert call_args[0] == "PUT"
            assert call_args[1] == "/auth/v1/user"
            assert call_kwargs["headers"]["Authorization"] == "Bearer access123"
            assert call_kwargs["json"] == updates
            assert result["user"]["full_name"] == "John Doe"

    async def test_update_user_missing_token(self, client):
        """Test update_user with missing token raises error."""
        with pytest.raises(ValidationError, match="Access token is required"):
            await client.update_user("", {"data": {"name": "X"}})



    async def test_health_check_healthy(self, client):
        """Test health_check returns healthy status."""
        with patch.object(client, "select", new=AsyncMock()) as mock_select:
            mock_select.return_value = [{"count": 1}]

            result = await client.health_check()

            assert result["status"] == "healthy"
            assert result["database"] == "connected"
            assert result["circuit_breaker"] == "closed"
            assert "timestamp" in result

    async def test_health_check_unhealthy(self, client):
        """Test health_check returns unhealthy status if select fails."""
        with patch.object(client, "select", new=AsyncMock(side_effect=Exception("boom"))):
            result = await client.health_check()

            assert result["status"] == "unhealthy"
            assert result["database"] == "disconnected"
            assert "boom" in result["error"]
            assert result["circuit_breaker"] in ["closed", "open"]
            assert "timestamp" in result

    def test_circuit_breaker_opens_after_failures(self, client):
        """Test that circuit breaker opens after repeated failures."""
        for _ in range(5):
            client._record_failure()

        assert client._circuit_breaker["state"] == "open"
        assert client._circuit_breaker["failure_count"] >= 5

    def test_circuit_breaker_closes_on_success(self, client):
        """Test that a success resets the circuit breaker."""
        client._record_failure()
        client._record_success()

        assert client._circuit_breaker["state"] == "closed"
        assert client._circuit_breaker["failure_count"] == 0
