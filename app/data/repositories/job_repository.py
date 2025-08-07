# app/data/repositories/job_repository.py
"""
Clean Job Repository - Pure CRUD operations with no business logic.
Follows the clean architecture pattern from BillingRepository.
Repository pattern implementation with clear separation of data access concerns.
"""
import copy
import asyncio
import logging
from typing import Any, Dict, List, Optional, Protocol
from uuid import uuid4
from datetime import datetime

from app.models.job import (
    JobRecord, 
    JobStatus, 
    JobType, 
    JobPriority, 
    RecurrenceInterval,
    JobStats
)
from app.core.exceptions import (
    # Core exceptions
    ValidationError,
    DatabaseError,
    # Job-specific domain exceptions
    JobNotFoundError,
    InvalidJobTypeError,
    InvalidJobStatusError,
    MaxRetriesExceededError,
    InvalidJobPriorityError
)


logger = logging.getLogger(__name__)





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

class JobRepository:
    """
    Pure CRUD operations for jobs with comprehensive error handling.
    Repository pattern implementation - no business logic, just data access.
    Follows BillingRepository patterns for production SAAS.
    """

    # Valid configuration values
    VALID_JOB_TYPES = {job_type.value for job_type in JobType}
    VALID_PRIORITIES = {priority.value for priority in JobPriority}
    VALID_STATUSES = {status.value for status in JobStatus}
    VALID_INTERVALS = {interval.value for interval in RecurrenceInterval}
    VALID_ORDER_FIELDS = {
        "created_at", "updated_at", "started_at", "completed_at", "failed_at", 
        "scheduled_for", "priority", "status", "job_type", "user_id", "attempts"
    }
    DEFAULT_MAX_RETRIES = 3

    def __init__(self, table: Optional[DatabaseTable] = None):
        """
        Initialize repository with optional table dependency for testing.
        If no table provided, uses in-memory storage for development/testing.
        """
        if table is not None:
            self.table = table
            self._use_database = True
        else:
            # In-memory storage for development/testing
            self._jobs: Dict[str, Dict[str, Any]] = {}
            self._lock = asyncio.Lock()  # Concurrency-safe in-memory operations
            self._use_database = False

    # ========== CREATE OPERATIONS ==========

    async def create_job(self, job_data: Dict[str, Any]) -> JobRecord:
        """
        Create a new job record.
        Pure CREATE operation with validation and defaults.
        """
        # Protect against input mutation - deep copy the payload
        job_data = copy.deepcopy(job_data)
        
        # Validate required fields
        user_id = job_data.get("user_id")
        if not user_id:
            raise ValidationError("user_id is required")

        job_type = job_data.get("job_type")
        if not job_type:
            raise ValidationError("job_type is required")
        if isinstance(job_type, str):
            if job_type not in self.VALID_JOB_TYPES:
                raise InvalidJobTypeError(job_type, list(self.VALID_JOB_TYPES))
            job_type = JobType(job_type)
        elif not isinstance(job_type, JobType):
            raise InvalidJobTypeError(str(job_type), list(self.VALID_JOB_TYPES))

        # Validate optional fields with defaults
        priority = job_data.get("priority", JobPriority.NORMAL)
        if isinstance(priority, str):
            if priority not in self.VALID_PRIORITIES:
                raise InvalidJobPriorityError(priority, list(self.VALID_PRIORITIES))
            priority = JobPriority(priority)

        status = job_data.get("status", JobStatus.PENDING)
        if isinstance(status, str):
            if status not in self.VALID_STATUSES:
                raise InvalidJobStatusError(status, list(self.VALID_STATUSES))
            status = JobStatus(status)

        # Validate recurrence_interval if provided
        recurrence_interval = job_data.get("recurrence_interval")
        if recurrence_interval is not None:
            if isinstance(recurrence_interval, str):
                if recurrence_interval not in self.VALID_INTERVALS:
                    raise ValidationError(f"Invalid recurrence_interval: {recurrence_interval}")
                recurrence_interval = RecurrenceInterval(recurrence_interval)
            elif not isinstance(recurrence_interval, RecurrenceInterval):
                raise ValidationError(f"Invalid recurrence_interval: {recurrence_interval}")

        # Generate job ID and timestamps
        job_id = str(uuid4())
        now = datetime.utcnow()

        try:
            record_data = {
                "job_id": job_id,
                "user_id": str(user_id),
                "job_type": job_type.value,
                "priority": priority.value,
                "status": status.value,
                "metadata": job_data.get("metadata", {}),
                "scheduled_for": job_data.get("scheduled_for", now).isoformat(),
                "max_retries": job_data.get("max_retries", self.DEFAULT_MAX_RETRIES),
                "attempts": job_data.get("attempts", 0),
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
                # Optional fields
                "started_at": job_data.get("started_at").isoformat() if job_data.get("started_at") else None,
                "completed_at": job_data.get("completed_at").isoformat() if job_data.get("completed_at") else None,
                "failed_at": job_data.get("failed_at").isoformat() if job_data.get("failed_at") else None,
                "worker_id": job_data.get("worker_id"),
                "last_error": job_data.get("last_error"),
                "result": job_data.get("result", {}),
                "processing_time": job_data.get("processing_time"),
                "recurrence_interval": recurrence_interval.value if recurrence_interval else None,
                "parent_job_id": job_data.get("parent_job_id"),
            }

            if self._use_database:
                response = self._execute_query(
                    self.table.insert(record_data).select("*"),
                    operation="create_job"
                )
                if not response or len(response) == 0:
                    raise DatabaseError("Failed to create job record", operation="create_job")
                
                job_record = JobRecord.from_dict(response[0])
            else:
                # In-memory storage with concurrency protection
                async with self._lock:
                    self._jobs[job_id] = record_data
                job_record = JobRecord.from_dict(record_data)

            logger.debug(f"Created job: {job_id}")
            return job_record

        except (ValidationError, DatabaseError):
            raise
        except Exception as e:
            logger.error(f"Failed to create job: {e}")
            raise DatabaseError(f"Failed to create job: {str(e)}", operation="create_job")

    # ========== READ OPERATIONS ==========

    async def get_job(self, job_id: str) -> Optional[JobRecord]:
        """Get a job by ID"""
        if not job_id:
            raise ValidationError("job_id cannot be empty")

        try:
            if self._use_database:
                response = self._execute_query(
                    self.table.select("*").eq("job_id", job_id),
                    operation="get_job"
                )
                
                if not response or len(response) == 0:
                    return None
                
                return JobRecord.from_dict(response[0])
            else:
                # In-memory storage
                job_data = self._jobs.get(job_id)
                return JobRecord.from_dict(job_data) if job_data else None

        except Exception as e:
            logger.error(f"Failed to get job {job_id}: {e}")
            raise DatabaseError(f"Failed to get job: {str(e)}", operation="get_job")

    async def list_jobs(
        self,
        user_id: Optional[str] = None,
        job_type: Optional[str] = None,
        status: Optional[JobStatus] = None,
        priority: Optional[JobPriority] = None,
        limit: Optional[int] = 100,
        offset: int = 0,
        order_by: str = "created_at",
        job_types: Optional[List[str]] = None,
        started_before: Optional[datetime] = None
    ) -> List[JobRecord]:
        """
        List jobs with filtering and pagination.
        Pure READ operation with flexible filtering.
        """
        try:
            if self._use_database:
                query = self.table.select("*")
                
                # Apply filters
                if user_id:
                    query = query.eq("user_id", user_id)
                if job_type:
                    query = query.eq("job_type", job_type)
                if job_types:
                    # Handle multiple job types - this would need database-specific implementation
                    # For now, use the first one as fallback
                    query = query.eq("job_type", job_types[0])
                if status:
                    query = query.eq("status", status.value)
                if priority:
                    query = query.eq("priority", priority.value)
                if started_before:
                    query = query.lt("started_at", started_before.isoformat())
                
                # Apply ordering and pagination
                if order_by:
                    desc = "DESC" in order_by.upper()
                    column = order_by.replace(" DESC", "").replace(" ASC", "").strip()
                    if column not in self.VALID_ORDER_FIELDS:
                        raise ValidationError(f"Invalid order_by field: {column}")
                    query = query.order(column, desc=desc)
                
                if limit:
                    query = query.limit(limit)
                if offset:
                    query = query.offset(offset)
                
                response = self._execute_query(query, operation="list_jobs")
                return [JobRecord.from_dict(record) for record in response or []]
            else:
                # In-memory storage filtering
                jobs = list(self._jobs.values())
                
                # Apply filters
                if user_id:
                    jobs = [j for j in jobs if j.get("user_id") == user_id]
                if job_type:
                    jobs = [j for j in jobs if j.get("job_type") == job_type]
                if job_types:
                    jobs = [j for j in jobs if j.get("job_type") in job_types]
                if status:
                    jobs = [j for j in jobs if j.get("status") == status.value]
                if priority:
                    jobs = [j for j in jobs if j.get("priority") == priority.value]
                if started_before:
                    jobs = [j for j in jobs if j.get("started_at") and 
                           datetime.fromisoformat(j["started_at"]) < started_before]
                
                # Apply ordering
                if order_by:
                    reverse = "DESC" in order_by.upper()
                    sort_key = order_by.replace(" DESC", "").replace(" ASC", "").strip()
                    if sort_key not in self.VALID_ORDER_FIELDS:
                        raise ValidationError(f"Invalid order_by field: {sort_key}")
                    jobs.sort(key=lambda x: x.get(sort_key, ""), reverse=reverse)
                
                # Apply pagination
                if offset:
                    jobs = jobs[offset:]
                if limit:
                    jobs = jobs[:limit]
                
                return [JobRecord.from_dict(job) for job in jobs]

        except Exception as e:
            logger.error(f"Failed to list jobs: {e}")
            raise DatabaseError(f"Failed to list jobs: {str(e)}", operation="list_jobs")

    async def count_jobs(
        self,
        user_id: Optional[str] = None,
        job_type: Optional[str] = None,
        status: Optional[JobStatus] = None,
        priority: Optional[JobPriority] = None
    ) -> int:
        """Count jobs with filtering"""
        try:
            if self._use_database:
                query = self.table.select("COUNT(*)")
                
                # Apply filters
                if user_id:
                    query = query.eq("user_id", user_id)
                if job_type:
                    query = query.eq("job_type", job_type)
                if status:
                    query = query.eq("status", status.value)
                if priority:
                    query = query.eq("priority", priority.value)
                
                response = self._execute_query(query, operation="count_jobs")
                return response[0].get("count", 0) if response else 0
            else:
                # In-memory storage counting
                jobs = list(self._jobs.values())
                
                # Apply filters
                if user_id:
                    jobs = [j for j in jobs if j.get("user_id") == user_id]
                if job_type:
                    jobs = [j for j in jobs if j.get("job_type") == job_type]
                if status:
                    jobs = [j for j in jobs if j.get("status") == status.value]
                if priority:
                    jobs = [j for j in jobs if j.get("priority") == priority.value]
                
                return len(jobs)

        except Exception as e:
            logger.error(f"Failed to count jobs: {e}")
            raise DatabaseError(f"Failed to count jobs: {str(e)}", operation="count_jobs")

    # ========== UPDATE OPERATIONS ==========

    async def update_job(self, job_id: str, update_data: Dict[str, Any]) -> JobRecord:
        """
        Update a job record.
        Pure UPDATE operation with validation.
        """
        if not job_id:
            raise ValidationError("job_id cannot be empty")

        if not update_data:
            raise ValidationError("update_data cannot be empty")

        try:
            # Validate the job exists
            existing_job = await self.get_job(job_id)
            if not existing_job:
                raise JobNotFoundError(job_id)

            # Validate enum fields if provided
            if "status" in update_data:
                status = update_data["status"]
                if isinstance(status, str) and status not in self.VALID_STATUSES:
                    raise InvalidJobStatusError(status, list(self.VALID_STATUSES))
                update_data["status"] = status

            if "priority" in update_data:
                priority = update_data["priority"]
                if isinstance(priority, str) and priority not in self.VALID_PRIORITIES:
                    raise InvalidJobPriorityError(priority, list(self.VALID_PRIORITIES))
                update_data["priority"] = priority

            if "job_type" in update_data:
                job_type = update_data["job_type"]
                if isinstance(job_type, str) and job_type not in self.VALID_JOB_TYPES:
                    raise InvalidJobTypeError(job_type, list(self.VALID_JOB_TYPES))
                update_data["job_type"] = job_type

            if "recurrence_interval" in update_data:
                recurrence_interval = update_data["recurrence_interval"]
                if recurrence_interval is not None:
                    if isinstance(recurrence_interval, str):
                        if recurrence_interval not in self.VALID_INTERVALS:
                            raise ValidationError(f"Invalid recurrence_interval: {recurrence_interval}")
                        update_data["recurrence_interval"] = recurrence_interval
                    elif not isinstance(recurrence_interval, RecurrenceInterval):
                        raise ValidationError(f"Invalid recurrence_interval: {recurrence_interval}")

            # Add updated timestamp
            update_data["updated_at"] = datetime.utcnow().isoformat()

            # Convert datetime objects to ISO strings
            for key, value in update_data.items():
                if isinstance(value, datetime):
                    update_data[key] = value.isoformat()

            if self._use_database:
                response = self._execute_query(
                    self.table.update(update_data).eq("job_id", job_id).select("*"),
                    operation="update_job"
                )
                
                if not response or len(response) == 0:
                    raise DatabaseError(f"Failed to update job {job_id}", operation="update_job")
                
                return JobRecord.from_dict(response[0])
            else:
                # In-memory storage with concurrency protection
                async with self._lock:
                    if job_id not in self._jobs:
                        raise JobNotFoundError(job_id)
                    
                    self._jobs[job_id].update(update_data)
                    return JobRecord.from_dict(self._jobs[job_id])

        except (JobNotFoundError, InvalidJobTypeError, InvalidJobStatusError, InvalidJobPriorityError, ValidationError, DatabaseError):
            raise
        except Exception as e:
            logger.error(f"Failed to update job {job_id}: {e}")
            raise DatabaseError(f"Failed to update job: {str(e)}", operation="update_job")

    # ========== DELETE OPERATIONS ==========

    async def delete_job(self, job_id: str) -> bool:
        """
        Delete a job record.
        Use with caution - this removes the job permanently.
        """
        if not job_id:
            raise ValidationError("job_id cannot be empty")

        try:
            # Verify job exists
            existing_job = await self.get_job(job_id)
            if not existing_job:
                raise JobNotFoundError(job_id)

            if self._use_database:
                response = self._execute_query(
                    self.table.delete().eq("job_id", job_id),
                    operation="delete_job"
                )
                logger.warning(f"DELETED job {job_id}")
                return True
            else:
                # In-memory storage with concurrency protection
                async with self._lock:
                    if job_id in self._jobs:
                        del self._jobs[job_id]
                        logger.warning(f"DELETED job {job_id}")
                        return True
                    return False

        except JobNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Failed to delete job {job_id}: {e}")
            raise DatabaseError(f"Failed to delete job: {str(e)}", operation="delete_job")

    # ========== ANALYTICS OPERATIONS ==========

    async def get_job_stats(self, user_id: Optional[str] = None) -> JobStats:
        """
        Get job statistics.
        Pure analytics READ operation.
        """
        try:
            # Get all jobs for user or system-wide
            jobs = await self.list_jobs(user_id=user_id, limit=None)
            
            return JobStats.from_jobs(user_id, jobs)

        except Exception as e:
            logger.error(f"Failed to get job stats: {e}")
            raise DatabaseError(f"Failed to get job stats: {str(e)}", operation="get_job_stats")

    # ========== HEALTH CHECK ==========

    async def health_check(self) -> Dict[str, Any]:
        """Repository health check"""
        try:
            if self._use_database:
                # Test database connection with a simple query
                response = self._execute_query(
                    self.table.select("COUNT(*)").limit(1),
                    operation="health_check"
                )
                
                return {
                    "status": "healthy",
                    "storage": "database",
                    "connection": "ok"
                }
            else:
                return {
                    "status": "healthy",
                    "storage": "in_memory",
                    "job_count": len(self._jobs)
                }

        except Exception as e:
            logger.error(f"Repository health check failed: {e}")
            return {
                "status": "unhealthy",
                "error": str(e)
            }

    # ========== PRIVATE HELPER METHODS ==========

    def _execute_query(self, query: QueryBuilder, operation: str) -> Any:
        """
        Execute a query with proper error handling.
        Centralized error handling pattern from BillingRepository.
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