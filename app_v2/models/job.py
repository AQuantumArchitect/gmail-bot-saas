# app/models/job.py
"""
Job domain models and data structures.
Complete set of models for job management, processing workflows, and job analytics.
"""
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from uuid import UUID, uuid4
from enum import Enum
from pydantic import BaseModel, Field, validator


# ========== ENUMS ==========

class JobStatus(Enum):
    """Job status enumeration"""
    PENDING = "pending"
    RUNNING = "running" 
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRYING = "retrying"


class JobType(Enum):
    """Job type enumeration"""
    EMAIL_PROCESSING = "email_processing"
    EMAIL_DISCOVERY = "email_discovery"
    DATA_SYNC = "data_sync"  # Generic sync job - use metadata to specify source (gmail, outlook, etc.)
    BATCH_PROCESSING = "batch_processing"
    SYSTEM_MAINTENANCE = "system_maintenance"
    USER_CLEANUP = "user_cleanup"
    ANALYTICS_GENERATION = "analytics_generation"


class JobPriority(Enum):
    """Job priority enumeration"""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class RecurrenceInterval(Enum):
    """Recurrence interval enumeration"""
    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


# ========== CORE MODELS ==========

class JobRecord(BaseModel):
    """
    Represents a job record from the database.
    Immutable record of all job-related activities and state transitions.
    """
    job_id: str
    user_id: str
    job_type: JobType
    priority: JobPriority = JobPriority.NORMAL
    status: JobStatus = JobStatus.PENDING
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    # Scheduling
    scheduled_for: datetime
    max_retries: int = 3
    attempts: int = 0
    
    # Execution tracking
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    failed_at: Optional[datetime] = None
    worker_id: Optional[str] = None
    
    # Error handling
    last_error: Optional[str] = None
    result: Dict[str, Any] = Field(default_factory=dict)
    processing_time: Optional[float] = None  # seconds
    
    # Recurring jobs
    recurrence_interval: Optional[RecurrenceInterval] = None
    parent_job_id: Optional[str] = None
    
    # Timestamps
    created_at: datetime
    updated_at: datetime
    
    @validator('job_type')
    def validate_job_type(cls, v):
        if isinstance(v, str):
            try:
                return JobType(v)
            except ValueError:
                valid_types = [t.value for t in JobType]
                raise ValueError(f"Invalid job type. Must be one of: {valid_types}")
        return v
    
    @validator('status')
    def validate_status(cls, v):
        if isinstance(v, str):
            try:
                return JobStatus(v)
            except ValueError:
                valid_statuses = [s.value for s in JobStatus]
                raise ValueError(f"Invalid status. Must be one of: {valid_statuses}")
        return v
    
    @validator('priority')
    def validate_priority(cls, v):
        if isinstance(v, str):
            try:
                return JobPriority(v)
            except ValueError:
                valid_priorities = [p.value for p in JobPriority]
                raise ValueError(f"Invalid priority. Must be one of: {valid_priorities}")
        return v
    
    @validator('attempts')
    def validate_attempts(cls, v, values):
        max_retries = values.get('max_retries', 3)
        if v > max_retries:
            raise ValueError(f"Attempts ({v}) cannot exceed max_retries ({max_retries})")
        return v
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "JobRecord":
        """Create JobRecord from dictionary (e.g., from database)"""
        # Make a copy to avoid modifying the original
        data = data.copy()
        
        # Handle enum conversions
        if 'job_type' in data and isinstance(data['job_type'], str):
            data['job_type'] = JobType(data['job_type'])
        if 'status' in data and isinstance(data['status'], str):
            data['status'] = JobStatus(data['status'])
        if 'priority' in data and isinstance(data['priority'], str):
            data['priority'] = JobPriority(data['priority'])
        if 'recurrence_interval' in data and isinstance(data['recurrence_interval'], str):
            data['recurrence_interval'] = RecurrenceInterval(data['recurrence_interval'])
        
        # Handle datetime conversions
        datetime_fields = [
            'scheduled_for', 'started_at', 'completed_at', 'failed_at', 
            'created_at', 'updated_at'
        ]
        
        for field in datetime_fields:
            if field in data and data[field]:
                if isinstance(data[field], str):
                    # Handle both ISO format with and without Z suffix
                    datetime_str = data[field]
                    if datetime_str.endswith('Z'):
                        datetime_str = datetime_str[:-1] + '+00:00'
                    try:
                        data[field] = datetime.fromisoformat(datetime_str)
                    except ValueError:
                        # Fallback for any other datetime format issues
                        data[field] = datetime.utcnow()
                elif not isinstance(data[field], datetime):
                    data[field] = datetime.utcnow()
        
        # Ensure required datetime fields have defaults
        now = datetime.utcnow()
        if 'scheduled_for' not in data or not data['scheduled_for']:
            data['scheduled_for'] = now
        if 'created_at' not in data or not data['created_at']:
            data['created_at'] = now
        if 'updated_at' not in data or not data['updated_at']:
            data['updated_at'] = now
        
        # Ensure dictionaries are dicts
        if not isinstance(data.get('metadata'), dict):
            data['metadata'] = {}
        if not isinstance(data.get('result'), dict):
            data['result'] = {}
        
        # Ensure job_id exists
        if 'job_id' not in data or not data['job_id']:
            data['job_id'] = str(uuid4())
        
        return cls(**data)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for database storage"""
        data = self.dict()
        
        # Convert enums to strings
        data['job_type'] = data['job_type'].value
        data['status'] = data['status'].value
        data['priority'] = data['priority'].value
        if data.get('recurrence_interval'):
            data['recurrence_interval'] = data['recurrence_interval'].value
        
        # Convert datetimes to ISO strings
        datetime_fields = [
            'scheduled_for', 'started_at', 'completed_at', 'failed_at',
            'created_at', 'updated_at'
        ]
        
        for field in datetime_fields:
            if data.get(field):
                data[field] = data[field].isoformat()
        
        return data
    
    # Status checking properties
    @property
    def is_pending(self) -> bool:
        """Check if job is pending"""
        return self.status == JobStatus.PENDING
    
    @property
    def is_running(self) -> bool:
        """Check if job is running"""
        return self.status == JobStatus.RUNNING
    
    @property
    def is_completed(self) -> bool:
        """Check if job is completed"""
        return self.status == JobStatus.COMPLETED
    
    @property
    def is_failed(self) -> bool:
        """Check if job is failed"""
        return self.status == JobStatus.FAILED
    
    @property
    def is_cancelled(self) -> bool:
        """Check if job is cancelled"""
        return self.status == JobStatus.CANCELLED
    
    @property
    def is_finished(self) -> bool:
        """Check if job is in a terminal state"""
        return self.status in [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED]
    
    @property
    def can_be_retried(self) -> bool:
        """Check if job can be retried"""
        return (
            self.status == JobStatus.FAILED and 
            self.attempts < self.max_retries
        )
    
    @property
    def is_overdue(self) -> bool:
        """Check if job is overdue for execution"""
        return (
            self.status == JobStatus.PENDING and 
            self.scheduled_for < datetime.utcnow()
        )
    
    @property
    def is_stale(self, timeout_minutes: int = 30) -> bool:
        """Check if running job is stale (running too long)"""
        if not self.is_running or not self.started_at:
            return False
        
        timeout_delta = timedelta(minutes=timeout_minutes)
        return datetime.utcnow() - self.started_at > timeout_delta
    
    @property
    def runtime_seconds(self) -> Optional[float]:
        """Get job runtime in seconds if available"""
        if self.processing_time:
            return self.processing_time
        
        if self.started_at:
            end_time = self.completed_at or self.failed_at or datetime.utcnow()
            return (end_time - self.started_at).total_seconds()
        
        return None
    
    @property
    def is_recurring(self) -> bool:
        """Check if this is a recurring job"""
        return self.recurrence_interval is not None
    
    def get_next_run_time(self) -> Optional[datetime]:
        """Calculate next run time for recurring jobs"""
        if not self.is_recurring or not self.completed_at:
            return None
        
        if self.recurrence_interval == RecurrenceInterval.HOURLY:
            return self.completed_at + timedelta(hours=1)
        elif self.recurrence_interval == RecurrenceInterval.DAILY:
            return self.completed_at + timedelta(days=1)
        elif self.recurrence_interval == RecurrenceInterval.WEEKLY:
            return self.completed_at + timedelta(weeks=1)
        elif self.recurrence_interval == RecurrenceInterval.MONTHLY:
            return self.completed_at + timedelta(days=30)  # Approximate
        
        return None


class JobStats(BaseModel):
    """Statistics and analytics for jobs"""
    user_id: Optional[str] = None  # None for system-wide stats
    total_jobs: int = 0
    completed_jobs: int = 0
    failed_jobs: int = 0
    pending_jobs: int = 0
    running_jobs: int = 0
    cancelled_jobs: int = 0
    success_rate: float = 0.0
    average_processing_time: float = 0.0
    jobs_by_type: Dict[str, int] = Field(default_factory=dict)
    jobs_by_priority: Dict[str, int] = Field(default_factory=dict)
    
    @classmethod
    def from_jobs(cls, user_id: Optional[str], jobs: List[JobRecord]) -> "JobStats":
        """Create statistics from a list of jobs"""
        if not jobs:
            return cls(user_id=user_id)
        
        total = len(jobs)
        completed = len([j for j in jobs if j.status == JobStatus.COMPLETED])
        failed = len([j for j in jobs if j.status == JobStatus.FAILED])
        pending = len([j for j in jobs if j.status == JobStatus.PENDING])
        running = len([j for j in jobs if j.status == JobStatus.RUNNING])
        cancelled = len([j for j in jobs if j.status == JobStatus.CANCELLED])
        
        # Calculate success rate
        finished_jobs = completed + failed
        success_rate = (completed / finished_jobs * 100) if finished_jobs > 0 else 0.0
        
        # Calculate average processing time
        processing_times = [j.runtime_seconds for j in jobs if j.runtime_seconds is not None]
        avg_time = sum(processing_times) / len(processing_times) if processing_times else 0.0
        
        # Jobs by type
        jobs_by_type = {}
        for job in jobs:
            job_type = job.job_type.value
            jobs_by_type[job_type] = jobs_by_type.get(job_type, 0) + 1
        
        # Jobs by priority
        jobs_by_priority = {}
        for job in jobs:
            priority = job.priority.value
            jobs_by_priority[priority] = jobs_by_priority.get(priority, 0) + 1
        
        return cls(
            user_id=user_id,
            total_jobs=total,
            completed_jobs=completed,
            failed_jobs=failed,
            pending_jobs=pending,
            running_jobs=running,
            cancelled_jobs=cancelled,
            success_rate=round(success_rate, 2),
            average_processing_time=round(avg_time, 2),
            jobs_by_type=jobs_by_type,
            jobs_by_priority=jobs_by_priority
        )
    
    @property
    def completion_rate(self) -> float:
        """Get completion rate as percentage"""
        if self.total_jobs == 0:
            return 0.0
        return round((self.completed_jobs / self.total_jobs) * 100, 2)
    
    @property
    def failure_rate(self) -> float:
        """Get failure rate as percentage"""
        if self.total_jobs == 0:
            return 0.0
        return round((self.failed_jobs / self.total_jobs) * 100, 2)
    
    @property
    def most_common_job_type(self) -> Optional[str]:
        """Get the most common job type"""
        if not self.jobs_by_type:
            return None
        return max(self.jobs_by_type.keys(), key=lambda k: self.jobs_by_type[k])
    
    @property
    def most_common_priority(self) -> Optional[str]:
        """Get the most common priority level"""
        if not self.jobs_by_priority:
            return None
        return max(self.jobs_by_priority.keys(), key=lambda k: self.jobs_by_priority[k])


class JobQueue(BaseModel):
    """Represents current job queue status"""
    total_pending: int = 0
    total_running: int = 0
    queue_depth_by_priority: Dict[str, int] = Field(default_factory=dict)
    queue_depth_by_type: Dict[str, int] = Field(default_factory=dict)
    oldest_pending_job: Optional[datetime] = None
    longest_running_job: Optional[datetime] = None
    estimated_wait_time: Optional[int] = None  # seconds
    
    @classmethod
    def from_jobs(cls, pending_jobs: List[JobRecord], running_jobs: List[JobRecord]) -> "JobQueue":
        """Create queue status from job lists"""
        # Priority breakdown
        priority_counts = {}
        for job in pending_jobs:
            priority = job.priority.value
            priority_counts[priority] = priority_counts.get(priority, 0) + 1
        
        # Type breakdown
        type_counts = {}
        for job in pending_jobs:
            job_type = job.job_type.value
            type_counts[job_type] = type_counts.get(job_type, 0) + 1
        
        # Find oldest pending and longest running
        oldest_pending = None
        if pending_jobs:
            oldest_pending = min(job.scheduled_for for job in pending_jobs)
        
        longest_running = None
        if running_jobs:
            longest_running = min(job.started_at for job in running_jobs if job.started_at)
        
        # Estimate wait time (simple heuristic)
        avg_processing_time = 300  # 5 minutes default
        if running_jobs:
            processing_times = [
                job.runtime_seconds for job in running_jobs 
                if job.runtime_seconds and job.runtime_seconds > 0
            ]
            if processing_times:
                avg_processing_time = sum(processing_times) / len(processing_times)
        
        estimated_wait = int(len(pending_jobs) * avg_processing_time / max(1, len(running_jobs)))
        
        return cls(
            total_pending=len(pending_jobs),
            total_running=len(running_jobs),
            queue_depth_by_priority=priority_counts,
            queue_depth_by_type=type_counts,
            oldest_pending_job=oldest_pending,
            longest_running_job=longest_running,
            estimated_wait_time=estimated_wait
        )
    
    @property
    def is_overloaded(self) -> bool:
        """Check if queue appears overloaded"""
        return self.total_pending > 100 or self.estimated_wait_time > 3600  # 1 hour
    
    @property
    def is_healthy(self) -> bool:
        """Check if queue is in healthy state"""
        return (
            self.total_pending < 50 and 
            self.estimated_wait_time < 1800 and  # 30 minutes
            self.total_running > 0
        )


class JobBatch(BaseModel):
    """Represents a batch of related jobs"""
    batch_id: str
    name: str
    description: Optional[str] = None
    job_ids: List[str] = Field(default_factory=list)
    created_by: str
    status: str = "pending"  # pending, running, completed, failed
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    
    @property
    def job_count(self) -> int:
        """Get number of jobs in batch"""
        return len(self.job_ids)
    
    @property
    def is_completed(self) -> bool:
        """Check if batch is completed"""
        return self.status == "completed"
    
    @property
    def is_failed(self) -> bool:
        """Check if batch failed"""
        return self.status == "failed"
    
    def add_job(self, job_id: str) -> None:
        """Add a job to the batch"""
        if job_id not in self.job_ids:
            self.job_ids.append(job_id)
    
    def remove_job(self, job_id: str) -> bool:
        """Remove a job from the batch"""
        if job_id in self.job_ids:
            self.job_ids.remove(job_id)
            return True
        return False


# ========== API RESPONSE MODELS ==========

class JobResponse(BaseModel):
    """API response for job operations"""
    job_id: str
    user_id: str
    job_type: str
    status: str
    priority: str
    scheduled_for: str
    created_at: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    @classmethod
    def from_job(cls, job: JobRecord) -> "JobResponse":
        """Create response from JobRecord"""
        return cls(
            job_id=job.job_id,
            user_id=job.user_id,
            job_type=job.job_type.value,
            status=job.status.value,
            priority=job.priority.value,
            scheduled_for=job.scheduled_for.isoformat(),
            created_at=job.created_at.isoformat(),
            metadata=job.metadata
        )


class JobListResponse(BaseModel):
    """API response for job listing"""
    jobs: List[JobResponse]
    total_count: int
    page: int = 1
    page_size: int = 100
    has_more: bool = False
    
    @classmethod
    def from_jobs(
        cls, 
        jobs: List[JobRecord], 
        total_count: int,
        page: int = 1,
        page_size: int = 100
    ) -> "JobListResponse":
        """Create response from job list"""
        job_responses = [JobResponse.from_job(job) for job in jobs]
        has_more = total_count > (page * page_size)
        
        return cls(
            jobs=job_responses,
            total_count=total_count,
            page=page,
            page_size=page_size,
            has_more=has_more
        )


class JobStatsResponse(BaseModel):
    """API response for job statistics"""
    user_id: Optional[str]
    total_jobs: int
    success_rate: float
    completion_rate: float
    failure_rate: float
    average_processing_time: float
    jobs_by_status: Dict[str, int]
    jobs_by_type: Dict[str, int]
    jobs_by_priority: Dict[str, int]
    
    @classmethod
    def from_stats(cls, stats: JobStats) -> "JobStatsResponse":
        """Create response from JobStats"""
        jobs_by_status = {
            "completed": stats.completed_jobs,
            "failed": stats.failed_jobs,
            "pending": stats.pending_jobs,
            "running": stats.running_jobs,
            "cancelled": stats.cancelled_jobs
        }
        
        return cls(
            user_id=stats.user_id,
            total_jobs=stats.total_jobs,
            success_rate=stats.success_rate,
            completion_rate=stats.completion_rate,
            failure_rate=stats.failure_rate,
            average_processing_time=stats.average_processing_time,
            jobs_by_status=jobs_by_status,
            jobs_by_type=stats.jobs_by_type,
            jobs_by_priority=stats.jobs_by_priority
        )


class JobQueueResponse(BaseModel):
    """API response for job queue status"""
    total_pending: int
    total_running: int
    queue_status: str  # healthy, overloaded, degraded
    estimated_wait_time: Optional[int]
    queue_depth_by_priority: Dict[str, int]
    queue_depth_by_type: Dict[str, int]
    
    @classmethod
    def from_queue(cls, queue: JobQueue) -> "JobQueueResponse":
        """Create response from JobQueue"""
        # Determine queue status
        if queue.is_healthy:
            status = "healthy"
        elif queue.is_overloaded:
            status = "overloaded"
        else:
            status = "degraded"
        
        return cls(
            total_pending=queue.total_pending,
            total_running=queue.total_running,
            queue_status=status,
            estimated_wait_time=queue.estimated_wait_time,
            queue_depth_by_priority=queue.queue_depth_by_priority,
            queue_depth_by_type=queue.queue_depth_by_type
        )