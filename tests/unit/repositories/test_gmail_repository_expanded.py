# test/data/repositories/test_gmail_repository.py
"""
EXPANDED UNIT TESTS for the GmailRepository.

Covers all core functionality, edge cases, legacy compatibility,
and factory creation to ensure a "Zero Compromise" implementation.
"""
import pytest
import asyncio
from uuid import UUID, uuid4
from datetime import datetime, timedelta
from unittest.mock import MagicMock, AsyncMock
from copy import deepcopy

# Module under test
from app.data.repositories.gmail_repository import (
    GmailRepository,
    GmailConnection,
    ConnectionStatus,
    GmailConnectionStats,
    create_gmail_repository,
)

# Exceptions
from app.core.exceptions import (
    ValidationError,
    DuplicateGmailConnectionError,
    GmailConnectionNotFoundError,
    InvalidConnectionStatusError,
    DatabaseError,
)

# --- Test Constants ---
TEST_USER_ID = uuid4()
OTHER_USER_ID = uuid4()
TEST_EMAIL = "test.user@example.com"


# --- Pytest Fixtures ---

@pytest.fixture
def mock_supabase_client():
    """Mocks the SupabaseClient for database interaction tests."""
    client = MagicMock(name="MockSupabaseClient")
    client.insert = AsyncMock()
    client.select = AsyncMock()
    client.update = AsyncMock()
    client.delete = AsyncMock()
    return client

@pytest.fixture
def memory_repo() -> GmailRepository:
    """Provides a GmailRepository instance using in-memory storage."""
    return GmailRepository(supabase_client=None)

@pytest.fixture
def db_repo(mock_supabase_client) -> GmailRepository:
    """Provides a GmailRepository instance configured with a mocked Supabase client."""
    return GmailRepository(supabase_client=mock_supabase_client)

@pytest.fixture
def sample_connection_data() -> dict:
    """Provides a dictionary with sample data for creating a connection."""
    now = datetime.utcnow()
    return {
        "user_id": TEST_USER_ID,
        "email_address": TEST_EMAIL,
        "access_token": "test_access_token_string",
        "refresh_token": "test_refresh_token_string",
        "token_expires_at": (now + timedelta(hours=1)).isoformat(),
        "connection_status": "connected",
        "scopes": ["https://www.googleapis.com/auth/gmail.readonly"],
        "created_at": now.isoformat(),
        "updated_at": now.isoformat()
    }

@pytest.fixture
def sample_connection(sample_connection_data) -> GmailConnection:
    """Provides a GmailConnection domain model instance."""
    data = sample_connection_data.copy()
    # Convert string dates back to datetime for the object constructor
    data['token_expires_at'] = datetime.fromisoformat(data['token_expires_at']) if data.get('token_expires_at') else None
    data['created_at'] = datetime.fromisoformat(data['created_at'])
    data['updated_at'] = datetime.fromisoformat(data['updated_at'])
    data['connection_status'] = ConnectionStatus(data['connection_status'])
    return GmailConnection(
        connection_id=uuid4(),
        **data
    )


# --- Core CRUD and Validation Tests (Previously Established) ---

@pytest.mark.asyncio
async def test_create_connection_memory(memory_repo: GmailRepository, sample_connection_data):
    """Verify creating a connection in-memory."""
    connection = await memory_repo.create_connection(sample_connection_data)
    assert isinstance(connection, GmailConnection)
    assert connection.user_id == TEST_USER_ID

@pytest.mark.asyncio
async def test_get_connection_by_user_id_memory(memory_repo: GmailRepository, sample_connection_data):
    """Verify retrieving a connection by user ID from in-memory storage."""
    await memory_repo.create_connection(sample_connection_data)
    retrieved = await memory_repo.get_connection_by_user_id(TEST_USER_ID)
    assert retrieved is not None
    assert retrieved.user_id == TEST_USER_ID

@pytest.mark.asyncio
async def test_update_connection_memory(memory_repo: GmailRepository, sample_connection_data):
    """Verify updating a connection in-memory."""
    created = await memory_repo.create_connection(sample_connection_data)
    updated = await memory_repo.update_connection(TEST_USER_ID, {"connection_status": "revoked"})
    assert updated.connection_status == ConnectionStatus.REVOKED
    assert updated.updated_at > created.updated_at

@pytest.mark.asyncio
async def test_delete_connection_memory(memory_repo: GmailRepository, sample_connection_data):
    """Verify deleting a connection from in-memory storage."""
    await memory_repo.create_connection(sample_connection_data)
    result = await memory_repo.delete_connection(TEST_USER_ID)
    assert result is True
    assert await memory_repo.get_connection_by_user_id(TEST_USER_ID) is None

@pytest.mark.asyncio
async def test_create_connection_duplicate_error(memory_repo: GmailRepository, sample_connection_data):
    """Verify that creating a duplicate connection raises the correct error."""
    await memory_repo.create_connection(sample_connection_data)
    with pytest.raises(DuplicateGmailConnectionError):
        await memory_repo.create_connection(sample_connection_data)

@pytest.mark.asyncio
async def test_create_connection_invalid_status(memory_repo: GmailRepository, sample_connection_data):
    """Verify that an invalid connection status raises a validation error."""
    data = sample_connection_data.copy()
    data["connection_status"] = "invalid_status"
    with pytest.raises(InvalidConnectionStatusError):
        await memory_repo.create_connection(data)

@pytest.mark.asyncio
async def test_create_connection_missing_required_fields(memory_repo: GmailRepository, sample_connection_data):
    """Verify that missing user_id or refresh_token raises a validation error."""
    with pytest.raises(ValidationError, match="user_id is required"):
        await memory_repo.create_connection({"refresh_token": "abc"})
    with pytest.raises(ValidationError, match="refresh_token is required"):
        await memory_repo.create_connection({"user_id": uuid4()})

@pytest.mark.asyncio
async def test_update_nonexistent_connection_error(memory_repo: GmailRepository):
    """Verify that updating a non-existent connection raises the correct error."""
    with pytest.raises(GmailConnectionNotFoundError):
        await memory_repo.update_connection(uuid4(), {"connection_status": "error"})


# --- Expanded Read/Update Operation Tests ---

@pytest.mark.asyncio
async def test_get_connection_by_id(memory_repo: GmailRepository, sample_connection_data):
    """Verify retrieving a connection by its own ID."""
    created = await memory_repo.create_connection(sample_connection_data)
    retrieved = await memory_repo.get_connection_by_id(created.connection_id)
    assert retrieved is not None
    assert retrieved.connection_id == created.connection_id
    assert retrieved.user_id == TEST_USER_ID

@pytest.mark.asyncio
async def test_list_connections_for_user_with_pagination(memory_repo: GmailRepository):
    """Verify listing connections with limit and offset."""
    now = datetime.utcnow()
    # This test is only meaningful for a repo that could have multiple connections per user
    # but we can test the logic anyway.
    c1_data = {"id": str(uuid4()), "user_id": str(TEST_USER_ID), "refresh_token": "rt1", "created_at": (now - timedelta(days=2)).isoformat(), "updated_at": now.isoformat()}
    c2_data = {"id": str(uuid4()), "user_id": str(TEST_USER_ID), "refresh_token": "rt2", "created_at": (now - timedelta(days=1)).isoformat(), "updated_at": now.isoformat()}
    
    # In a real scenario, this would raise a DuplicateGmailConnectionError.
    # We bypass it by directly manipulating the internal store for this test.
    # The key for the internal store is a unique UUID, not the user_id.
    memory_repo._connections[uuid4()] = c1_data
    memory_repo._connections[uuid4()] = c2_data

    # Get all
    all_conns = await memory_repo.list_connections_for_user(TEST_USER_ID)
    assert len(all_conns) == 2

    # Get with limit
    limited_conns = await memory_repo.list_connections_for_user(TEST_USER_ID, limit=1)
    assert len(limited_conns) == 1
    # Check that it returns the most recent one first
    assert limited_conns[0].refresh_token == "rt2"

    # Get with offset
    offset_conns = await memory_repo.list_connections_for_user(TEST_USER_ID, limit=1, offset=1)
    assert len(offset_conns) == 1
    assert offset_conns[0].refresh_token == "rt1"

@pytest.mark.asyncio
async def test_refresh_access_token(memory_repo: GmailRepository, sample_connection_data):
    """Verify the refresh_access_token convenience method."""
    await memory_repo.create_connection(sample_connection_data)
    
    new_token = "new_refreshed_access_token"
    new_expiry = datetime.utcnow() + timedelta(hours=1)
    
    updated_conn = await memory_repo.refresh_access_token(TEST_USER_ID, new_token, new_expiry)
    
    assert updated_conn.access_token == new_token
    assert updated_conn.token_expires_at == new_expiry
    assert updated_conn.connection_status == ConnectionStatus.CONNECTED


# --- Legacy Compatibility Tests ---

@pytest.mark.asyncio
async def test_legacy_get_connection_with_string_id(memory_repo: GmailRepository, sample_connection_data):
    """Verify the legacy get_connection method works with string UUIDs."""
    await memory_repo.create_connection(sample_connection_data)
    
    # Use string representation of the UUID
    connection_dict = await memory_repo.get_connection(str(TEST_USER_ID))
    
    assert connection_dict is not None
    assert connection_dict["user_id"] == str(TEST_USER_ID)

@pytest.mark.asyncio
async def test_legacy_get_connection_invalid_uuid_string(memory_repo: GmailRepository):
    """Verify legacy get_connection raises error for invalid UUID string."""
    with pytest.raises(ValidationError, match="user_id must be a valid UUID"):
        await memory_repo.get_connection("not-a-uuid")

@pytest.mark.asyncio
async def test_legacy_store_oauth_tokens_creates_new_connection(memory_repo: GmailRepository):
    """Verify store_oauth_tokens creates a new connection."""
    tokens = {"access_token": "at", "refresh_token": "rt", "expires_in": 3600}
    user_info = {"email": "new.user@example.com"}
    
    result = await memory_repo.store_oauth_tokens(str(TEST_USER_ID), tokens, user_info)
    
    assert result is True
    new_conn = await memory_repo.get_connection_by_user_id(TEST_USER_ID)
    assert new_conn is not None
    assert new_conn.email_address == "new.user@example.com"

@pytest.mark.asyncio
async def test_legacy_store_oauth_tokens_updates_existing_connection(memory_repo: GmailRepository, sample_connection_data):
    """Verify store_oauth_tokens updates an existing connection."""
    await memory_repo.create_connection(sample_connection_data)
    
    tokens = {"access_token": "updated_at", "refresh_token": "updated_rt", "expires_in": 3600}
    user_info = {"email": "updated.email@example.com"}
    
    result = await memory_repo.store_oauth_tokens(str(TEST_USER_ID), tokens, user_info)
    
    assert result is True
    updated_conn = await memory_repo.get_connection_by_user_id(TEST_USER_ID)
    assert updated_conn.access_token == "updated_at"
    assert updated_conn.email_address == "updated.email@example.com"


# --- Health Check and Factory Tests ---

@pytest.mark.asyncio
async def test_health_check_memory(memory_repo: GmailRepository):
    """Verify the health check for in-memory repository."""
    health = await memory_repo.health_check()
    assert health["healthy"] is True
    assert health["storage"] == "memory"

@pytest.mark.asyncio
async def test_health_check_db_success(db_repo: GmailRepository, mock_supabase_client):
    """Verify the health check for a healthy database-backed repository."""
    mock_supabase_client.select.return_value = [] # A successful empty query
    health = await db_repo.health_check()
    assert health["healthy"] is True
    assert health["storage"] == "database"

@pytest.mark.asyncio
async def test_health_check_db_failure(db_repo: GmailRepository, mock_supabase_client):
    """Verify the health check reports failure when the database is down."""
    mock_supabase_client.select.side_effect = Exception("Connection failed")
    health = await db_repo.health_check()
    assert health["healthy"] is False
    assert "Connection failed" in health["error"]

def test_create_gmail_repository_factory():
    """Verify the factory method returns the correct repository type."""
    test_repo = create_gmail_repository(env="test")
    assert isinstance(test_repo, GmailRepository)
    assert test_repo._use_database is False
    
    # This test doesn't actually connect to a DB, just checks the instance type
    prod_repo = create_gmail_repository(env="production")
    assert isinstance(prod_repo, GmailRepository)
    assert prod_repo._use_database is True


# --- Statistics Test (Previously Established) ---

@pytest.mark.asyncio
async def test_gmail_connection_stats(memory_repo: GmailRepository):
    """Verify the calculation of connection statistics."""
    now = datetime.utcnow()
    c1_data = {"user_id": uuid4(), "refresh_token": "rt1", "connection_status": "connected", "created_at": (now - timedelta(days=10)).isoformat(), "updated_at": now.isoformat()}
    c2_data = {"user_id": uuid4(), "refresh_token": "rt2", "connection_status": "error", "created_at": (now - timedelta(days=20)).isoformat(), "updated_at": now.isoformat()}
    c3_data = {"user_id": uuid4(), "refresh_token": "rt3", "connection_status": "connected", "created_at": now.isoformat(), "updated_at": now.isoformat(), "token_expires_at": (now + timedelta(seconds=100)).isoformat()}

    # Assuming the create_connection fix is in place to respect created_at
    await memory_repo.create_connection(c1_data)
    await memory_repo.create_connection(c2_data)
    await memory_repo.create_connection(c3_data)

    stats = await memory_repo.get_connection_stats()

    assert isinstance(stats, GmailConnectionStats)
    assert stats.total_connections == 3
    assert stats.active_connections == 2
    assert stats.error_connections == 1
    assert stats.connections_by_status == {"connected": 2, "error": 1}
    assert stats.tokens_expiring_soon == 1
    assert stats.average_connection_age_days == 10.0
