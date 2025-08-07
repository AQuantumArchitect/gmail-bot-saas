import logging
from datetime import datetime, timedelta
from uuid import uuid4
from typing import Any, Dict, List, Optional, Protocol
from dataclasses import dataclass, asdict
from enum import Enum

from app.core.exceptions import (
    ValidationError,
    NotFoundError,
    DatabaseError,
    AuditLogNotFoundError,
    InvalidEventTypeError,
    InvalidSeverityLevelError,
    InvalidComplianceCategoryError,
    AuditRetentionViolationError,
)

logger = logging.getLogger(__name__)


# ========== DOMAIN MODELS ==========

class EventType(Enum):
    """Audit event type enumeration"""
    USER_ACTION = "user_action"
    SYSTEM_EVENT = "system_event"
    SECURITY_EVENT = "security_event"
    DATA_ACCESS = "data_access"
    DATA_MODIFICATION = "data_modification"
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    API_REQUEST = "api_request"
    CONFIGURATION_CHANGE = "configuration_change"
    ERROR_EVENT = "error_event"
    COMPLIANCE_EVENT = "compliance_event"


class SeverityLevel(Enum):
    """Audit severity level enumeration"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ComplianceCategory(Enum):
    """Compliance category enumeration"""
    GDPR = "gdpr"
    SOX = "sox"
    HIPAA = "hipaa"
    PCI_DSS = "pci_dss"
    SOC2 = "soc2"
    GENERAL = "general"


@dataclass
class AuditLog:
    """Domain model for audit log entries"""
    id: str
    user_id: Optional[str]
    event_type: EventType
    event_name: str
    description: str
    severity: SeverityLevel
    resource_type: Optional[str]
    resource_id: Optional[str]
    ip_address: Optional[str]
    user_agent: Optional[str]
    session_id: Optional[str]
    request_id: Optional[str]
    metadata: Dict[str, Any]
    tags: List[str]
    compliance_categories: List[ComplianceCategory]
    timestamp: datetime
    created_at: datetime
    reviewed: bool = False
    review_notes: Optional[str] = None
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AuditLog":
        """Create AuditLog from dictionary"""
        # --- START OF FIX ---
        # Operate on a copy to prevent mutating the original data in the repository.
        data = data.copy()
        # --- END OF FIX ---

        # Handle datetime conversion
        for field in ["timestamp", "created_at", "reviewed_at"]:
            if field in data and data[field]:
                if isinstance(data[field], str):
                    data[field] = datetime.fromisoformat(data[field])

        # Handle enum conversion
        if "event_type" in data and isinstance(data["event_type"], str):
            data["event_type"] = EventType(data["event_type"])
        
        if "severity" in data and isinstance(data["severity"], str):
            data["severity"] = SeverityLevel(data["severity"])

        # Handle compliance categories list
        if "compliance_categories" in data:
            categories = data["compliance_categories"]
            if isinstance(categories, list):
                data["compliance_categories"] = [
                    ComplianceCategory(cat) if isinstance(cat, str) else cat
                    for cat in categories
                ]
        else:
            data["compliance_categories"] = []

        # Handle optional fields
        if "tags" not in data:
            data["tags"] = []
        if "metadata" not in data:
            data["metadata"] = {}

        return cls(**data)

    def to_dict(self) -> Dict[str, Any]:
        """Convert AuditLog to dictionary"""
        data = asdict(self)
        
        # Convert datetime to ISO strings
        for field in ["timestamp", "created_at", "reviewed_at"]:
            if data[field]:
                data[field] = data[field].isoformat() if isinstance(data[field], datetime) else data[field]
        
        # Convert enums to strings
        data["event_type"] = data["event_type"].value if isinstance(data["event_type"], EventType) else data["event_type"]
        data["severity"] = data["severity"].value if isinstance(data["severity"], SeverityLevel) else data["severity"]
        
        # Convert compliance categories
        data["compliance_categories"] = [
            cat.value if isinstance(cat, ComplianceCategory) else cat
            for cat in data["compliance_categories"]
        ]
        
        return data

    @property
    def age_hours(self) -> float:
        """Get age of audit log in hours"""
        return (datetime.utcnow() - self.timestamp).total_seconds() / 3600

    @property
    def is_security_relevant(self) -> bool:
        """Check if audit log is security relevant"""
        return (self.event_type == EventType.SECURITY_EVENT or
                self.severity in [SeverityLevel.HIGH, SeverityLevel.CRITICAL] or
                "security" in self.tags)

    @property
    def requires_review(self) -> bool:
        """Check if audit log requires manual review"""
        return (not self.reviewed and 
                (self.severity in [SeverityLevel.HIGH, SeverityLevel.CRITICAL] or
                 self.is_security_relevant))


@dataclass
class AuditSummary:
    """Domain model for audit summary statistics"""
    total_events: int
    events_by_type: Dict[str, int]
    events_by_severity: Dict[str, int]
    events_by_user: Dict[str, int]
    security_events: int
    unreviewed_critical: int
    compliance_events: Dict[str, int]
    time_range: Dict[str, Optional[str]]
    generated_at: datetime

    @classmethod
    def from_logs(
        cls, 
        logs: List[AuditLog], 
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> "AuditSummary":
        """Generate summary from audit logs"""
        total_events = len(logs)
        
        if total_events == 0:
            return cls(
                total_events=0,
                events_by_type={},
                events_by_severity={},
                events_by_user={},
                security_events=0,
                unreviewed_critical=0,
                compliance_events={},
                time_range={
                    "start": start_time.isoformat() if start_time else None,
                    "end": end_time.isoformat() if end_time else None
                },
                generated_at=datetime.utcnow()
            )

        # Count by event type
        events_by_type = {}
        for log in logs:
            event_type = log.event_type.value
            events_by_type[event_type] = events_by_type.get(event_type, 0) + 1

        # Count by severity
        events_by_severity = {}
        for log in logs:
            severity = log.severity.value
            events_by_severity[severity] = events_by_severity.get(severity, 0) + 1

        # Count by user
        events_by_user = {}
        for log in logs:
            user_id = log.user_id or "system"
            events_by_user[user_id] = events_by_user.get(user_id, 0) + 1

        # Security events
        security_events = len([log for log in logs if log.is_security_relevant])

        # Unreviewed critical
        unreviewed_critical = len([
            log for log in logs 
            if not log.reviewed and log.severity == SeverityLevel.CRITICAL
        ])

        # Compliance events
        compliance_events = {}
        for log in logs:
            for category in log.compliance_categories:
                cat_name = category.value
                compliance_events[cat_name] = compliance_events.get(cat_name, 0) + 1

        return cls(
            total_events=total_events,
            events_by_type=events_by_type,
            events_by_severity=events_by_severity,
            events_by_user=events_by_user,
            security_events=security_events,
            unreviewed_critical=unreviewed_critical,
            compliance_events=compliance_events,
            time_range={
                "start": start_time.isoformat() if start_time else logs[-1].timestamp.isoformat(),
                "end": end_time.isoformat() if end_time else logs[0].timestamp.isoformat()
            },
            generated_at=datetime.utcnow()
        )


@dataclass
class SearchCriteria:
    """Domain model for audit log search criteria"""
    user_id: Optional[str] = None
    event_type: Optional[EventType] = None
    event_name: Optional[str] = None
    severity: Optional[SeverityLevel] = None
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    ip_address: Optional[str] = None
    session_id: Optional[str] = None
    tags: Optional[List[str]] = None
    compliance_category: Optional[ComplianceCategory] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    search_text: Optional[str] = None
    reviewed: Optional[bool] = None
    limit: Optional[int] = None
    offset: int = 0
    order_by: str = "timestamp"
    descending: bool = True


# ========== DATABASE PROTOCOLS ==========

class DatabaseTable(Protocol):
    """Protocol for database table operations"""
    def insert(self, data: Dict[str, Any]) -> "QueryBuilder": ...
    def select(self, columns: str = "*") -> "QueryBuilder": ...
    def update(self, data: Dict[str, Any]) -> "QueryBuilder": ...
    def delete(self) -> "QueryBuilder": ...


class QueryBuilder(Protocol):
    """Protocol for query builder operations"""
    def eq(self, column: str, value: Any) -> "QueryBuilder": ...
    def limit(self, count: int) -> "QueryBuilder": ...
    def offset(self, count: int) -> "QueryBuilder": ...
    def order(self, column: str, desc: bool = False) -> "QueryBuilder": ...
    def select(self, columns: str = "*") -> "QueryBuilder": ...
    def execute(self) -> "QueryResponse": ...


class QueryResponse(Protocol):
    """Protocol for query response"""
    data: List[Dict[str, Any]]
    error: Optional[Exception]
    count: Optional[int]


# ========== REPOSITORY ==========

class AuditRepository:
    """
    Enterprise-grade audit repository with domain models and async operations.
    Provides comprehensive audit logging, compliance features, and security monitoring.
    """

    # Valid configuration values
    VALID_EVENT_TYPES = {event_type.value for event_type in EventType}
    VALID_SEVERITY_LEVELS = {severity.value for severity in SeverityLevel}
    VALID_COMPLIANCE_CATEGORIES = {category.value for category in ComplianceCategory}
    
    # Compliance settings
    DEFAULT_RETENTION_DAYS = 2555  # 7 years for SOX compliance
    GDPR_RETENTION_DAYS = 1095     # 3 years for GDPR
    CRITICAL_EVENT_RETENTION_DAYS = 3650  # 10 years for critical events

    def __init__(self, table: Optional[DatabaseTable] = None):
        """
        Initialize repository with optional table dependency for testing.
        If no table provided, uses in-memory storage.
        """
        if table is not None:
            self.table = table
            self._use_database = True
        else:
            # In-memory storage for development/testing
            self._audit_logs: Dict[str, Dict[str, Any]] = {}
            # Indexes for efficient querying
            self._user_index: Dict[str, List[str]] = {}
            self._event_type_index: Dict[str, List[str]] = {}
            self._severity_index: Dict[str, List[str]] = {}
            self._tag_index: Dict[str, List[str]] = {}
            self._use_database = False

    # ========== CREATE OPERATIONS ==========

    async def create_audit_log(
        self,
        user_id: Optional[str],
        event_type: EventType,
        event_name: str,
        description: str,
        severity: SeverityLevel = SeverityLevel.MEDIUM,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        session_id: Optional[str] = None,
        request_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
        compliance_categories: Optional[List[ComplianceCategory]] = None,
        timestamp: Optional[datetime] = None,
        **kwargs
    ) -> AuditLog:
        """
        Create a new audit log entry.
        Core CREATE operation with comprehensive validation.
        """
        # Validation
        if not event_name:
            raise ValidationError("event_name is required")
        if not description:
            raise ValidationError("description is required")

        # Validate enums
        if isinstance(event_type, str):
            if event_type not in self.VALID_EVENT_TYPES:
                raise InvalidEventTypeError(event_type, list(self.VALID_EVENT_TYPES))
            event_type = EventType(event_type)

        if isinstance(severity, str):
            if severity not in self.VALID_SEVERITY_LEVELS:
                raise InvalidSeverityLevelError(severity, list(self.VALID_SEVERITY_LEVELS))
            severity = SeverityLevel(severity)

        # Validate compliance categories
        if compliance_categories:
            valid_categories = []
            for category in compliance_categories:
                if isinstance(category, str):
                    if category not in self.VALID_COMPLIANCE_CATEGORIES:
                        raise InvalidComplianceCategoryError(category, list(self.VALID_COMPLIANCE_CATEGORIES))
                    valid_categories.append(ComplianceCategory(category))
                elif isinstance(category, ComplianceCategory):
                    valid_categories.append(category)
            compliance_categories = valid_categories


        # Create audit log record
        audit_id = str(uuid4())
        now = datetime.utcnow()

        audit_data = {
            "id": audit_id,
            "user_id": user_id,
            "event_type": event_type.value,
            "event_name": event_name,
            "description": description,
            "severity": severity.value,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "ip_address": ip_address,
            "user_agent": user_agent,
            "session_id": session_id,
            "request_id": request_id,
            "metadata": metadata or {},
            "tags": tags or [],
            "compliance_categories": [
                cat.value if isinstance(cat, ComplianceCategory) else cat
                for cat in (compliance_categories or [])
            ],
            "timestamp": timestamp or now,
            "created_at": now,
            "reviewed": False,
            "review_notes": None,
            "reviewed_by": None,
            "reviewed_at": None,
        }
        # Add any extra kwargs to the dictionary
        audit_data.update(kwargs)

        if self._use_database:
            response = await self._execute_query(
                self.table.insert(audit_data).select("*"),
                operation="create_audit_log"
            )
            audit_log_data = response[0] if isinstance(response, list) else response
        else:
            # In-memory storage
            self._audit_logs[audit_id] = audit_data
            
            # Update indexes
            if user_id:
                self._user_index.setdefault(user_id, []).append(audit_id)
            
            self._event_type_index.setdefault(event_type.value, []).append(audit_id)
            self._severity_index.setdefault(severity.value, []).append(audit_id)
            
            for tag in (tags or []):
                self._tag_index.setdefault(tag, []).append(audit_id)
            
            audit_log_data = audit_data.copy()

        audit_log = AuditLog.from_dict(audit_log_data)
        logger.info(f"Created audit log {audit_id}: {event_type.value}/{event_name}")
        return audit_log

    async def create_bulk_audit_logs(
        self, 
        audit_data_list: List[Dict[str, Any]]
    ) -> List[AuditLog]:
        """
        Create multiple audit log entries in bulk.
        """
        results = []
        for audit_data in audit_data_list:
            try:
                audit_log = await self.create_audit_log(**audit_data)
                results.append(audit_log)
            except (ValidationError, InvalidEventTypeError, InvalidSeverityLevelError, InvalidComplianceCategoryError) as e:
                logger.warning(f"Failed to create audit log during bulk operation: {e}")
                continue
        return results

    # ========== READ OPERATIONS ==========

    async def get_audit_log(self, audit_id: str) -> Optional[AuditLog]:
        """
        Get audit log by ID.
        Core READ operation.
        """
        if self._use_database:
            response = await self._execute_query(
                self.table.select("*").eq("id", audit_id).limit(1),
                operation="get_audit_log"
            )
            if not response:
                return None
            audit_data = response[0] if isinstance(response, list) else response
        else:
            # In-memory storage
            if audit_id not in self._audit_logs:
                return None
            audit_data = self._audit_logs[audit_id].copy()

        return AuditLog.from_dict(audit_data)

    async def search_audit_logs(self, criteria: SearchCriteria) -> List[AuditLog]:
        """
        Search audit logs with comprehensive filtering.
        Advanced READ operation.
        """
        if self._use_database:
            query = self.table.select("*")
            
            # Apply filters
            if criteria.user_id:
                query = query.eq("user_id", criteria.user_id)
            if criteria.event_type:
                query = query.eq("event_type", criteria.event_type.value)
            if criteria.event_name:
                query = query.eq("event_name", criteria.event_name)
            if criteria.severity:
                query = query.eq("severity", criteria.severity.value)
            if criteria.resource_type:
                query = query.eq("resource_type", criteria.resource_type)
            if criteria.resource_id:
                query = query.eq("resource_id", criteria.resource_id)
            if criteria.ip_address:
                query = query.eq("ip_address", criteria.ip_address)
            if criteria.session_id:
                query = query.eq("session_id", criteria.session_id)
            if criteria.reviewed is not None:
                query = query.eq("reviewed", criteria.reviewed)
            
            # Time range filtering
            if criteria.start_time:
                query = query.gte("timestamp", criteria.start_time.isoformat())
            if criteria.end_time:
                query = query.lte("timestamp", criteria.end_time.isoformat())
            
            # Ordering and pagination
            query = query.order(criteria.order_by, desc=criteria.descending)
            
            if criteria.limit is not None:
                query = query.limit(criteria.limit)
            if criteria.offset > 0:
                query = query.offset(criteria.offset)
            
            response = await self._execute_query(query, operation="search_audit_logs")
            logs_data = response or []
        else:
            # In-memory storage with manual filtering
            logs_data = list(self._audit_logs.values())
            
            # Apply filters
            if criteria.user_id:
                logs_data = [log for log in logs_data if log.get("user_id") == criteria.user_id]
            if criteria.event_type:
                logs_data = [log for log in logs_data if log["event_type"] == criteria.event_type.value]
            if criteria.event_name:
                logs_data = [log for log in logs_data if log["event_name"] == criteria.event_name]
            if criteria.severity:
                logs_data = [log for log in logs_data if log["severity"] == criteria.severity.value]
            if criteria.resource_type:
                logs_data = [log for log in logs_data if log.get("resource_type") == criteria.resource_type]
            if criteria.resource_id:
                logs_data = [log for log in logs_data if log.get("resource_id") == criteria.resource_id]
            if criteria.ip_address:
                logs_data = [log for log in logs_data if log.get("ip_address") == criteria.ip_address]
            if criteria.session_id:
                logs_data = [log for log in logs_data if log.get("session_id") == criteria.session_id]
            if criteria.reviewed is not None:
                logs_data = [log for log in logs_data if log.get("reviewed", False) == criteria.reviewed]
            
            # Time range filtering
            if criteria.start_time:
                logs_data = [log for log in logs_data if log["timestamp"] >= criteria.start_time]
            if criteria.end_time:
                logs_data = [log for log in logs_data if log["timestamp"] <= criteria.end_time]
            
            # Text search
            if criteria.search_text:
                search_lower = criteria.search_text.lower()
                logs_data = [
                    log for log in logs_data
                    if (search_lower in log["event_name"].lower() or
                        search_lower in log["description"].lower() or
                        search_lower in str(log["metadata"]).lower())
                ]
            
            # Tag filtering
            if criteria.tags:
                logs_data = [
                    log for log in logs_data
                    if any(tag in log.get("tags", []) for tag in criteria.tags)
                ]
            
            # Compliance category filtering
            if criteria.compliance_category:
                category_value = criteria.compliance_category.value
                logs_data = [
                    log for log in logs_data
                    if category_value in log.get("compliance_categories", [])
                ]
            
            # Sort logs
            reverse = criteria.descending
            if criteria.order_by == "timestamp":
                logs_data.sort(key=lambda x: x["timestamp"], reverse=reverse)
            elif criteria.order_by == "created_at":
                logs_data.sort(key=lambda x: x["created_at"], reverse=reverse)
            elif criteria.order_by == "severity":
                severity_order = {"critical": 4, "high": 3, "medium": 2, "low": 1}
                logs_data.sort(key=lambda x: severity_order.get(x["severity"], 0), reverse=reverse)
            
            # Apply pagination
            if criteria.offset > 0:
                logs_data = logs_data[criteria.offset:]
            if criteria.limit is not None:
                logs_data = logs_data[:criteria.limit]

        return [AuditLog.from_dict(data) for data in logs_data]

    async def count_audit_logs(self, criteria: Optional[SearchCriteria] = None) -> int:
        """
        Count audit logs matching criteria.
        """
        if criteria is None:
            criteria = SearchCriteria(limit=None)
        else:
            # Remove pagination for counting
            criteria = SearchCriteria(
                **{k: v for k, v in criteria.__dict__.items() if k not in ["limit", "offset"]}
            )
        
        logs = await self.search_audit_logs(criteria)
        return len(logs)

    async def audit_log_exists(self, audit_id: str) -> bool:
        """
        Check if audit log exists.
        """
        audit_log = await self.get_audit_log(audit_id)
        return audit_log is not None

    # ========== UPDATE OPERATIONS ==========

    async def update_audit_log(self, audit_id: str, **updates) -> AuditLog:
        """
        Update audit log (limited updates for audit integrity).
        Core UPDATE operation with restrictions.
        """
        # Only allow updates to specific fields for audit integrity
        allowed_updates = {
            "tags", "reviewed", "review_notes", "reviewed_by", "reviewed_at",
            "compliance_categories", "metadata"
        }
        
        filtered_updates = {}
        for field, value in updates.items():
            if field in allowed_updates:
                filtered_updates[field] = value
            else:
                logger.warning(f"Ignoring update to protected audit field: {field}")

        if not filtered_updates:
            # If no valid updates, just return existing record
            existing = await self.get_audit_log(audit_id)
            if not existing:
                raise AuditLogNotFoundError(audit_id)
            return existing

        if self._use_database:
            response = await self._execute_query(
                self.table.update(filtered_updates).eq("id", audit_id).select("*"),
                operation="update_audit_log"
            )
            
            if not response:
                raise AuditLogNotFoundError(audit_id)
            
            audit_data = response[0] if isinstance(response, list) else response
        else:
            # In-memory storage
            if audit_id not in self._audit_logs:
                raise AuditLogNotFoundError(audit_id)
            
            audit_log = self._audit_logs[audit_id]
            for field, value in filtered_updates.items():
                audit_log[field] = value
            
            audit_data = audit_log.copy()

        updated_audit_log = AuditLog.from_dict(audit_data)
        logger.debug(f"Updated audit log {audit_id}")
        return updated_audit_log

    async def mark_audit_log_reviewed(
        self,
        audit_id: str,
        reviewed_by: str,
        review_notes: Optional[str] = None
    ) -> AuditLog:
        """
        Mark an audit log as reviewed.
        Specialized UPDATE operation.
        """
        return await self.update_audit_log(
            audit_id,
            reviewed=True,
            reviewed_by=reviewed_by,
            reviewed_at=datetime.utcnow(),
            review_notes=review_notes
        )

    async def add_tags_to_audit_log(
        self,
        audit_id: str,
        tags: List[str]
    ) -> AuditLog:
        """
        Add tags to an audit log.
        Specialized UPDATE operation.
        """
        existing = await self.get_audit_log(audit_id)
        if not existing:
            raise AuditLogNotFoundError(audit_id)
        
        current_tags = set(existing.tags)
        new_tags = current_tags.union(set(tags))
        
        return await self.update_audit_log(audit_id, tags=list(new_tags))

    # ========== DELETE OPERATIONS ==========

    async def delete_audit_log(
        self,
        audit_id: str,
        retention_override: bool = False
    ) -> bool:
        """
        Delete audit log (use with extreme caution - breaks audit trail).
        Core DELETE operation with retention policy checks.
        """
        if not retention_override:
            # Check retention policy
            audit_log = await self.get_audit_log(audit_id)
            if audit_log:
                age_days = audit_log.age_hours / 24
                min_retention_days = self._get_minimum_retention_days(audit_log)
                
                if age_days < min_retention_days:
                    raise AuditRetentionViolationError(min_retention_days, int(age_days))

        if self._use_database:
            response = await self._execute_query(
                self.table.delete().eq("id", audit_id),
                operation="delete_audit_log"
            )
            success = bool(response)
        else:
            # In-memory storage
            if audit_id not in self._audit_logs:
                return False
            
            audit_log = self._audit_logs.pop(audit_id)
            
            # Remove from indexes
            user_id = audit_log.get("user_id")
            if user_id and user_id in self._user_index:
                try:
                    self._user_index[user_id].remove(audit_id)
                    if not self._user_index[user_id]:
                        del self._user_index[user_id]
                except ValueError:
                    pass
            
            event_type = audit_log.get("event_type")
            if event_type and event_type in self._event_type_index:
                try:
                    self._event_type_index[event_type].remove(audit_id)
                    if not self._event_type_index[event_type]:
                        del self._event_type_index[event_type]
                except ValueError:
                    pass
            
            severity = audit_log.get("severity")
            if severity and severity in self._severity_index:
                try:
                    self._severity_index[severity].remove(audit_id)
                    if not self._severity_index[severity]:
                        del self._severity_index[severity]
                except ValueError:
                    pass
            
            for tag in audit_log.get("tags", []):
                if tag in self._tag_index:
                    try:
                        self._tag_index[tag].remove(audit_id)
                        if not self._tag_index[tag]:
                            del self._tag_index[tag]
                    except ValueError:
                        pass
            
            success = True

        if success:
            logger.warning(f"DELETED audit log {audit_id} - audit trail broken!")
        
        return success

    async def delete_user_audit_logs(self, user_id: str) -> int:
        """
        Delete all audit logs for a user (GDPR compliance).
        Bulk DELETE operation.
        """
        criteria = SearchCriteria(user_id=user_id, limit=None)
        user_logs = await self.search_audit_logs(criteria)
        
        count = 0
        for log in user_logs:
            try:
                if await self.delete_audit_log(log.id, retention_override=True):
                    count += 1
            except Exception as e:
                logger.error(f"Failed to delete audit log {log.id}: {e}")
                continue
        
        logger.warning(f"DELETED {count} audit logs for user {user_id} - audit trail broken!")
        return count

    async def delete_old_audit_logs(
        self,
        days: int,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """
        Delete old audit logs based on retention policy.
        Maintenance DELETE operation with dry run support.
        """
        cutoff = datetime.utcnow() - timedelta(days=days)
        criteria = SearchCriteria(end_time=cutoff, limit=None)
        old_logs = await self.search_audit_logs(criteria)
        
        # Filter by retention policy
        deletable_logs = []
        protected_logs = []
        
        for log in old_logs:
            min_retention_days = self._get_minimum_retention_days(log)
            if log.age_hours / 24 >= min_retention_days:
                deletable_logs.append(log)
            else:
                protected_logs.append(log)
        
        if dry_run:
            return {
                "dry_run": True,
                "total_old_logs": len(old_logs),
                "deletable_count": len(deletable_logs),
                "protected_count": len(protected_logs),
                "cutoff_date": cutoff.isoformat()
            }
        
        # Actually delete
        deleted_count = 0
        for log in deletable_logs:
            try:
                if await self.delete_audit_log(log.id, retention_override=True):
                    deleted_count += 1
            except Exception as e:
                logger.error(f"Failed to delete old audit log {log.id}: {e}")
                continue
        
        logger.info(f"Deleted {deleted_count} old audit logs")
        return {
            "dry_run": False,
            "deleted_count": deleted_count,
            "protected_count": len(protected_logs),
            "cutoff_date": cutoff.isoformat()
        }

    # ========== CONVENIENCE METHODS ==========

    async def log_event(
        self,
        user_id: Optional[str],
        event_type: EventType,
        metadata: Dict[str, Any]
    ) -> AuditLog:
        """
        Log an audit event.
        High-level convenience method - matches original interface.
        """
        event_name = metadata.get("event_name", event_type.value)
        description = metadata.get("description", f"{event_type.value} event")
        
        return await self.create_audit_log(
            user_id=user_id,
            event_type=event_type,
            event_name=event_name,
            description=description,
            metadata=metadata
        )

    async def log_user_action(
        self,
        user_id: str,
        action: str,
        resource: str,
        details: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
        session_id: Optional[str] = None
    ) -> AuditLog:
        """
        Log a user action with standardized format.
        """
        metadata = {
            "action": action,
            "resource": resource,
            "details": details or {}
        }
        
        return await self.create_audit_log(
            user_id=user_id,
            event_type=EventType.USER_ACTION,
            event_name=f"user_{action}",
            description=f"User {action} on {resource}",
            resource_type=resource,
            ip_address=ip_address,
            session_id=session_id,
            metadata=metadata,
            tags=["user_action", action]
        )

    async def log_security_event(
        self,
        event_name: str,
        description: str,
        severity: SeverityLevel = SeverityLevel.HIGH,
        user_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ) -> AuditLog:
        """
        Log a security event with standardized format.
        """
        metadata = {
            "event_name": event_name,
            "ip_address": ip_address,
            "user_agent": user_agent,
            "details": details or {}
        }
        
        return await self.create_audit_log(
            user_id=user_id,
            event_type=EventType.SECURITY_EVENT,
            event_name=event_name,
            description=description,
            severity=severity,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata=metadata,
            tags=["security", "alert"],
            compliance_categories=[ComplianceCategory.SOC2]
        )

    async def log_system_event(
        self,
        event_name: str,
        component: str,
        details: Optional[Dict[str, Any]] = None,
        severity: SeverityLevel = SeverityLevel.MEDIUM
    ) -> AuditLog:
        """
        Log a system event with standardized format.
        """
        metadata = {
            "event_name": event_name,
            "component": component,
            "details": details or {}
        }
        
        return await self.create_audit_log(
            user_id=None,  # System events don't have a user
            event_type=EventType.SYSTEM_EVENT,
            event_name=event_name,
            description=f"System event in {component}: {event_name}",
            severity=severity,
            resource_type="system",
            resource_id=component,
            metadata=metadata,
            tags=["system", component]
        )

    # ========== COMPLIANCE AND REPORTING ==========

    async def get_audit_summary(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        user_id: Optional[str] = None
    ) -> AuditSummary:
        """
        Get comprehensive audit summary.
        """
        criteria = SearchCriteria(
            user_id=user_id,
            start_time=start_time,
            end_time=end_time,
            limit=None
        )
        
        logs = await self.search_audit_logs(criteria)
        return AuditSummary.from_logs(logs, start_time, end_time)

    async def get_security_incidents(
        self,
        severity: Optional[SeverityLevel] = None,
        days: int = 7
    ) -> List[AuditLog]:
        """
        Get security incidents from audit logs.
        """
        start_time = datetime.utcnow() - timedelta(days=days)
        
        criteria = SearchCriteria(
            event_type=EventType.SECURITY_EVENT,
            severity=severity,
            start_time=start_time,
            limit=None
        )
        
        return await self.search_audit_logs(criteria)

    async def get_compliance_report(
        self,
        compliance_category: ComplianceCategory,
        days: int = 30
    ) -> Dict[str, Any]:
        """
        Generate compliance report for a specific category.
        """
        start_time = datetime.utcnow() - timedelta(days=days)
        
        criteria = SearchCriteria(
            compliance_category=compliance_category,
            start_time=start_time,
            limit=None
        )
        
        logs = await self.search_audit_logs(criteria)
        
        # Categorize events
        data_access_events = [log for log in logs if log.event_type == EventType.DATA_ACCESS]
        modification_events = [log for log in logs if log.event_type == EventType.DATA_MODIFICATION]
        security_events = [log for log in logs if log.event_type == EventType.SECURITY_EVENT]
        
        return {
            "compliance_category": compliance_category.value,
            "report_period_days": days,
            "total_events": len(logs),
            "data_access_events": len(data_access_events),
            "modification_events": len(modification_events),
            "security_events": len(security_events),
            "unreviewed_critical": len([log for log in logs if log.requires_review]),
            "first_event": logs[-1].timestamp.isoformat() if logs else None,
            "last_event": logs[0].timestamp.isoformat() if logs else None,
            "generated_at": datetime.utcnow().isoformat()
        }

    async def get_unreviewed_critical_events(self) -> List[AuditLog]:
        """
        Get critical events that require review.  
        """
        criteria = SearchCriteria(
            severity=SeverityLevel.CRITICAL,
            reviewed=False,
            limit=None
        )
        
        return await self.search_audit_logs(criteria)

    # ========== MAINTENANCE OPERATIONS ==========

    def _get_minimum_retention_days(self, audit_log: AuditLog) -> int:
        """
        Get minimum retention days based on compliance requirements.
        """
        # Critical events have longer retention
        if audit_log.severity == SeverityLevel.CRITICAL:
            return self.CRITICAL_EVENT_RETENTION_DAYS
        
        # GDPR specific retention
        if ComplianceCategory.GDPR in audit_log.compliance_categories:
            return self.GDPR_RETENTION_DAYS
        
        # Default SOX compliance
        return self.DEFAULT_RETENTION_DAYS

    async def reindex_audit_logs(self) -> Dict[str, int]:
        """
        Rebuild indexes for audit logs (in-memory storage only).
        """
        if self._use_database:
            return {"message": "Database storage does not require manual reindexing"}
        
        # Clear existing indexes
        self._user_index.clear()
        self._event_type_index.clear()
        self._severity_index.clear()
        self._tag_index.clear()
        
        # Rebuild indexes
        for audit_id, audit_log in self._audit_logs.items():
            user_id = audit_log.get("user_id")
            if user_id:
                self._user_index.setdefault(user_id, []).append(audit_id)
            
            event_type = audit_log.get("event_type")
            if event_type:
                self._event_type_index.setdefault(event_type, []).append(audit_id)
            
            severity = audit_log.get("severity")
            if severity:
                self._severity_index.setdefault(severity, []).append(audit_id)
            
            for tag in audit_log.get("tags", []):
                self._tag_index.setdefault(tag, []).append(audit_id)
        
        return {
            "total_logs": len(self._audit_logs),
            "users_indexed": len(self._user_index),
            "event_types_indexed": len(self._event_type_index),
            "severities_indexed": len(self._severity_index),
            "tags_indexed": len(self._tag_index)
        }

    # ========== DATABASE OPERATIONS ==========

    async def _execute_query(self, query: QueryBuilder, operation: str) -> Any:
        """
        Execute a query with proper error handling.
        Centralized error handling pattern.
        """
        try:
            response = query.execute()
            
            # Handle error responses
            if hasattr(response, 'error') and response.error:
                raise DatabaseError(f"Database error in {operation}: {response.error}", operation=operation)
            
            # Extract data from response
            if hasattr(response, 'data'):
                return response.data
            else:
                # For mocks that return data directly
                return response
                
        except DatabaseError:
            raise
        except Exception as e:
            logger.error(f"Query execution failed in {operation}: {e}")
            raise DatabaseError(f"Query execution failed in {operation}: {str(e)}", operation=operation)

    # ========== HEALTH CHECK ==========

    async def health_check(self) -> Dict[str, Any]:
        """
        Repository health check.
        """
        try:
            if self._use_database:
                # Test database connectivity
                response = await self._execute_query(
                    self.table.select("id").limit(1),
                    operation="health_check"
                )
                
                return {
                    "healthy": True,
                    "storage_type": "database",
                    "timestamp": datetime.utcnow().isoformat(),
                    "valid_event_types": list(self.VALID_EVENT_TYPES),
                    "valid_severity_levels": list(self.VALID_SEVERITY_LEVELS),
                    "valid_compliance_categories": list(self.VALID_COMPLIANCE_CATEGORIES),
                    "retention_policies": {
                        "default_days": self.DEFAULT_RETENTION_DAYS,
                        "gdpr_days": self.GDPR_RETENTION_DAYS,
                        "critical_events_days": self.CRITICAL_EVENT_RETENTION_DAYS
                    }
                }
            else:
                total_logs = len(self._audit_logs)
                unreviewed_critical = await self.count_audit_logs(
                    SearchCriteria(severity=SeverityLevel.CRITICAL, reviewed=False)
                )
                
                return {
                    "healthy": True,
                    "storage_type": "in_memory",
                    "total_logs": total_logs,
                    "unreviewed_critical": unreviewed_critical,
                    "indexes_built": True,
                    "timestamp": datetime.utcnow().isoformat(),
                    "valid_event_types": list(self.VALID_EVENT_TYPES),
                    "valid_severity_levels": list(self.VALID_SEVERITY_LEVELS),
                    "valid_compliance_categories": list(self.VALID_COMPLIANCE_CATEGORIES)
                }
                
        except Exception as e:
            logger.error(f"Audit repository health check failed: {e}")
            return {
                "healthy": False,
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }

    # ========== LEGACY COMPATIBILITY ==========

    async def get_user_audit_logs(
        self, 
        user_id: str, 
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Legacy method - returns dicts for backward compatibility"""
        criteria = SearchCriteria(user_id=user_id, limit=limit)
        audit_logs = await self.search_audit_logs(criteria)
        return [log.to_dict() for log in audit_logs]

    async def get_security_audit_logs(
        self, 
        event_type: Optional[str] = None, 
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Legacy method - returns dicts for backward compatibility"""
        event_type_enum = None
        if event_type:
            try:
                event_type_enum = EventType(event_type)
            except ValueError:
                event_type_enum = EventType.SECURITY_EVENT
        else:
            event_type_enum = EventType.SECURITY_EVENT
        
        criteria = SearchCriteria(event_type=event_type_enum, limit=limit)
        audit_logs = await self.search_audit_logs(criteria)
        return [log.to_dict() for log in audit_logs]
