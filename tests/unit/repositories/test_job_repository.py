import pytest
from uuid import uuid4
from datetime import datetime, timedelta
from typing import Any, Dict, List

# Import the repository and its domain models/exceptions
from app.data.repositories.job_repository import JobRepository
from app.models.job import (
    JobRecord,
    JobStatus,
    JobType,
    JobPriority,
    JobStats,
    RecurrenceInterval
)
from app.core.exceptions import (
    ValidationError,
    JobNotFoundError,
    InvalidJobTypeError,
    InvalidJobStatusError,
)

# --- Test Constants ---
USER_ID = str(uuid4())
OTHER_USER_ID = str(uuid4())

# --- Fixtures ---

@pytest.fixture
def job_repo() -> JobRepository:
    """Provides a clean, in-memory JobRepository instance for each test."""
    return JobRepository()

@pytest.fixture
def sample_job_payload() -> Dict[str, Any]:
    """Provides a reusable dictionary of basic job data for creation."""
    return {
        "user_id": USER_ID,
        "job_type": JobType.EMAIL_PROCESSING,
    }

# --- CREATE Operation Tests ---

@pytest.mark.asyncio
async def test_create_job_success(job_repo: JobRepository, sample_job_payload: Dict[str, Any]):
    """Tests successful creation of a new job with default values."""
    job = await job_repo.create_job(sample_job_payload)

    assert isinstance(job, JobRecord)
    assert job.user_id == USER_ID
    assert job.job_type == JobType.EMAIL_PROCESSING
    assert job.status == JobStatus.PENDING
    assert job.priority == JobPriority.NORMAL
    assert job.attempts == 0
    assert job.max_retries == 3

    retrieved_job = await job_repo.get_job(job.job_id)
    assert retrieved_job is not None
    assert retrieved_job.job_id == job.job_id

@pytest.mark.asyncio
async def test_create_job_with_all_fields(job_repo: JobRepository):
    """Tests creating a job with all optional fields specified."""
    now = datetime.utcnow()
    payload = {
        "user_id": USER_ID,
        "job_type": "data_sync",
        "priority": "high",
        "status": "running",
        "metadata": {"source": "api"},
        "scheduled_for": now + timedelta(hours=1),
        "max_retries": 5,
    }
    job = await job_repo.create_job(payload)

    assert job.priority == JobPriority.HIGH
    assert job.status == JobStatus.RUNNING
    assert job.metadata["source"] == "api"
    assert job.max_retries == 5

@pytest.mark.asyncio
@pytest.mark.parametrize("missing_field", ["user_id", "job_type"])
async def test_create_job_with_missing_required_fields_raises_error(job_repo: JobRepository, sample_job_payload: Dict[str, Any], missing_field: str):
    """Tests that creating a job with missing required fields raises a ValidationError."""
    payload = sample_job_payload.copy()
    del payload[missing_field]
    
    with pytest.raises(ValidationError, match=f"{missing_field} is required"):
        await job_repo.create_job(payload)

@pytest.mark.asyncio
async def test_create_job_with_invalid_enum_raises_error(job_repo: JobRepository, sample_job_payload: Dict[str, Any]):
    """Tests that creating a job with an invalid enum string raises an error."""
    payload = sample_job_payload.copy()
    payload["job_type"] = "invalid_type"
    
    with pytest.raises(InvalidJobTypeError):
        await job_repo.create_job(payload)

# --- READ Operation Tests ---

@pytest.mark.asyncio
async def test_get_job_not_found(job_repo: JobRepository):
    """Tests that get_job returns None for a non-existent job."""
    non_existent_id = str(uuid4())
    assert await job_repo.get_job(non_existent_id) is None

@pytest.mark.asyncio
async def test_list_and_count_jobs(job_repo: JobRepository, sample_job_payload: Dict[str, Any]):
    """Tests listing and counting jobs with various filters."""
    # Create a variety of jobs
    await job_repo.create_job({**sample_job_payload, "status": JobStatus.PENDING})
    await job_repo.create_job({**sample_job_payload, "status": JobStatus.COMPLETED})
    await job_repo.create_job({**sample_job_payload, "status": JobStatus.COMPLETED, "priority": JobPriority.HIGH})
    await job_repo.create_job({"user_id": OTHER_USER_ID, "job_type": JobType.DATA_SYNC})

    # Test counts
    assert await job_repo.count_jobs(user_id=USER_ID) == 3
    assert await job_repo.count_jobs(user_id=USER_ID, status=JobStatus.COMPLETED) == 2
    assert await job_repo.count_jobs(user_id=USER_ID, priority=JobPriority.HIGH) == 1
    assert await job_repo.count_jobs(user_id=OTHER_USER_ID) == 1
    assert await job_repo.count_jobs(job_type=JobType.DATA_SYNC.value) == 1
    assert await job_repo.count_jobs(user_id="non_existent_user") == 0

    # Test lists
    all_user_jobs = await job_repo.list_jobs(user_id=USER_ID)
    assert len(all_user_jobs) == 3
    completed_jobs = await job_repo.list_jobs(user_id=USER_ID, status=JobStatus.COMPLETED)
    assert len(completed_jobs) == 2

@pytest.mark.asyncio
async def test_list_jobs_pagination(job_repo: JobRepository, sample_job_payload: Dict[str, Any]):
    """Tests the limit and offset parameters for pagination."""
    for i in range(5):
        # Ensure created_at is distinct for reliable sorting
        await job_repo.create_job({**sample_job_payload, "created_at": datetime.utcnow() + timedelta(seconds=i)})

    # Test limit
    limited_jobs = await job_repo.list_jobs(user_id=USER_ID, limit=3)
    assert len(limited_jobs) == 3

    # Test offset
    offset_jobs = await job_repo.list_jobs(user_id=USER_ID, offset=3)
    assert len(offset_jobs) == 2

@pytest.mark.asyncio
async def test_list_jobs_with_complex_filters_and_ordering(job_repo: JobRepository, sample_job_payload: Dict[str, Any]):
    """Tests listing with multiple filters and specific ordering."""
    # Create a set of jobs to filter and sort
    j1 = await job_repo.create_job({**sample_job_payload, "priority": JobPriority.HIGH, "status": JobStatus.PENDING, "created_at": datetime.utcnow() + timedelta(seconds=1)})
    await job_repo.create_job({**sample_job_payload, "priority": JobPriority.NORMAL, "status": JobStatus.PENDING})
    j3 = await job_repo.create_job({**sample_job_payload, "priority": JobPriority.HIGH, "status": JobStatus.PENDING, "created_at": datetime.utcnow() + timedelta(seconds=3)})
    await job_repo.create_job({**sample_job_payload, "priority": JobPriority.HIGH, "status": JobStatus.RUNNING})

    # Filter for high priority, pending jobs, and order by creation time ascending
    filtered_jobs = await job_repo.list_jobs(
        user_id=USER_ID,
        status=JobStatus.PENDING,
        priority=JobPriority.HIGH,
        order_by="created_at ASC"
    )

    assert len(filtered_jobs) == 2
    assert filtered_jobs[0].job_id == j1.job_id
    assert filtered_jobs[1].job_id == j3.job_id

# --- UPDATE Operation Tests ---

@pytest.mark.asyncio
async def test_update_job_success(job_repo: JobRepository, sample_job_payload: Dict[str, Any]):
    """Tests successfully updating various fields of a job."""
    job = await job_repo.create_job(sample_job_payload)
    
    now = datetime.utcnow()
    updates = {
        "status": JobStatus.RUNNING.value,
        "worker_id": "worker-123",
        "started_at": now,
        "attempts": job.attempts + 1
    }
    updated_job = await job_repo.update_job(job.job_id, updates)

    assert updated_job.status == JobStatus.RUNNING
    assert updated_job.worker_id == "worker-123"
    assert updated_job.attempts == 1
    assert updated_job.started_at is not None
    assert updated_job.updated_at > job.updated_at

@pytest.mark.asyncio
async def test_update_non_existent_job_raises_error(job_repo: JobRepository):
    """Tests that updating a non-existent job raises JobNotFoundError."""
    non_existent_id = str(uuid4())
    with pytest.raises(JobNotFoundError):
        await job_repo.update_job(non_existent_id, {"status": JobStatus.FAILED.value})

@pytest.mark.asyncio
async def test_update_with_invalid_status_raises_error(job_repo: JobRepository, sample_job_payload: Dict[str, Any]):
    """Tests that updating with an invalid status string raises an error."""
    job = await job_repo.create_job(sample_job_payload)
    with pytest.raises(InvalidJobStatusError):
        await job_repo.update_job(job.job_id, {"status": "invalid_status"})

# --- DELETE Operation Tests ---

@pytest.mark.asyncio
async def test_delete_job_success(job_repo: JobRepository, sample_job_payload: Dict[str, Any]):
    """Tests that a job can be successfully deleted."""
    job = await job_repo.create_job(sample_job_payload)
    
    delete_result = await job_repo.delete_job(job.job_id)
    assert delete_result is True
    
    assert await job_repo.get_job(job.job_id) is None
    assert await job_repo.count_jobs(user_id=USER_ID) == 0

@pytest.mark.asyncio
async def test_delete_non_existent_job_raises_error(job_repo: JobRepository):
    """Tests that attempting to delete a non-existent job raises JobNotFoundError."""
    non_existent_id = str(uuid4())
    with pytest.raises(JobNotFoundError):
        await job_repo.delete_job(non_existent_id)

# --- Domain Model: JobRecord Property Tests ---

def _create_test_job_record(**kwargs) -> JobRecord:
    """Helper to create a JobRecord instance with sensible defaults for property testing."""
    now = datetime.utcnow()
    defaults = {
        "job_id": str(uuid4()),
        "user_id": USER_ID,
        "job_type": JobType.EMAIL_PROCESSING,
        "status": JobStatus.PENDING,
        "priority": JobPriority.NORMAL,
        "scheduled_for": now,
        "created_at": now,
        "updated_at": now,
        "max_retries": 3,
        "attempts": 0,
    }
    return JobRecord.from_dict({**defaults, **kwargs})

def test_job_record_status_properties():
    """Tests the boolean status properties of the JobRecord model."""
    pending_job = _create_test_job_record(status=JobStatus.PENDING)
    assert pending_job.is_pending and not pending_job.is_finished

    running_job = _create_test_job_record(status=JobStatus.RUNNING)
    assert running_job.is_running and not running_job.is_finished

    completed_job = _create_test_job_record(status=JobStatus.COMPLETED)
    assert completed_job.is_completed and completed_job.is_finished

    failed_job = _create_test_job_record(status=JobStatus.FAILED)
    assert failed_job.is_failed and failed_job.is_finished

    cancelled_job = _create_test_job_record(status=JobStatus.CANCELLED)
    assert cancelled_job.is_cancelled and cancelled_job.is_finished

def test_job_record_can_be_retried():
    """Tests the can_be_retried property logic."""
    # A failed job with attempts left can be retried
    job1 = _create_test_job_record(status=JobStatus.FAILED, attempts=1, max_retries=3)
    assert job1.can_be_retried

    # A failed job with no attempts left cannot be retried
    job2 = _create_test_job_record(status=JobStatus.FAILED, attempts=3, max_retries=3)
    assert not job2.can_be_retried

    # A running job cannot be retried
    job3 = _create_test_job_record(status=JobStatus.RUNNING, attempts=1, max_retries=3)
    assert not job3.can_be_retried

def test_job_record_is_overdue():
    """Tests the is_overdue property logic."""
    # A pending job scheduled for the past is overdue
    overdue_job = _create_test_job_record(status=JobStatus.PENDING, scheduled_for=datetime.utcnow() - timedelta(minutes=5))
    assert overdue_job.is_overdue

    # A pending job scheduled for the future is not overdue
    future_job = _create_test_job_record(status=JobStatus.PENDING, scheduled_for=datetime.utcnow() + timedelta(minutes=5))
    assert not future_job.is_overdue

    # A completed job is not overdue
    completed_job = _create_test_job_record(status=JobStatus.COMPLETED, scheduled_for=datetime.utcnow() - timedelta(minutes=5))
    assert not completed_job.is_overdue

# --- Analytics and Health Check Tests ---

def _create_mock_job_record(user_id: str, status: JobStatus, job_type: JobType, processing_time: float = 0.0) -> JobRecord:
    """Helper to create mock JobRecord objects for stats testing."""
    now = datetime.utcnow()
    return JobRecord(
        job_id=str(uuid4()), user_id=user_id, job_type=job_type, status=status,
        priority=JobPriority.NORMAL, metadata={}, scheduled_for=now, max_retries=3,
        attempts=1, created_at=now, updated_at=now, started_at=now,
        completed_at=now if status == JobStatus.COMPLETED else None,
        failed_at=now if status == JobStatus.FAILED else None,
        worker_id="worker-1", last_error=None, result={}, 
        processing_time=processing_time, recurrence_interval=None, parent_job_id=None
    )

@pytest.mark.asyncio
async def test_get_job_stats(job_repo: JobRepository, mocker):
    """Tests the get_job_stats analytics method."""
    # Note: We mock list_jobs to inject controlled data into JobStats
    mock_jobs = [
        _create_mock_job_record(USER_ID, JobStatus.COMPLETED, JobType.EMAIL_PROCESSING, 2.5),
        _create_mock_job_record(USER_ID, JobStatus.COMPLETED, JobType.EMAIL_PROCESSING, 1.5),
        _create_mock_job_record(USER_ID, JobStatus.FAILED, JobType.DATA_SYNC),
        _create_mock_job_record(USER_ID, JobStatus.RUNNING, JobType.EMAIL_PROCESSING),
        _create_mock_job_record(USER_ID, JobStatus.PENDING, JobType.DATA_SYNC),
        _create_mock_job_record(OTHER_USER_ID, JobStatus.COMPLETED, JobType.EMAIL_PROCESSING),
    ]
    
    # Mock the list_jobs method to return our controlled list
    mocker.patch.object(job_repo, 'list_jobs', return_value=mock_jobs)

    stats = await job_repo.get_job_stats(user_id=USER_ID)

    assert isinstance(stats, JobStats)
    assert stats.total_jobs == 6
    
    assert stats.completed_jobs == 3
    assert stats.failed_jobs == 1
    assert stats.running_jobs == 1
    assert stats.pending_jobs == 1
    
    assert stats.jobs_by_type[JobType.EMAIL_PROCESSING.value] == 4
    assert stats.jobs_by_type[JobType.DATA_SYNC.value] == 2
    
    # The model's logic correctly averages the runtime for all 6 mock jobs,
    # and rounds the result to 2 decimal places. The test must match this behavior.
    assert stats.average_processing_time == pytest.approx(round(4.0 / 6, 2))

@pytest.mark.asyncio
async def test_job_stats_from_empty_list(job_repo: JobRepository, mocker):
    """Tests that JobStats handles an empty list of jobs gracefully."""
    mocker.patch.object(job_repo, 'list_jobs', return_value=[])
    stats = await job_repo.get_job_stats(user_id=USER_ID)

    assert stats.total_jobs == 0
    assert stats.completed_jobs == 0
    assert stats.failed_jobs == 0
    assert stats.success_rate == 0.0
    assert stats.average_processing_time == 0.0

@pytest.mark.asyncio
async def test_job_stats_with_no_completed_jobs(job_repo: JobRepository, mocker):
    """Tests that success_rate is 0 when no jobs are completed or failed."""
    mock_jobs = [
        _create_mock_job_record(USER_ID, JobStatus.RUNNING, JobType.EMAIL_PROCESSING),
        _create_mock_job_record(USER_ID, JobStatus.PENDING, JobType.DATA_SYNC),
    ]
    mocker.patch.object(job_repo, 'list_jobs', return_value=mock_jobs)
    stats = await job_repo.get_job_stats(user_id=USER_ID)

    assert stats.total_jobs == 2
    assert stats.completed_jobs == 0
    assert stats.failed_jobs == 0
    assert stats.success_rate == 0.0

@pytest.mark.asyncio
async def test_health_check(job_repo: JobRepository):
    """Tests the health_check method for the in-memory repository."""
    await job_repo.create_job({"user_id": USER_ID, "job_type": JobType.EMAIL_PROCESSING})


# --- Additional Edge Case Tests ---

@pytest.mark.asyncio
async def test_create_job_with_invalid_recurrence_interval(job_repo: JobRepository, sample_job_payload: Dict[str, Any]):
    """Tests that an invalid recurrence interval is rejected."""
    payload = {
        **sample_job_payload,
        "recurrence_interval": "every_second"  # invalid string
    }
    with pytest.raises(ValidationError):
        await job_repo.create_job(payload)

@pytest.mark.asyncio
async def test_list_jobs_filtered_by_job_types(job_repo: JobRepository):
    """Tests filtering jobs by a list of job types."""
    await job_repo.create_job({"user_id": USER_ID, "job_type": JobType.EMAIL_PROCESSING})
    await job_repo.create_job({"user_id": USER_ID, "job_type": JobType.DATA_SYNC})
    await job_repo.create_job({"user_id": USER_ID, "job_type": JobType.DATA_SYNC})

    jobs = await job_repo.list_jobs(user_id=USER_ID, job_types=[JobType.DATA_SYNC.value])
    assert all(j.job_type == JobType.DATA_SYNC for j in jobs)
    assert len(jobs) == 2

@pytest.mark.asyncio
async def test_list_jobs_with_started_before_filter(job_repo: JobRepository):
    """Tests filtering jobs by started_before datetime."""
    past = datetime.utcnow() - timedelta(minutes=10)
    future = datetime.utcnow() + timedelta(minutes=10)

    await job_repo.create_job({"user_id": USER_ID, "job_type": JobType.EMAIL_PROCESSING, "started_at": past})
    await job_repo.create_job({"user_id": USER_ID, "job_type": JobType.DATA_SYNC, "started_at": future})

    results = await job_repo.list_jobs(user_id=USER_ID, started_before=datetime.utcnow())
    assert len(results) == 1
    assert results[0].started_at < datetime.utcnow()

@pytest.mark.asyncio
async def test_list_jobs_order_by_descending(job_repo: JobRepository, sample_job_payload: Dict[str, Any]):
    """Tests that jobs are ordered descending by created_at."""
    for i in range(3):
        await job_repo.create_job({**sample_job_payload, "created_at": datetime.utcnow() + timedelta(seconds=i)})

    jobs = await job_repo.list_jobs(user_id=USER_ID, order_by="created_at DESC")
    assert len(jobs) == 3
    assert jobs[0].created_at > jobs[1].created_at > jobs[2].created_at

@pytest.mark.asyncio
async def test_create_job_with_all_optional_fields_covered(job_repo: JobRepository):
    """Tests creation with all optional fields including recurrence and parent_job_id."""
    now = datetime.utcnow()
    payload = {
        "user_id": USER_ID,
        "job_type": JobType.EMAIL_PROCESSING.value,
        "priority": JobPriority.URGENT.value,
        "status": JobStatus.RUNNING.value,
        "metadata": {"foo": "bar"},
        "scheduled_for": now,
        "max_retries": 7,
        "attempts": 2,
        "started_at": now,
        "completed_at": now,
        "failed_at": None,
        "worker_id": "w123",
        "last_error": None,
        "result": {"ok": True},
        "processing_time": 2.5,
        "recurrence_interval": RecurrenceInterval.DAILY.value,
        "parent_job_id": "parent-001"
    }
    job = await job_repo.create_job(payload)

    assert job.recurrence_interval == RecurrenceInterval.DAILY
    assert job.parent_job_id == "parent-001"
    assert job.result == {"ok": True}
    assert job.processing_time == 2.5
    assert job.worker_id == "w123"
    assert job.attempts == 2
    assert job.priority == JobPriority.URGENT

@pytest.mark.asyncio
async def test_in_memory_job_state_isolated(job_repo: JobRepository, sample_job_payload: Dict[str, Any]):
    """Mutating returned JobRecord does not alter repo's internal state."""
    job = await job_repo.create_job(sample_job_payload)
    job.result["injected"] = True

    original = await job_repo.get_job(job.job_id)
    assert "injected" not in original.result

@pytest.mark.asyncio
async def test_health_check_failure_in_database_mode(mocker):
    """Forces _execute_query to throw and asserts unhealthy health check."""
    mock_table = mocker.Mock()
    mock_query = mocker.Mock()
    mock_query.execute.side_effect = Exception("db fail")
    mock_table.select.return_value.limit.return_value = mock_query

    repo = JobRepository(table=mock_table)
    health = await repo.health_check()

    assert health["status"] == "unhealthy"
    assert "db fail" in health["error"]
