import pytest
from uuid import uuid4
from datetime import datetime, timedelta
from typing import List, Dict, Any

# Import the repository and its domain models
from app.data.repositories.audit_repository import (
    AuditRepository,
    AuditLog,
    AuditSummary,
    SearchCriteria,
    EventType,
    SeverityLevel,
    ComplianceCategory,
)

# Import exceptions from the central source of truth
from app.core.exceptions import (
    AuditLogNotFoundError,
    InvalidEventTypeError,
    InvalidSeverityLevelError,
    AuditRetentionViolationError,
    ValidationError,
)

# --- Test Constants ---
USER_ID = str(uuid4())
ADMIN_ID = str(uuid4())
SESSION_ID = str(uuid4())
IP_ADDRESS = "192.168.1.100"


# --- Pytest Fixtures ---

@pytest.fixture
def audit_repo() -> AuditRepository:
    """Provides a fresh instance of the AuditRepository for each test."""
    return AuditRepository()


@pytest.fixture
def sample_log_data() -> dict:
    """Provides a reusable dictionary of valid audit log data."""
    return {
        "user_id": USER_ID,
        "event_type": EventType.USER_ACTION,
        "event_name": "user_login_success",
        "description": "User successfully logged in with password.",
        "severity": SeverityLevel.MEDIUM,
        "ip_address": IP_ADDRESS,
        "user_agent": "Mozilla/5.0",
        "session_id": SESSION_ID,
        "tags": ["authentication", "login"],
        "compliance_categories": [ComplianceCategory.SOC2],
        "resource_type": "user_session",
        "resource_id": USER_ID,
        "request_id": str(uuid4()),
        "timestamp": datetime.utcnow(),
        "metadata": {"login_method": "password"},
    }


@pytest.fixture
def multiple_log_data(sample_log_data: dict) -> List[dict]:
    """Provides a list of diverse audit logs for testing search and summary operations."""
    log1 = sample_log_data.copy()

    # FIX: Explicitly define the full dictionary for log2 and log3 to avoid
    # unintentionally copying the 'description' from sample_log_data.
    log2 = {
        "user_id": ADMIN_ID,
        "event_type": EventType.SECURITY_EVENT,
        "event_name": "permission_change",
        "description": "Admin granted new permissions to user.",
        "severity": SeverityLevel.HIGH,
        "ip_address": IP_ADDRESS,
        "user_agent": "Mozilla/5.0",
        "session_id": str(uuid4()),
        "tags": ["security", "iam"],
        "compliance_categories": [ComplianceCategory.SOX, ComplianceCategory.SOC2],
        "resource_type": "user_permissions",
        "resource_id": ADMIN_ID,
        "request_id": str(uuid4()),
        "timestamp": datetime.utcnow() - timedelta(days=1),
        "metadata": {"permissions_added": ["read", "write"]},
    }

    log3 = {
        "user_id": None, # System event
        "event_type": EventType.SYSTEM_EVENT,
        "event_name": "database_backup_failed",
        "description": "Nightly database backup failed.",
        "severity": SeverityLevel.CRITICAL,
        "ip_address": None,
        "user_agent": "system",
        "session_id": None,
        "tags": ["system", "backup", "failure"],
        "compliance_categories": [],
        "resource_type": "database",
        "resource_id": "primary_db",
        "request_id": str(uuid4()),
        "timestamp": datetime.utcnow() - timedelta(days=2),
        "metadata": {"reason": "connection_timeout"},
    }
    return [log1, log2, log3]


# --- Domain Model Tests ---

def test_audit_log_domain_model_properties():
    """Tests the computed properties of the AuditLog domain model."""
    base_data = {
        "id": str(uuid4()),
        "event_name": "test", "description": "test",
        "timestamp": datetime.utcnow(), "created_at": datetime.utcnow(),
        "user_id": None, "resource_type": None, "resource_id": None,
        "ip_address": None, "user_agent": None, "session_id": None,
        "request_id": None, "metadata": {}, "tags": [], "compliance_categories": [],
    }

    # Test a security-relevant log
    security_log = AuditLog.from_dict({
        **base_data,
        "event_type": EventType.SECURITY_EVENT,
        "severity": SeverityLevel.HIGH,
    })
    assert security_log.is_security_relevant is True
    assert security_log.requires_review is True

    # Test a non-security log that requires review due to severity
    critical_log = AuditLog.from_dict({
        **base_data,
        "event_type": EventType.SYSTEM_EVENT,
        "severity": SeverityLevel.CRITICAL,
        "reviewed": False,
    })
    assert critical_log.is_security_relevant is True # Because of severity
    assert critical_log.requires_review is True

    # Test a reviewed log
    reviewed_log = AuditLog.from_dict({
        **base_data,
        "event_type": EventType.SYSTEM_EVENT,
        "severity": SeverityLevel.CRITICAL,
        "reviewed": True,
    })
    assert reviewed_log.requires_review is False

def test_audit_summary_domain_model(multiple_log_data: List[dict]):
    """Tests the statistical calculations of the AuditSummary domain model."""
    logs = [AuditLog.from_dict({**data, "id": str(uuid4()), "created_at": datetime.utcnow()}) for data in multiple_log_data]
    summary = AuditSummary.from_logs(logs)

    assert summary.total_events == 3
    assert summary.events_by_type[EventType.USER_ACTION.value] == 1
    assert summary.events_by_type[EventType.SECURITY_EVENT.value] == 1
    assert summary.events_by_severity[SeverityLevel.MEDIUM.value] == 1
    assert summary.events_by_severity[SeverityLevel.CRITICAL.value] == 1
    assert summary.security_events == 2 # log2 (security type) and log3 (critical severity)
    assert summary.unreviewed_critical == 1
    assert summary.compliance_events[ComplianceCategory.SOC2.value] == 2


# --- Core CRUD and Validation Tests ---

@pytest.mark.asyncio
async def test_create_audit_log_success(audit_repo: AuditRepository, sample_log_data: dict):
    """Tests successful creation of a single audit log."""
    log = await audit_repo.create_audit_log(**sample_log_data)
    assert isinstance(log, AuditLog)
    assert log.user_id == USER_ID
    assert log.event_name == "user_login_success"

    # Verify it was stored
    stored_log = await audit_repo.get_audit_log(log.id)
    assert stored_log is not None
    assert stored_log.id == log.id

@pytest.mark.asyncio
async def test_create_bulk_logs_partial_failure(audit_repo: AuditRepository, sample_log_data: dict):
    """Tests that the bulk create operation gracefully handles invalid data."""
    valid_log = sample_log_data.copy()
    invalid_log = sample_log_data.copy()
    invalid_log["event_type"] = "invalid_type"
    
    logs_to_create = [valid_log, invalid_log]
    created_logs = await audit_repo.create_bulk_audit_logs(logs_to_create)
    
    assert len(created_logs) == 1
    assert await audit_repo.count_audit_logs() == 1

@pytest.mark.asyncio
async def test_create_audit_log_validation_error(audit_repo: AuditRepository):
    """Tests that creating an audit log with invalid data raises validation errors."""
    with pytest.raises(ValidationError, match="event_name is required"):
        await audit_repo.create_audit_log(
            user_id=USER_ID, event_type=EventType.USER_ACTION, event_name="", description="fail"
        )

    with pytest.raises(InvalidEventTypeError):
        await audit_repo.create_audit_log(
            user_id=USER_ID, event_type="invalid_type", event_name="test", description="fail"
        )

    with pytest.raises(InvalidSeverityLevelError):
        await audit_repo.create_audit_log(
            user_id=USER_ID, event_type=EventType.USER_ACTION, event_name="test", description="fail",
            severity="invalid_severity"
        )

@pytest.mark.asyncio
async def test_get_audit_log_not_found(audit_repo: AuditRepository):
    """Tests that getting a non-existent log returns None."""
    log = await audit_repo.get_audit_log(str(uuid4()))
    assert log is None

@pytest.mark.asyncio
async def test_update_audit_log_restricted(audit_repo: AuditRepository, sample_log_data: dict):
    """Tests that only specific, allowed fields can be updated on an audit log."""
    log = await audit_repo.create_audit_log(**sample_log_data)

    # Attempt to update a protected field
    updated_log = await audit_repo.update_audit_log(log.id, event_name="new_name", reviewed=True)
    
    # Verify the protected field was NOT changed, but the allowed one was
    assert updated_log.event_name == "user_login_success"
    assert updated_log.reviewed is True

@pytest.mark.asyncio
async def test_mark_audit_log_reviewed(audit_repo: AuditRepository, sample_log_data: dict):
    """Tests the convenience method for marking a log as reviewed."""
    log = await audit_repo.create_audit_log(**sample_log_data)
    assert log.reviewed is False

    reviewed_log = await audit_repo.mark_audit_log_reviewed(log.id, ADMIN_ID, "Looks normal.")
    assert reviewed_log.reviewed is True
    assert reviewed_log.reviewed_by == ADMIN_ID
    assert reviewed_log.review_notes == "Looks normal."
    assert reviewed_log.reviewed_at is not None

@pytest.mark.asyncio
async def test_delete_audit_log_retention_policy(audit_repo: AuditRepository, sample_log_data: dict):
    """Tests that the retention policy prevents deletion of recent logs."""
    log = await audit_repo.create_audit_log(**sample_log_data)
    
    with pytest.raises(AuditRetentionViolationError):
        await audit_repo.delete_audit_log(log.id)

@pytest.mark.asyncio
async def test_delete_audit_log_override(audit_repo: AuditRepository, sample_log_data: dict):
    """Tests that the retention policy can be overridden."""
    log = await audit_repo.create_audit_log(**sample_log_data)
    
    success = await audit_repo.delete_audit_log(log.id, retention_override=True)
    assert success is True
    assert await audit_repo.get_audit_log(log.id) is None

@pytest.mark.asyncio
async def test_delete_user_audit_logs(audit_repo: AuditRepository, multiple_log_data: list):
    """Tests the GDPR compliance feature of deleting all logs for a specific user."""
    await audit_repo.create_bulk_audit_logs(multiple_log_data)
    assert await audit_repo.count_audit_logs(SearchCriteria(user_id=USER_ID)) == 1
    
    deleted_count = await audit_repo.delete_user_audit_logs(USER_ID)
    assert deleted_count == 1
    assert await audit_repo.count_audit_logs(SearchCriteria(user_id=USER_ID)) == 0
    assert await audit_repo.count_audit_logs() == 2


# --- Search and Filtering Tests ---

@pytest.mark.asyncio
async def test_search_audit_logs_by_user(audit_repo: AuditRepository, multiple_log_data: list):
    """Tests searching for logs by a specific user ID."""
    await audit_repo.create_bulk_audit_logs(multiple_log_data)
    
    criteria = SearchCriteria(user_id=USER_ID)
    results = await audit_repo.search_audit_logs(criteria)
    assert len(results) == 1
    assert results[0].user_id == USER_ID

@pytest.mark.asyncio
async def test_search_audit_logs_no_results(audit_repo: AuditRepository):
    """Tests that a search with no matching criteria returns an empty list."""
    criteria = SearchCriteria(search_text="non_existent_term")
    results = await audit_repo.search_audit_logs(criteria)
    assert results == []

@pytest.mark.asyncio
async def test_search_audit_logs_by_severity_and_type(audit_repo: AuditRepository, multiple_log_data: list):
    """Tests searching with multiple criteria (severity and event type)."""
    await audit_repo.create_bulk_audit_logs(multiple_log_data)
    
    criteria = SearchCriteria(severity=SeverityLevel.HIGH, event_type=EventType.SECURITY_EVENT)
    results = await audit_repo.search_audit_logs(criteria)
    assert len(results) == 1
    assert results[0].user_id == ADMIN_ID

@pytest.mark.asyncio
async def test_search_audit_logs_with_time_range(audit_repo: AuditRepository, multiple_log_data: list):
    """Tests searching within a specific time window."""
    await audit_repo.create_bulk_audit_logs(multiple_log_data)
    
    # Search for logs in the last 90 minutes (should only be the first one)
    start_time = datetime.utcnow() - timedelta(minutes=90)
    criteria = SearchCriteria(start_time=start_time)
    results = await audit_repo.search_audit_logs(criteria)
    assert len(results) == 1
    assert results[0].event_name == "user_login_success"

@pytest.mark.asyncio
async def test_search_audit_logs_pagination_and_sorting(audit_repo: AuditRepository, multiple_log_data: list):
    """Tests that limit, offset, and sorting are applied correctly."""
    await audit_repo.create_bulk_audit_logs(multiple_log_data)
    
    # Get the second log when sorted by severity (descending)
    # Expected order: CRITICAL, HIGH, MEDIUM
    criteria = SearchCriteria(order_by="severity", descending=True, limit=1, offset=1)
    results = await audit_repo.search_audit_logs(criteria)
    
    assert len(results) == 1
    assert results[0].severity == SeverityLevel.HIGH

@pytest.mark.asyncio
async def test_search_audit_logs_by_tag_and_compliance(audit_repo: AuditRepository, multiple_log_data: list):
    """Tests searching by tags and compliance categories."""
    await audit_repo.create_bulk_audit_logs(multiple_log_data)

    # Search by tag
    tag_criteria = SearchCriteria(tags=["iam"])
    tag_results = await audit_repo.search_audit_logs(tag_criteria)
    assert len(tag_results) == 1
    assert tag_results[0].event_name == "permission_change"

    # Search by compliance category
    compliance_criteria = SearchCriteria(compliance_category=ComplianceCategory.SOX)
    compliance_results = await audit_repo.search_audit_logs(compliance_criteria)
    assert len(compliance_results) == 1
    assert compliance_results[0].user_id == ADMIN_ID

@pytest.mark.asyncio
async def test_search_audit_logs_by_text(audit_repo: AuditRepository, multiple_log_data: list):
    """Tests free-text search on description and event_name."""
    await audit_repo.create_bulk_audit_logs(multiple_log_data)

    # Search for a word in the description
    text_criteria = SearchCriteria(search_text="password")
    text_results = await audit_repo.search_audit_logs(text_criteria)
    assert len(text_results) == 1
    assert text_results[0].event_name == "user_login_success"

@pytest.mark.asyncio
async def test_count_audit_logs(audit_repo: AuditRepository, multiple_log_data: list):
    """Tests the count operation with search criteria."""
    created_logs = await audit_repo.create_bulk_audit_logs(multiple_log_data)
    assert len(created_logs) == 3, "Not all logs were created in the bulk operation."

    # Count all logs
    total_count = await audit_repo.count_audit_logs()
    assert total_count == 3

    # Count only security events
    security_criteria = SearchCriteria(event_type=EventType.SECURITY_EVENT)
    security_count = await audit_repo.count_audit_logs(security_criteria)
    assert security_count == 1


# --- Convenience Method Tests ---

@pytest.mark.asyncio
async def test_log_user_action(audit_repo: AuditRepository):
    """Tests the log_user_action convenience method."""
    log = await audit_repo.log_user_action(
        user_id=USER_ID,
        action="update_profile",
        resource="user_profile",
        details={"changed_fields": ["display_name"]},
        ip_address=IP_ADDRESS
    )
    assert log.event_type == EventType.USER_ACTION
    assert log.event_name == "user_update_profile"
    assert "update_profile" in log.tags
    assert log.ip_address == IP_ADDRESS

@pytest.mark.asyncio
async def test_log_security_event(audit_repo: AuditRepository):
    """Tests the log_security_event convenience method."""
    log = await audit_repo.log_security_event(
        event_name="failed_login_attempt",
        description="Multiple failed login attempts for user.",
        severity=SeverityLevel.HIGH,
        user_id=USER_ID,
        ip_address=IP_ADDRESS
    )
    assert log.event_type == EventType.SECURITY_EVENT
    assert log.severity == SeverityLevel.HIGH
    assert "security" in log.tags
    assert ComplianceCategory.SOC2 in log.compliance_categories

@pytest.mark.asyncio
async def test_log_system_event(audit_repo: AuditRepository):
    """Tests the log_system_event convenience method."""
    log = await audit_repo.log_system_event(
        event_name="cache_cleared",
        component="redis_cache",
        severity=SeverityLevel.LOW
    )
    assert log.event_type == EventType.SYSTEM_EVENT
    assert log.user_id is None
    assert log.severity == SeverityLevel.LOW
    assert "redis_cache" in log.tags


# --- Reporting and Maintenance Tests ---

@pytest.mark.asyncio
async def test_get_audit_summary(audit_repo: AuditRepository, multiple_log_data: list):
    """Tests the get_audit_summary reporting method."""
    await audit_repo.create_bulk_audit_logs(multiple_log_data)
    summary = await audit_repo.get_audit_summary()
    assert isinstance(summary, AuditSummary)
    assert summary.total_events == 3
    assert summary.unreviewed_critical == 1

@pytest.mark.asyncio
async def test_get_compliance_report(audit_repo: AuditRepository, multiple_log_data: list):
    """Tests the compliance report generation."""
    await audit_repo.create_bulk_audit_logs(multiple_log_data)
    report = await audit_repo.get_compliance_report(ComplianceCategory.SOC2, days=30)
    assert report["compliance_category"] == "soc2"
    assert report["total_events"] == 2
    assert report["security_events"] == 1

@pytest.mark.asyncio
async def test_get_unreviewed_critical_events(audit_repo: AuditRepository, multiple_log_data: list):
    """Tests fetching unreviewed critical events."""
    await audit_repo.create_bulk_audit_logs(multiple_log_data)
    
    # Mark one log as reviewed
    critical_log = (await audit_repo.search_audit_logs(SearchCriteria(severity=SeverityLevel.CRITICAL)))[0]
    await audit_repo.log_system_event("another_critical", "test", severity=SeverityLevel.CRITICAL)

    unreviewed = await audit_repo.get_unreviewed_critical_events()
    assert len(unreviewed) == 2

    # Now review one
    await audit_repo.mark_audit_log_reviewed(critical_log.id, ADMIN_ID)
    unreviewed_after = await audit_repo.get_unreviewed_critical_events()
    assert len(unreviewed_after) == 1

@pytest.mark.asyncio
async def test_delete_old_audit_logs_dry_run(audit_repo: AuditRepository):
    """Tests the dry_run functionality of the cleanup method."""
    # Create a very old log
    await audit_repo.create_audit_log(
        user_id=USER_ID, event_type=EventType.USER_ACTION, event_name="ancient_event",
        description="This is an old log.",
        timestamp=datetime.utcnow() - timedelta(days=4000)
    )
    # Create a recent log
    await audit_repo.create_audit_log(
        user_id=USER_ID, event_type=EventType.USER_ACTION, event_name="recent_event",
        description="This is a recent log."
    )

    # Perform a dry run to delete logs older than 365 days
    result = await audit_repo.delete_old_audit_logs(days=365, dry_run=True)
    assert result["dry_run"] is True
    assert result["deletable_count"] == 1
    
    # Verify no logs were actually deleted
    assert await audit_repo.count_audit_logs() == 2

@pytest.mark.asyncio
async def test_delete_old_audit_logs_execution(audit_repo: AuditRepository):
    """Tests the actual deletion of old logs."""
    # Create a very old log that can be deleted
    await audit_repo.create_audit_log(
        user_id=USER_ID, event_type=EventType.USER_ACTION, event_name="ancient_event",
        description="This is an old log.",
        timestamp=datetime.utcnow() - timedelta(days=3000) # Older than default retention
    )
    # Create a critical log that is old but protected by policy
    await audit_repo.create_audit_log(
        user_id=USER_ID, event_type=EventType.SECURITY_EVENT, event_name="protected_event",
        description="This log is old but protected.",
        severity=SeverityLevel.CRITICAL,
        timestamp=datetime.utcnow() - timedelta(days=3000) # Older than default, but not critical retention
    )

    # Perform the deletion
    result = await audit_repo.delete_old_audit_logs(days=365, dry_run=False)
    assert result["dry_run"] is False
    assert result["deleted_count"] == 1
    assert result["protected_count"] == 1
    
    # Verify one log was deleted
    assert await audit_repo.count_audit_logs() == 1


# --- Health Check Test ---

@pytest.mark.asyncio
async def test_health_check(audit_repo: AuditRepository):
    """Tests the health_check method."""
    health = await audit_repo.health_check()
    assert health["healthy"] is True
    assert health["storage_type"] == "in_memory"
