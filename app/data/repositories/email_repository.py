# app/data/repositories/email_repository.py
"""
Clean EmailRepository - Pure CRUD operations only.
Following BillingRepository pattern with no business logic.
Repository pattern implementation with clear separation of data access concerns.
"""
import logging
from datetime import datetime, timedelta
from uuid import uuid4
from typing import Any, Dict, List, Optional, Protocol, Tuple
from dataclasses import dataclass, asdict
from enum import Enum

from app.core.exceptions import (
    ValidationError,
    NotFoundError,
    DatabaseError,
    EmailRecordExistsError,
    InvalidEmailStatusError,
    EmailRecordNotFoundError
)

logger = logging.getLogger(__name__)


# ========== DOMAIN MODELS ==========

class EmailStatus(Enum):
    """Email processing status enumeration"""
    DISCOVERED = "discovered"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"


@dataclass
class EmailRecord:
    """Domain model for email processing records"""
    id: str
    user_id: str
    message_id: str
    subject: str
    sender: str
    received_at: Optional[str]
    discovery_method: str
    metadata: Dict[str, Any]
    status: EmailStatus
    created_at: datetime
    updated_at: datetime
    discovery_count: int
    discovered_at: datetime
    processing_started_at: Optional[datetime]
    processing_completed_at: Optional[datetime]
    processing_attempts: int
    processing_result: Dict[str, Any]
    last_retry_at: Optional[datetime]
    max_retries: int
    success: Optional[bool]

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EmailRecord":
        """Create EmailRecord from dictionary"""
        # --- START OF FIX ---
        data = data.copy()  # Operate on a copy to prevent mutation
        # --- END OF FIX ---

        # Handle datetime conversion
        for field in ["created_at", "updated_at", "discovered_at", "processing_started_at", 
                     "processing_completed_at", "last_retry_at"]:
            if field in data and data[field]:
                if isinstance(data[field], str):
                    data[field] = datetime.fromisoformat(data[field])
        
        # Handle enum conversion
        if "status" in data and isinstance(data["status"], str):
            data["status"] = EmailStatus(data["status"])
        
        return cls(**data)

    def to_dict(self) -> Dict[str, Any]:
        """Convert EmailRecord to dictionary"""
        data = asdict(self)
        
        # Convert enum to string
        data["status"] = self.status.value
        
        # Convert datetime to ISO string
        for field in ["created_at", "updated_at", "discovered_at", "processing_started_at", 
                     "processing_completed_at", "last_retry_at"]:
            if data[field]:
                data[field] = data[field].isoformat()
        
        return data


@dataclass
class ProcessingStats:
    """Domain model for processing statistics"""
    user_id: str
    total_discovered: int
    total_processed: int
    total_successful: int
    total_failed: int
    total_pending: int
    success_rate: float
    total_credits_used: int
    average_processing_time: float

    @classmethod
    def from_records(cls, user_id: str, records: List[EmailRecord]) -> "ProcessingStats":
        """Create ProcessingStats from email records"""
        if not records:
            return cls(
                user_id=user_id,
                total_discovered=0,
                total_processed=0,
                total_successful=0,
                total_failed=0,
                total_pending=0,
                success_rate=0.0,
                total_credits_used=0,
                average_processing_time=0.0
            )

        total_discovered = len(records)
        successes = [r for r in records if r.status == EmailStatus.COMPLETED and r.success]
        failures = [r for r in records if r.status == EmailStatus.FAILED or (r.status == EmailStatus.COMPLETED and not r.success)]
        
        total_processed = len(successes) + len(failures)
        total_successful = len(successes)
        total_failed = len(failures)
        pending = total_discovered - total_processed
        
        total_credits_used = sum(r.processing_result.get("credits_used", 0) for r in successes)
        
        processing_times = [r.processing_result.get("processing_time", 0) for r in successes]
        avg_time = sum(processing_times) / len(processing_times) if processing_times else 0.0
        
        success_rate = (total_successful / total_processed) if total_processed > 0 else 0.0

        return cls(
            user_id=user_id,
            total_discovered=total_discovered,
            total_processed=total_processed,
            total_successful=total_successful,
            total_failed=total_failed,
            total_pending=pending,
            success_rate=round(success_rate, 2),
            total_credits_used=total_credits_used,
            average_processing_time=avg_time
        )


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

class EmailRepository:
    """
    Pure CRUD operations for email records with comprehensive error handling.
    Repository pattern implementation - no business logic, just data access.
    Following BillingRepository pattern exactly.
    """
    
    # Valid email statuses
    VALID_STATUSES = {status.value for status in EmailStatus}
    VALID_DISCOVERY_METHODS = {"api_scan", "webhook", "manual", "scheduled"}

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
            self._records: Dict[str, Dict[str, Any]] = {}
            self._index: Dict[tuple, str] = {}  # (user_id, message_id) -> record_id
            self._use_database = False

    # ========== CREATE OPERATIONS ==========

    async def create_email_record(
        self,
        user_id: str,
        message_id: str,
        subject: str = "",
        sender: str = "",
        received_at: Optional[str] = None,
        discovery_method: str = "api_scan",
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> EmailRecord:
        """
        Create a new email record.
        Core CREATE operation with validation and deduplication.
        """
        # Validate required fields
        if not user_id:
            raise ValidationError("user_id is required")
        if not message_id:
            raise ValidationError("message_id is required")
        if discovery_method not in self.VALID_DISCOVERY_METHODS:
            raise ValidationError(f"Invalid discovery method: {discovery_method}")

        # Check for duplicates
        uid = str(user_id)
        key = (uid, message_id)
        
        if self._use_database:
            existing = await self.get_email_record(user_id, message_id)
            if existing:
                raise EmailRecordExistsError(message_id)
        else:
            if key in self._index:
                raise EmailRecordExistsError(message_id)

        # Create record
        record_id = str(uuid4())
        now = datetime.utcnow()

        record_data = {
            "id": record_id,
            "user_id": uid,
            "message_id": message_id,
            "subject": subject,
            "sender": sender,
            "received_at": received_at,
            "discovery_method": discovery_method,
            "metadata": metadata or {},
            "status": EmailStatus.DISCOVERED.value,
            "created_at": now,
            "updated_at": now,
            "discovery_count": 1,
            "discovered_at": now,
            "processing_started_at": None,
            "processing_completed_at": None,
            "processing_attempts": 0,
            "processing_result": {},
            "last_retry_at": None,
            "max_retries": 3,
            "success": None,
            **kwargs
        }

        if self._use_database:
            response = await self._execute_query(
                self.table.insert(record_data).select("*"),
                operation="create_email_record"
            )
            record_data = response[0] if isinstance(response, list) else response
        else:
            # In-memory storage
            self._records[record_id] = record_data.copy()
            self._index[key] = record_id

        email_record = EmailRecord.from_dict(record_data)
        logger.debug(f"Created email record: {message_id} for user {uid}")
        return email_record

    # ========== READ OPERATIONS ==========

    async def get_email_record(self, user_id: str, message_id: str) -> Optional[EmailRecord]:
        """
        Get single email record by user_id and message_id.
        Core READ operation.
        """
        uid = str(user_id)
        key = (uid, message_id)

        if self._use_database:
            response = await self._execute_query(
                self.table.select("*").eq("user_id", uid).eq("message_id", message_id),
                operation="get_email_record"
            )
            
            if not response:
                return None
            
            record_data = response[0] if isinstance(response, list) else response
        else:
            # In-memory storage
            if key not in self._index:
                return None
            
            record_id = self._index[key]
            record_data = self._records[record_id]

        return EmailRecord.from_dict(record_data)

    async def get_email_record_by_id(self, record_id: str) -> Optional[EmailRecord]:
        """
        Get single email record by internal ID.
        Core READ operation.
        """
        if self._use_database:
            response = await self._execute_query(
                self.table.select("*").eq("id", record_id),
                operation="get_email_record_by_id"
            )
            
            if not response:
                return None
            
            record_data = response[0] if isinstance(response, list) else response
        else:
            # In-memory storage
            if record_id not in self._records:
                return None
            
            record_data = self._records[record_id]

        return EmailRecord.from_dict(record_data)

    async def list_email_records(
        self,
        user_id: str,
        status: Optional[EmailStatus] = None,
        limit: Optional[int] = 100,
        offset: int = 0
    ) -> List[EmailRecord]:
        """
        List email records for a user with optional filtering.
        Core READ operation with basic filtering.
        """
        uid = str(user_id)

        if self._use_database:
            query = self.table.select("*").eq("user_id", uid)
            
            if status:
                query = query.eq("status", status.value)
            
            if limit:
                query = query.limit(limit)
            
            if offset:
                query = query.offset(offset)
            
            query = query.order("created_at", desc=True)
            
            response = await self._execute_query(query, operation="list_email_records")
            records_data = response if isinstance(response, list) else [response] if response else []
        else:
            # In-memory storage
            # --- Start of FIX ---
            records_data = self._records.values()
            
            # Filter by user_id first
            records_data = [r for r in records_data if r["user_id"] == uid]

            # Filter by status if provided
            if status is not None:
                records_data = [r for r in records_data if r["status"] == status.value]
            # --- End of FIX ---

            # Sort by created_at descending
            records_data.sort(key=lambda x: x["created_at"], reverse=True)
            
            # Apply pagination
            if offset:
                records_data = records_data[offset:]
            if limit:
                records_data = records_data[:limit]

        return [EmailRecord.from_dict(data) for data in records_data]

    async def count_email_records(
        self,
        user_id: str,
        status: Optional[EmailStatus] = None
    ) -> int:
        """
        Count email records for a user.
        Utility READ operation.
        """
        uid = str(user_id)

        if self._use_database:
            query = self.table.select("count").eq("user_id", uid)
            
            if status:
                query = query.eq("status", status.value)
            
            response = await self._execute_query(query, operation="count_email_records")
            return response.get("count", 0) if response else 0
        else:
            # In-memory storage
            return len([
                rec for rec in self._records.values()
                if rec["user_id"] == uid and (status is None or rec["status"] == status.value)
            ])

    # ========== UPDATE OPERATIONS ==========

    async def update_email_record(
        self,
        user_id: str,
        message_id: str,
        **updates
    ) -> EmailRecord:
        """
        Update an email record.
        Core UPDATE operation - the 'U' in CRUD.
        """
        uid = str(user_id)
        key = (uid, message_id)
        
        # Validate status if provided
        if "status" in updates:
            status_value = updates["status"]
            if isinstance(status_value, EmailStatus):
                updates["status"] = status_value.value
            elif status_value not in self.VALID_STATUSES:
                raise InvalidEmailStatusError(status_value, list(self.VALID_STATUSES))

        if self._use_database:
            # Always update the updated_at timestamp
            updates["updated_at"] = datetime.utcnow()
            
            response = await self._execute_query(
                self.table
                .update(updates)
                .eq("user_id", uid)
                .eq("message_id", message_id)
                .select("*"),
                operation="update_email_record"
            )
            
            if not response:
                raise EmailRecordNotFoundError(message_id)
            
            record_data = response[0] if isinstance(response, list) else response
        else:
            # In-memory storage
            if key not in self._index:
                raise EmailRecordNotFoundError(message_id)
            
            record_id = self._index[key]
            record = self._records[record_id]
            
            # Update fields (protect immutable fields)
            for field, value in updates.items():
                if field not in ["id", "user_id", "message_id", "created_at"]:
                    record[field] = value
            
            # Always update the updated_at timestamp
            record["updated_at"] = datetime.utcnow()
            record_data = record.copy()

        logger.debug(f"Updated email record: {message_id} for user {uid}")
        return EmailRecord.from_dict(record_data)

    async def update_email_record_by_id(
        self,
        record_id: str,
        **updates
    ) -> EmailRecord:
        """
        Update an email record by internal ID.
        Alternative UPDATE method.
        """
        # Validate status if provided
        if "status" in updates:
            status_value = updates["status"]
            if isinstance(status_value, EmailStatus):
                updates["status"] = status_value.value
            elif status_value not in self.VALID_STATUSES:
                raise InvalidEmailStatusError(status_value, list(self.VALID_STATUSES))

        if self._use_database:
            # Always update the updated_at timestamp
            updates["updated_at"] = datetime.utcnow()
            
            response = await self._execute_query(
                self.table
                .update(updates)
                .eq("id", record_id)
                .select("*"),
                operation="update_email_record_by_id"
            )
            
            if not response:
                raise NotFoundError(f"Email record not found: {record_id}")
            
            record_data = response[0] if isinstance(response, list) else response
        else:
            # In-memory storage
            if record_id not in self._records:
                raise NotFoundError(f"Email record not found: {record_id}")
            
            record = self._records[record_id]
            
            # Update fields (protect immutable fields)
            for field, value in updates.items():
                if field not in ["id", "user_id", "message_id", "created_at"]:
                    record[field] = value
            
            # Always update the updated_at timestamp
            record["updated_at"] = datetime.utcnow()
            record_data = record.copy()

        logger.debug(f"Updated email record by ID: {record_id}")
        return EmailRecord.from_dict(record_data)

    async def bulk_update_email_records(
        self,
        user_id: str,
        updates: List[Tuple[str, Dict[str, Any]]]  # List of (message_id, update_data)
    ) -> List[EmailRecord]:
        """
        Bulk update multiple email records.
        Efficient UPDATE for batch operations.
        """
        results = []
        for message_id, update_data in updates:
            try:
                record = await self.update_email_record(user_id, message_id, **update_data)
                results.append(record)
            except (EmailRecordNotFoundError, ValidationError) as e:
                logger.warning(f"Failed to update email record {message_id}: {e}")
                continue
        return results

    # ========== DELETE OPERATIONS ==========

    async def delete_email_record(
        self,
        user_id: str,
        message_id: str
    ) -> bool:
        """
        Delete a single email record.
        Core DELETE operation.
        """
        uid = str(user_id)
        key = (uid, message_id)

        if self._use_database:
            response = await self._execute_query(
                self.table.delete().eq("user_id", uid).eq("message_id", message_id),
                operation="delete_email_record"
            )
            success = bool(response)
        else:
            # In-memory storage
            if key not in self._index:
                return False
            
            record_id = self._index[key]
            del self._records[record_id]
            del self._index[key]
            success = True

        if success:
            logger.debug(f"Deleted email record: {message_id} for user {uid}")
        
        return success

    async def delete_user_email_records(self, user_id: str) -> int:
        """
        Delete all email records for a user.
        Bulk DELETE operation.
        """
        uid = str(user_id)

        if self._use_database:
            response = await self._execute_query(
                self.table.delete().eq("user_id", uid),
                operation="delete_user_email_records"
            )
            count = len(response) if isinstance(response, list) else 0
        else:
            # In-memory storage
            to_delete = []
            
            for key, record_id in self._index.items():
                if key[0] == uid:
                    to_delete.append((key, record_id))
            
            count = 0
            for key, record_id in to_delete:
                del self._records[record_id]
                del self._index[key]
                count += 1

        logger.debug(f"Deleted {count} email records for user {uid}")
        return count

    async def delete_old_records(self, days: int) -> int:
        """
        Delete old completed/failed records.
        Maintenance DELETE operation.
        """
        cutoff = datetime.utcnow() - timedelta(days=days)
        
        if self._use_database:
            # Database implementation would use date filtering
            response = await self._execute_query(
                self.table.delete()
                    .eq("status", EmailStatus.COMPLETED.value)
                    .lt("processing_completed_at", cutoff.isoformat()),
                operation="delete_old_records"
            )
            count = len(response) if isinstance(response, list) else 0
        else:
            # In-memory storage
            to_delete = []
            
            for record_id, record in self._records.items():
                completed_at = record.get("processing_completed_at")
                if (completed_at and 
                    isinstance(completed_at, datetime) and
                    completed_at < cutoff and 
                    record["status"] in [EmailStatus.COMPLETED.value, EmailStatus.FAILED.value]):
                    to_delete.append((record_id, (record["user_id"], record["message_id"])))
            
            count = 0
            for record_id, index_key in to_delete:
                del self._records[record_id]
                del self._index[index_key]
                count += 1

        logger.debug(f"Deleted {count} old email records")
        return count

    # ========== DATABASE OPERATIONS ==========

    async def _execute_query(self, query: QueryBuilder, operation: str) -> Any:
        """
        Execute a query with proper error handling.
        Centralized error handling pattern from BillingRepository.
        """
        try:
            response = query.execute()
            
            if response.error:
                raise response.error
            
            return response.data
            
        except Exception as e:
            logger.error(f"Database operation failed ({operation}): {e}")
            raise DatabaseError(f"Database operation failed: {str(e)}", operation=operation)