import pytest
from uuid import uuid4
from datetime import datetime, timedelta
from typing import Any, Dict, List

# Import the models and repository to be tested
from app.data.repositories.email_repository import (
    EmailRepository,
    EmailRecord,
    EmailStatus,
    ProcessingStats,
)
# Import the generic exceptions the repository is designed to use
from app.core.exceptions import (
    ValidationError,
    NotFoundError,
    EmailRecordExistsError,
    InvalidEmailStatusError,
    EmailRecordNotFoundError
)

# --- Test Constants ---
USER_ID = str(uuid4())
OTHER_USER_ID = str(uuid4())

# --- Simplified Fixtures ---

@pytest.fixture
def email_repo() -> EmailRepository:
    """
    Provides a clean, in-memory EmailRepository instance for each test,
    which is the ideal way to test this lean CRUD repository.
    """
    return EmailRepository()

@pytest.fixture
def sample_email_payload() -> Dict[str, Any]:
    """Provides a reusable dictionary of email data for creation."""
    return {
        "message_id": f"msg_{uuid4()}@example.com",
        "subject": "Test Email",
        "sender": "test@example.com",
    }

# --- CREATE Operation Tests ---

@pytest.mark.asyncio
async def test_create_email_record_success(email_repo: EmailRepository, sample_email_payload: Dict[str, Any]):
    """Tests successful creation and retrieval of a new email record."""
    record = await email_repo.create_email_record(user_id=USER_ID, **sample_email_payload)

    # Assert the returned object is correct
    assert isinstance(record, EmailRecord)
    assert record.user_id == USER_ID
    assert record.message_id == sample_email_payload["message_id"]
    assert record.status == EmailStatus.DISCOVERED

    # Verify it was saved correctly
    retrieved_record = await email_repo.get_email_record(USER_ID, sample_email_payload["message_id"])
    assert retrieved_record is not None
    assert retrieved_record.id == record.id

@pytest.mark.asyncio
@pytest.mark.parametrize("missing_field", ["user_id", "message_id"])
async def test_create_with_missing_required_fields_raises_error(email_repo: EmailRepository, sample_email_payload: Dict[str, Any], missing_field: str):
    """Tests that creating a record with missing required fields raises a ValidationError."""
    payload = sample_email_payload.copy()
    
    if missing_field == "user_id":
        with pytest.raises(ValidationError, match="user_id is required"):
            await email_repo.create_email_record(user_id="", **payload)
    else:
        # To test the internal validation, we pass an empty string, not omit the argument
        payload['message_id'] = ""
        with pytest.raises(ValidationError, match="message_id is required"):
            await email_repo.create_email_record(user_id=USER_ID, **payload)

@pytest.mark.asyncio
async def test_create_duplicate_raises_error(email_repo: EmailRepository, sample_email_payload: Dict[str, Any]):
    """Tests that creating a record with a duplicate message_id for the same user raises an error."""
    await email_repo.create_email_record(user_id=USER_ID, **sample_email_payload)
    with pytest.raises(EmailRecordExistsError):
        await email_repo.create_email_record(user_id=USER_ID, **sample_email_payload)

@pytest.mark.asyncio
async def test_create_with_invalid_discovery_method_raises_error(email_repo: EmailRepository, sample_email_payload: Dict[str, Any]):
    """Tests that creating a record with an invalid discovery_method raises a ValidationError."""
    with pytest.raises(ValidationError, match="Invalid discovery method"):
        await email_repo.create_email_record(user_id=USER_ID, discovery_method="invalid_method", **sample_email_payload)

# --- READ Operation Tests ---

@pytest.mark.asyncio
async def test_get_email_record_not_found(email_repo: EmailRepository):
    """Tests that get_email_record returns None for a non-existent record."""
    assert await email_repo.get_email_record(USER_ID, "non_existent@id.com") is None

@pytest.mark.asyncio
async def test_get_email_record_by_id_success(email_repo: EmailRepository, sample_email_payload: Dict[str, Any]):
    """Tests successful retrieval of a record by its internal ID."""
    created_record = await email_repo.create_email_record(user_id=USER_ID, **sample_email_payload)
    retrieved_record = await email_repo.get_email_record_by_id(created_record.id)
    assert retrieved_record is not None
    assert retrieved_record.id == created_record.id

@pytest.mark.asyncio
async def test_get_email_record_by_id_not_found(email_repo: EmailRepository):
    """Tests that get_email_record_by_id returns None for a non-existent ID."""
    non_existent_id = str(uuid4())
    assert await email_repo.get_email_record_by_id(non_existent_id) is None

@pytest.mark.asyncio
async def test_list_and_count_records(email_repo: EmailRepository):
    """Tests listing and counting records with various filters."""
    # Arrange: Create records, then update them to the desired status
    await email_repo.create_email_record(user_id=USER_ID, message_id="msg1") # Stays DISCOVERED
    await email_repo.create_email_record(user_id=USER_ID, message_id="msg2")
    await email_repo.create_email_record(user_id=USER_ID, message_id="msg3")
    await email_repo.create_email_record(user_id=OTHER_USER_ID, message_id="msg4")

    # Update statuses correctly using the public method
    await email_repo.update_email_record(USER_ID, "msg2", status=EmailStatus.COMPLETED)
    await email_repo.update_email_record(USER_ID, "msg3", status=EmailStatus.COMPLETED)

    # Test counts
    assert await email_repo.count_email_records(USER_ID) == 3
    assert await email_repo.count_email_records(USER_ID, status=EmailStatus.COMPLETED) == 2
    assert await email_repo.count_email_records(OTHER_USER_ID) == 1
    assert await email_repo.count_email_records("non_existent_user") == 0

    # Test lists
    all_records = await email_repo.list_email_records(USER_ID)
    assert len(all_records) == 3
    completed_records = await email_repo.list_email_records(USER_ID, status=EmailStatus.COMPLETED)
    assert len(completed_records) == 2

@pytest.mark.asyncio
async def test_list_email_records_pagination(email_repo: EmailRepository):
    """Tests the limit and offset parameters for pagination."""
    # Create 5 records
    for i in range(5):
        await email_repo.create_email_record(user_id=USER_ID, message_id=f"msg{i}")

    # Test limit
    limited_records = await email_repo.list_email_records(USER_ID, limit=3)
    assert len(limited_records) == 3

    # Test offset
    offset_records = await email_repo.list_email_records(USER_ID, offset=3)
    assert len(offset_records) == 2

    # Test limit and offset together
    paginated_records = await email_repo.list_email_records(USER_ID, limit=2, offset=1)
    assert len(paginated_records) == 2
    # The records are sorted by created_at desc, so offset=1 skips msg4, limit=2 gets msg3 and msg2
    assert paginated_records[0].message_id == "msg3"
    assert paginated_records[1].message_id == "msg2"

# --- UPDATE Operation Tests ---

@pytest.mark.asyncio
async def test_update_email_record_success(email_repo: EmailRepository, sample_email_payload: Dict[str, Any]):
    """Tests successfully updating various fields of an email record."""
    original_record = await email_repo.create_email_record(user_id=USER_ID, **sample_email_payload)
    
    updates = {
        "status": EmailStatus.PROCESSING,
        "metadata": {"processor_id": "proc_123"},
        "discovery_count": 5
    }
    updated_record = await email_repo.update_email_record(USER_ID, original_record.message_id, **updates)

    assert updated_record.status == EmailStatus.PROCESSING
    assert updated_record.metadata["processor_id"] == "proc_123"
    assert updated_record.discovery_count == 5
    assert updated_record.updated_at > original_record.updated_at

@pytest.mark.asyncio
async def test_update_non_existent_record_raises_error(email_repo: EmailRepository):
    """Tests that updating a non-existent record raises EmailRecordNotFoundError."""
    with pytest.raises(EmailRecordNotFoundError):
        await email_repo.update_email_record(USER_ID, "non_existent@id.com", status=EmailStatus.FAILED)

@pytest.mark.asyncio
async def test_update_with_invalid_status_raises_error(email_repo: EmailRepository, sample_email_payload: Dict[str, Any]):
    """Tests that providing an invalid status string during an update raises an error."""
    await email_repo.create_email_record(user_id=USER_ID, **sample_email_payload)
    with pytest.raises(InvalidEmailStatusError):
        await email_repo.update_email_record(USER_ID, sample_email_payload["message_id"], status="invalid_status")


@pytest.mark.asyncio
async def test_update_by_id_success(email_repo: EmailRepository, sample_email_payload: Dict[str, Any]):
    """Tests successfully updating a record using its internal ID."""
    record = await email_repo.create_email_record(user_id=USER_ID, **sample_email_payload)
    await email_repo.update_email_record_by_id(record.id, status=EmailStatus.FAILED)
    updated_record = await email_repo.get_email_record_by_id(record.id)
    assert updated_record.status == EmailStatus.FAILED

@pytest.mark.asyncio
async def test_update_by_id_not_found_raises_error(email_repo: EmailRepository):
    """Tests that updating a non-existent record by ID raises a NotFoundError."""
    non_existent_id = str(uuid4())
    with pytest.raises(NotFoundError):
        await email_repo.update_email_record_by_id(non_existent_id, status=EmailStatus.FAILED)

@pytest.mark.asyncio
async def test_bulk_update_success(email_repo: EmailRepository):
    """Tests the bulk update functionality."""
    rec1 = await email_repo.create_email_record(user_id=USER_ID, message_id="msg1")
    rec2 = await email_repo.create_email_record(user_id=USER_ID, message_id="msg2")
    
    updates_to_perform = [
        (rec1.message_id, {"status": EmailStatus.COMPLETED}),
        (rec2.message_id, {"status": EmailStatus.FAILED}),
        ("non_existent", {"status": EmailStatus.FAILED}) # Should be skipped
    ]
    
    result = await email_repo.bulk_update_email_records(USER_ID, updates_to_perform)
    assert len(result) == 2 # Only successful updates are returned

    updated_rec1 = await email_repo.get_email_record(USER_ID, rec1.message_id)
    assert updated_rec1.status == EmailStatus.COMPLETED

# --- DELETE Operation Tests ---

@pytest.mark.asyncio
async def test_delete_email_record_success(email_repo: EmailRepository, sample_email_payload: Dict[str, Any]):
    """Tests that a single email record can be successfully deleted."""
    await email_repo.create_email_record(user_id=USER_ID, **sample_email_payload)
    
    delete_result = await email_repo.delete_email_record(USER_ID, sample_email_payload["message_id"])
    assert delete_result is True
    assert await email_repo.count_email_records(USER_ID) == 0

@pytest.mark.asyncio
async def test_delete_non_existent_record_returns_false(email_repo: EmailRepository):
    """Tests that attempting to delete a non-existent record returns False."""
    delete_result = await email_repo.delete_email_record(USER_ID, "non_existent@id.com")
    assert delete_result is False

@pytest.mark.asyncio
async def test_delete_user_email_records(email_repo: EmailRepository):
    """Tests that all records for a specific user can be deleted, without affecting others."""
    await email_repo.create_email_record(user_id=USER_ID, message_id="msg1")
    await email_repo.create_email_record(user_id=USER_ID, message_id="msg2")
    await email_repo.create_email_record(user_id=OTHER_USER_ID, message_id="msg3")

    deleted_count = await email_repo.delete_user_email_records(USER_ID)
    assert deleted_count == 2
    assert await email_repo.count_email_records(USER_ID) == 0
    assert await email_repo.count_email_records(OTHER_USER_ID) == 1

@pytest.mark.asyncio
async def test_delete_user_email_records_for_non_existent_user(email_repo: EmailRepository):
    """Tests that deleting records for a user with no records returns 0."""
    deleted_count = await email_repo.delete_user_email_records("non_existent_user")
    assert deleted_count == 0

@pytest.mark.asyncio
async def test_delete_old_records(email_repo: EmailRepository):
    """Tests that the cleanup method for old records works correctly."""
    now = datetime.utcnow()
    
    # Old and completed, should be deleted
    rec1 = await email_repo.create_email_record(user_id=USER_ID, message_id="old_completed")
    # Manually update the dictionary for the in-memory test case
    record_id = email_repo._index[(USER_ID, rec1.message_id)]
    email_repo._records[record_id]['status'] = EmailStatus.COMPLETED.value
    email_repo._records[record_id]['processing_completed_at'] = now - timedelta(days=40)
    
    # Old but still processing, should NOT be deleted
    await email_repo.create_email_record(user_id=USER_ID, message_id="old_processing")

    # Recent and completed, should NOT be deleted
    rec3 = await email_repo.create_email_record(user_id=USER_ID, message_id="new_completed")
    record_id_3 = email_repo._index[(USER_ID, rec3.message_id)]
    email_repo._records[record_id_3]['status'] = EmailStatus.COMPLETED.value
    email_repo._records[record_id_3]['processing_completed_at'] = now - timedelta(days=10)


    deleted_count = await email_repo.delete_old_records(days=30)
    assert deleted_count == 1
    assert await email_repo.count_email_records(USER_ID) == 2

# --- Domain Model Tests ---

def _create_mock_record(status: EmailStatus, success: bool = None, credits: int = 0, time: float = 0.0) -> EmailRecord:
    """Helper function to create mock EmailRecord objects for stats testing."""
    now = datetime.utcnow()
    return EmailRecord(
        id=str(uuid4()),
        user_id=USER_ID,
        message_id=str(uuid4()),
        subject="", sender="", received_at=None, discovery_method="api_scan",
        metadata={},
        status=status,
        created_at=now,
        updated_at=now,
        discovery_count=1,
        discovered_at=now,
        processing_started_at=now,
        processing_completed_at=now,
        processing_attempts=1,
        processing_result={"credits_used": credits, "processing_time": time},
        last_retry_at=None,
        max_retries=3,
        success=success
    )

def test_processing_stats_from_records():
    """Tests the calculation logic of the ProcessingStats.from_records classmethod."""
    records = [
        _create_mock_record(EmailStatus.COMPLETED, success=True, credits=1, time=1.5),
        _create_mock_record(EmailStatus.COMPLETED, success=True, credits=2, time=2.5),
        _create_mock_record(EmailStatus.FAILED, success=False),
        _create_mock_record(EmailStatus.COMPLETED, success=False), # A failure case
        _create_mock_record(EmailStatus.PROCESSING), # Pending
        _create_mock_record(EmailStatus.DISCOVERED), # Pending
    ]

    stats = ProcessingStats.from_records(USER_ID, records)

    assert stats.user_id == USER_ID
    assert stats.total_discovered == 6
    assert stats.total_processed == 4  # 2 successful, 1 failed, 1 completed-but-failed
    assert stats.total_successful == 2
    assert stats.total_failed == 2
    assert stats.total_pending == 2
    assert stats.success_rate == 0.5  # 2 successful / 4 processed
    assert stats.total_credits_used == 3 # 1 + 2
    assert stats.average_processing_time == 2.0 # (1.5 + 2.5) / 2

def test_processing_stats_from_empty_records():
    """Tests that ProcessingStats handles an empty list of records gracefully."""
    stats = ProcessingStats.from_records(USER_ID, [])

    assert stats.user_id == USER_ID
    assert stats.total_discovered == 0
    assert stats.total_processed == 0
    assert stats.total_successful == 0
    assert stats.total_failed == 0
    assert stats.total_pending == 0
    assert stats.success_rate == 0.0
    assert stats.total_credits_used == 0
    assert stats.average_processing_time == 0.0

def test_processing_stats_with_no_processed_records():
    """Tests that success rate is 0 when no records have been processed."""
    records = [
        _create_mock_record(EmailStatus.DISCOVERED),
        _create_mock_record(EmailStatus.PROCESSING),
    ]
    stats = ProcessingStats.from_records(USER_ID, records)
    assert stats.total_processed == 0
    assert stats.success_rate == 0.0
    assert stats.average_processing_time == 0.0
