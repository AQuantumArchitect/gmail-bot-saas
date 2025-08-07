# test/data/repositories/test_gmail_repository.py
"""
Unit tests for the revised GmailRepository.

Key principles:
- Tests the in-memory implementation directly.
- Mocks the SupabaseClient for database interaction tests.
- Covers all public methods of the repository.
- Validates UUID-first architecture and domain model usage.
- Ensures exceptions are raised correctly for invalid operations.
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
    }

@pytest.fixture
def sample_connection(sample_connection_data) -> GmailConnection:
    """Provides a GmailConnection domain model instance."""
    now = datetime.utcnow()
    data = sample_connection_data.copy()
    # Convert string dates back to datetime for the object constructor
    data['token_expires_at'] = datetime.fromisoformat(data['token_expires_at'])
    data['connection_status'] = ConnectionStatus(data['connection_status'])
    return GmailConnection(
        connection_id=uuid4(),
        created_at=now,
        updated_at=now,
        **data
    )


# --- In-Memory Repository Tests ---

@pytest.mark.asyncio
async def test_create_connection_memory(memory_repo: GmailRepository, sample_connection_data):
    """Verify creating a connection in-memory."""
    # Act
    connection = await memory_repo.create_connection(sample_connection_data)

    # Assert
    assert isinstance(connection, GmailConnection)
    assert connection.user_id == TEST_USER_ID
    assert connection.email_address == TEST_EMAIL
    assert connection.connection_status == ConnectionStatus.CONNECTED

@pytest.mark.asyncio
async def test_get_connection_by_user_id_memory(memory_repo: GmailRepository, sample_connection_data):
    """Verify retrieving a connection by user ID from in-memory storage."""
    # Arrange
    await memory_repo.create_connection(sample_connection_data)

    # Act
    retrieved = await memory_repo.get_connection_by_user_id(TEST_USER_ID)

    # Assert
    assert retrieved is not None
    assert retrieved.user_id == TEST_USER_ID

@pytest.mark.asyncio
async def test_update_connection_memory(memory_repo: GmailRepository, sample_connection_data):
    """Verify updating a connection in-memory."""
    # Arrange
    created = await memory_repo.create_connection(sample_connection_data)
    assert created.connection_status == ConnectionStatus.CONNECTED

    # Act
    updated = await memory_repo.update_connection(TEST_USER_ID, {"connection_status": "revoked"})

    # Assert
    assert updated.connection_status == ConnectionStatus.REVOKED
    assert updated.updated_at > created.updated_at

@pytest.mark.asyncio
async def test_delete_connection_memory(memory_repo: GmailRepository, sample_connection_data):
    """Verify deleting a connection from in-memory storage."""
    # Arrange
    await memory_repo.create_connection(sample_connection_data)
    assert await memory_repo.get_connection_by_user_id(TEST_USER_ID) is not None

    # Act
    result = await memory_repo.delete_connection(TEST_USER_ID)
    
    # Assert
    assert result is True
    assert await memory_repo.get_connection_by_user_id(TEST_USER_ID) is None


# --- Database Repository Tests (with Mocked Client) ---

@pytest.mark.asyncio
async def test_create_connection_db(db_repo: GmailRepository, mock_supabase_client, sample_connection_data):
    """Verify the database create operation calls the client correctly."""
    # Arrange
    mock_supabase_client.select.return_value = [] # No existing connection
    
    db_response = {
        **sample_connection_data,
        "id": str(uuid4()),
        "user_id": str(TEST_USER_ID),
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
    }
    
    mock_supabase_client.insert.return_value = [db_response]
    db_repo._decrypt_tokens = AsyncMock(return_value=db_response)
    db_repo._encrypt_tokens = AsyncMock(side_effect=lambda x: x)

    # Act
    connection = await db_repo.create_connection(sample_connection_data)

    # Assert
    mock_supabase_client.insert.assert_called_once()
    db_repo._encrypt_tokens.assert_called_once()
    db_repo._decrypt_tokens.assert_called_once()
    assert connection.user_id == TEST_USER_ID

@pytest.mark.asyncio
async def test_get_connection_by_user_id_db_found(db_repo: GmailRepository, mock_supabase_client, sample_connection):
    """Verify retrieving a connection from the database."""
    # Arrange
    # .to_dict() correctly represents the raw data from the DB
    db_data = sample_connection.to_dict() 
    mock_supabase_client.select.return_value = [db_data]
    db_repo._decrypt_tokens = AsyncMock(return_value=db_data)

    # Act
    connection = await db_repo.get_connection_by_user_id(TEST_USER_ID)

    # Assert
    mock_supabase_client.select.assert_called_once_with(
        table="gmail_connections",
        columns="*",
        filters={"user_id": str(TEST_USER_ID)},
        user_id=str(TEST_USER_ID)
    )
    db_repo._decrypt_tokens.assert_called_once()
    assert connection is not None
    assert connection.user_id == TEST_USER_ID
    assert connection.connection_status == ConnectionStatus.CONNECTED

@pytest.mark.asyncio
async def test_get_connection_by_user_id_db_not_found(db_repo: GmailRepository, mock_supabase_client):
    """Verify behavior when a connection is not found in the database."""
    # Arrange
    mock_supabase_client.select.return_value = []

    # Act
    connection = await db_repo.get_connection_by_user_id(uuid4())

    # Assert
    assert connection is None

@pytest.mark.asyncio
async def test_delete_connection_db(db_repo: GmailRepository, mock_supabase_client, sample_connection):
    """Verify the database delete operation calls the client correctly."""
    # Arrange
    db_repo.get_connection_by_user_id = AsyncMock(return_value=sample_connection)

    # Act
    result = await db_repo.delete_connection(TEST_USER_ID)

    # Assert
    mock_supabase_client.delete.assert_called_once_with(
        table="gmail_connections",
        filters={"user_id": str(TEST_USER_ID)},
        user_id=str(TEST_USER_ID)
    )
    assert result is True


# --- Exception and Edge Case Tests ---

@pytest.mark.asyncio
async def test_create_connection_duplicate_error(memory_repo: GmailRepository, sample_connection_data):
    """Verify that creating a duplicate connection raises the correct error."""
    # Arrange
    await memory_repo.create_connection(sample_connection_data)

    # Act & Assert
    with pytest.raises(DuplicateGmailConnectionError):
        await memory_repo.create_connection(sample_connection_data)

@pytest.mark.asyncio
async def test_create_connection_invalid_status(memory_repo: GmailRepository, sample_connection_data):
    """Verify that an invalid connection status raises a validation error."""
    # Arrange
    data = sample_connection_data.copy()
    data["connection_status"] = "invalid_status"

    # Act & Assert
    with pytest.raises(InvalidConnectionStatusError):
        await memory_repo.create_connection(data)
        
@pytest.mark.asyncio
async def test_create_connection_missing_user_id(memory_repo: GmailRepository, sample_connection_data):
    """Verify that a missing user_id raises a validation error."""
    # Arrange
    data = sample_connection_data.copy()
    del data["user_id"]

    # Act & Assert
    with pytest.raises(ValidationError, match="user_id is required"):
        await memory_repo.create_connection(data)

@pytest.mark.asyncio
async def test_update_nonexistent_connection_error(memory_repo: GmailRepository):
    """Verify that updating a non-existent connection raises the correct error."""
    with pytest.raises(GmailConnectionNotFoundError):
        await memory_repo.update_connection(uuid4(), {"connection_status": "error"})

@pytest.mark.asyncio
async def test_delete_nonexistent_connection_error(memory_repo: GmailRepository):
    """Verify that deleting a non-existent connection raises the correct error."""
    with pytest.raises(GmailConnectionNotFoundError):
        await memory_repo.delete_connection(uuid4())

@pytest.mark.asyncio
async def test_db_operation_fails(db_repo: GmailRepository, mock_supabase_client):
    """Verify that a generic database exception is wrapped in DatabaseError."""
    # Arrange
    mock_supabase_client.select.side_effect = Exception("Supabase is down")

    # Act & Assert
    with pytest.raises(DatabaseError, match="Failed to get connection"):
        await db_repo.get_connection_by_user_id(uuid4())


# --- Convenience Method Tests ---

@pytest.mark.asyncio
async def test_create_oauth_connection(memory_repo: GmailRepository):
    """Verify the convenience method for creating a connection from OAuth tokens."""
    # Arrange
    oauth_tokens = {
        "access_token": "new_access_token",
        "refresh_token": "new_refresh_token",
        "expires_in": 3599
    }
    
    # Act
    connection = await memory_repo.create_oauth_connection(
        user_id=TEST_USER_ID,
        email_address=TEST_EMAIL,
        oauth_tokens=oauth_tokens
    )

    # Assert
    assert connection is not None
    assert connection.user_id == TEST_USER_ID
    assert connection.access_token == "new_access_token"
    assert connection.token_expires_at is not None
    assert connection.token_expires_at > datetime.utcnow()

@pytest.mark.asyncio
async def test_get_connections_needing_refresh(memory_repo: GmailRepository):
    """Verify correct retrieval of connections with expiring tokens."""
    # Arrange
    now = datetime.utcnow()
    # Connection that has already expired
    await memory_repo.create_connection({
        "user_id": uuid4(), "refresh_token": "rt1", "email_address": "e1@test.com",
        "token_expires_at": (now - timedelta(minutes=10)).isoformat(),
        "connection_status": "connected"
    })
    # Connection expiring soon
    await memory_repo.create_connection({
        "user_id": TEST_USER_ID, "refresh_token": "rt2", "email_address": "e2@test.com",
        "token_expires_at": (now + timedelta(minutes=3)).isoformat(),
        "connection_status": "connected"
    })
    # Healthy connection
    await memory_repo.create_connection({
        "user_id": uuid4(), "refresh_token": "rt3", "email_address": "e3@test.com",
        "token_expires_at": (now + timedelta(hours=1)).isoformat(),
        "connection_status": "connected"
    })

    # Act
    expiring_connections = await memory_repo.get_connections_needing_refresh(threshold_minutes=5)

    # Assert
    assert len(expiring_connections) == 2


# --- Statistics Test ---

@pytest.mark.asyncio
async def test_gmail_connection_stats(memory_repo: GmailRepository):
    """Verify the calculation of connection statistics."""
    # Arrange
    now = datetime.utcnow()
    # Data must be in string format, as it would be from the DB/in-memory store
    c1_data = {
        "user_id": uuid4(), "refresh_token": "rt1", "connection_status": "connected", 
        "created_at": (now - timedelta(days=10)).isoformat()
    }
    c2_data = {
        "user_id": uuid4(), "refresh_token": "rt2", "connection_status": "error", 
        "created_at": (now - timedelta(days=20)).isoformat()
    }
    c3_data = {
        "user_id": uuid4(), "refresh_token": "rt3", "connection_status": "connected", 
        "created_at": now.isoformat(), 
        "token_expires_at": (now + timedelta(seconds=100)).isoformat()
    }

    await memory_repo.create_connection(c1_data)
    await memory_repo.create_connection(c2_data)
    await memory_repo.create_connection(c3_data)

    # Act
    stats = await memory_repo.get_connection_stats()

    # Assert
    assert isinstance(stats, GmailConnectionStats)
    assert stats.total_connections == 3
    assert stats.active_connections == 2
    assert stats.error_connections == 1
    assert stats.connections_by_status == {"connected": 2, "error": 1}
    assert stats.tokens_expiring_soon == 1
    # (10 + 20 + 0) / 3 = 10.0
    assert stats.average_connection_age_days == 10.0
