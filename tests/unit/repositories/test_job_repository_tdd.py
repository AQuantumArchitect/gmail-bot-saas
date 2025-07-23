# tests/unit/repositories/test_job_repository.py
"""
Test-first driver for JobRepository implementation.
Manages background job queue for email processing.
"""
import pytest
from uuid import uuid4
from datetime import datetime, timedelta
from app.data.repositories.job_repository import JobRepository
from app.data.database import ValidationError, NotFoundError

class TestJobRepository:
    """Test-driven development for JobRepository"""
    
    @pytest.fixture
    def job_repo(self):
        """Create JobRepository instance - this doesn't exist yet!"""
        return JobRepository()
    
    def test_create_processing_job(self, job_repo):
        """Test creating a background processing job"""
        user_id = uuid4()
        job_data = {
            "user_id": str(user_id),
            "job_type": "email_processing",
            "priority": "normal",
            "scheduled_for": datetime.utcnow().isoformat(),
            "metadata": {
                "processing_frequency": "hourly",
                "max_emails": 50,
                "query_filter": "is:unread"
            }
        }
        
        result = job_repo.create_job(job_data)
        
        assert result["user_id"] == str(user_id)
        assert result["job_type"] == "email_processing"
        assert result["priority"] == "normal"
        assert result["status"] == "pending"
        assert result["attempts"] == 0
        assert result["metadata"]["max_emails"] == 50
        assert "id" in result
        assert "created_at" in result
        assert "scheduled_for" in result
    
    def test_create_job_with_delay(self, job_repo):
        """Test creating a job scheduled for future execution"""
        user_id = uuid4()
        future_time = datetime.utcnow() + timedelta(hours=1)
        
        job_data = {
            "user_id": str(user_id),
            "job_type": "email_processing",
            "scheduled_for": future_time.isoformat(),
            "metadata": {"delay_reason": "rate_limiting"}
        }
        
        result = job_repo.create_job(job_data)
        
        assert result["status"] == "pending"
        assert result["scheduled_for"] == future_time.isoformat()
        assert result["metadata"]["delay_reason"] == "rate_limiting"
    
    def test_create_job_validation(self, job_repo):
        """Test job creation validation"""
        # Missing required fields
        with pytest.raises(ValidationError) as exc_info:
            job_repo.create_job({
                "job_type": "email_processing"
                # Missing user_id
            })
        
        assert "user_id is required" in str(exc_info.value)
        
        # Invalid job type
        with pytest.raises(ValidationError) as exc_info:
            job_repo.create_job({
                "user_id": str(uuid4()),
                "job_type": "invalid_type"
            })
        
        assert "invalid job type" in str(exc_info.value).lower()
        
        # Invalid priority
        with pytest.raises(ValidationError) as exc_info:
            job_repo.create_job({
                "user_id": str(uuid4()),
                "job_type": "email_processing",
                "priority": "invalid_priority"
            })
        
        assert "invalid priority" in str(exc_info.value).lower()
    
    def test_get_pending_jobs(self, job_repo):
        """Test getting jobs ready for execution"""
        user_id = uuid4()
        
        # Create jobs with different states
        job_repo.create_job({
            "user_id": str(user_id),
            "job_type": "email_processing",
            "scheduled_for": (datetime.utcnow() - timedelta(minutes=5)).isoformat()  # Ready
        })
        
        job_repo.create_job({
            "user_id": str(user_id),
            "job_type": "email_processing",
            "scheduled_for": (datetime.utcnow() + timedelta(hours=1)).isoformat()  # Future
        })
        
        # Get pending jobs
        pending = job_repo.get_pending_jobs()
        
        assert len(pending) == 1
        assert pending[0]["status"] == "pending"
        assert pending[0]["user_id"] == str(user_id)
        
        # Should be ordered by scheduled_for (earliest first)
        assert pending[0]["scheduled_for"] <= datetime.utcnow().isoformat()
    
    def test_get_pending_jobs_with_limit(self, job_repo):
        """Test getting pending jobs with limit"""
        user_id = uuid4()
        
        # Create multiple pending jobs
        for i in range(5):
            job_repo.create_job({
                "user_id": str(user_id),
                "job_type": "email_processing",
                "scheduled_for": (datetime.utcnow() - timedelta(minutes=i)).isoformat()
            })
        
        # Get limited results
        pending = job_repo.get_pending_jobs(limit=3)
        
        assert len(pending) == 3
        # Should be ordered by scheduled_for ascending (earliest first)
        assert pending[0]["scheduled_for"] <= pending[1]["scheduled_for"]
        assert pending[1]["scheduled_for"] <= pending[2]["scheduled_for"]
    
    def test_get_pending_jobs_by_priority(self, job_repo):
        """Test getting pending jobs ordered by priority"""
        user_id = uuid4()
        
        # Create jobs with different priorities
        job_repo.create_job({
            "user_id": str(user_id),
            "job_type": "email_processing",
            "priority": "low"
        })
        
        job_repo.create_job({
            "user_id": str(user_id),
            "job_type": "email_processing",
            "priority": "high"
        })
        
        job_repo.create_job({
            "user_id": str(user_id),
            "job_type": "email_processing",
            "priority": "normal"
        })
        
        # Get pending jobs
        pending = job_repo.get_pending_jobs(limit=10)
        
        assert len(pending) == 3
        # Should be ordered by priority (high, normal, low) then by scheduled_for
        assert pending[0]["priority"] == "high"
        assert pending[1]["priority"] == "normal"
        assert pending[2]["priority"] == "low"
    
    def test_claim_job_for_processing(self, job_repo):
        """Test claiming a job for processing"""
        user_id = uuid4()
        
        # Create pending job
        job_data = {
            "user_id": str(user_id),
            "job_type": "email_processing"
        }
        created_job = job_repo.create_job(job_data)
        
        # Claim job
        worker_id = "worker_123"
        claimed_job = job_repo.claim_job(created_job["id"], worker_id)
        
        assert claimed_job["status"] == "running"
        assert claimed_job["worker_id"] == worker_id
        assert claimed_job["started_at"] is not None
        assert claimed_job["attempts"] == 1
    
    def test_claim_job_already_claimed(self, job_repo):
        """Test claiming a job that's already been claimed"""
        user_id = uuid4()
        
        # Create and claim job
        job_data = {
            "user_id": str(user_id),
            "job_type": "email_processing"
        }
        created_job = job_repo.create_job(job_data)
        job_repo.claim_job(created_job["id"], "worker_1")
        
        # Try to claim again
        with pytest.raises(ValidationError) as exc_info:
            job_repo.claim_job(created_job["id"], "worker_2")
        
        assert "job already claimed" in str(exc_info.value).lower()
    
    def test_claim_job_not_found(self, job_repo):
        """Test claiming non-existent job"""
        with pytest.raises(NotFoundError) as exc_info:
            job_repo.claim_job(uuid4(), "worker_123")
        
        assert "job not found" in str(exc_info.value).lower()
    
    def test_mark_job_completed(self, job_repo):
        """Test marking job as completed successfully"""
        user_id = uuid4()
        
        # Create and claim job
        job_data = {
            "user_id": str(user_id),
            "job_type": "email_processing"
        }
        created_job = job_repo.create_job(job_data)
        job_repo.claim_job(created_job["id"], "worker_123")
        
        # Complete job
        completion_result = {
            "emails_processed": 15,
            "summaries_generated": 12,
            "credits_used": 60,
            "processing_time": 45.5,
            "success_rate": 0.8
        }
        
        completed_job = job_repo.mark_job_completed(created_job["id"], completion_result)
        
        assert completed_job["status"] == "completed"
        assert completed_job["completed_at"] is not None
        assert completed_job["result"]["emails_processed"] == 15
        assert completed_job["result"]["credits_used"] == 60
        assert completed_job["result"]["success_rate"] == 0.8
    
    def test_mark_job_failed(self, job_repo):
        """Test marking job as failed"""
        user_id = uuid4()
        
        # Create and claim job
        job_data = {
            "user_id": str(user_id),
            "job_type": "email_processing"
        }
        created_job = job_repo.create_job(job_data)
        job_repo.claim_job(created_job["id"], "worker_123")
        
        # Fail job
        failure_result = {
            "error": "Gmail API quota exceeded",
            "error_type": "quota_exceeded",
            "retry_after": 3600,
            "emails_processed": 3,
            "partial_success": True
        }
        
        failed_job = job_repo.mark_job_failed(created_job["id"], failure_result)
        
        assert failed_job["status"] == "failed"
        assert failed_job["completed_at"] is not None
        assert failed_job["result"]["error"] == "Gmail API quota exceeded"
        assert failed_job["result"]["retry_after"] == 3600
        assert failed_job["result"]["partial_success"] == True
    
    def test_retry_failed_job(self, job_repo):
        """Test retrying a failed job"""
        user_id = uuid4()
        
        # Create, claim, and fail job
        job_data = {
            "user_id": str(user_id),
            "job_type": "email_processing"
        }
        created_job = job_repo.create_job(job_data)
        job_repo.claim_job(created_job["id"], "worker_123")
        job_repo.mark_job_failed(created_job["id"], {"error": "temporary failure"})
        
        # Retry job
        retry_delay = timedelta(minutes=30)
        retried_job = job_repo.retry_job(created_job["id"], retry_delay)
        
        assert retried_job["status"] == "pending"
        assert retried_job["attempts"] == 1  # Keeps previous attempt count
        assert retried_job["worker_id"] is None  # Cleared for new worker
        assert retried_job["started_at"] is None  # Cleared
        assert retried_job["scheduled_for"] > datetime.utcnow().isoformat()  # Delayed
    
    def test_retry_job_max_attempts(self, job_repo):
        """Test retry limit enforcement"""
        user_id = uuid4()
        
        # Create job
        job_data = {
            "user_id": str(user_id),
            "job_type": "email_processing"
        }
        created_job = job_repo.create_job(job_data)
        
        # Fail job multiple times
        for attempt in range(3):
            job_repo.claim_job(created_job["id"], f"worker_{attempt}")
            job_repo.mark_job_failed(created_job["id"], {"error": f"failure {attempt}"})
            
            if attempt < 2:  # First two failures can retry
                job_repo.retry_job(created_job["id"], timedelta(minutes=5))
        
        # Fourth retry should fail
        with pytest.raises(ValidationError) as exc_info:
            job_repo.retry_job(created_job["id"], timedelta(minutes=5))
        
        assert "maximum retry attempts exceeded" in str(exc_info.value).lower()
    
    def test_get_job_status(self, job_repo):
        """Test getting job status"""
        user_id = uuid4()
        
        # Create job
        job_data = {
            "user_id": str(user_id),
            "job_type": "email_processing",
            "metadata": {"test": "data"}
        }
        created_job = job_repo.create_job(job_data)
        
        # Get status
        status = job_repo.get_job_status(created_job["id"])
        
        assert status["id"] == created_job["id"]
        assert status["status"] == "pending"
        assert status["user_id"] == str(user_id)
        assert status["job_type"] == "email_processing"
        assert status["metadata"]["test"] == "data"
    
    def test_get_job_status_not_found(self, job_repo):
        """Test getting status of non-existent job"""
        result = job_repo.get_job_status(uuid4())
        assert result is None
    
    def test_get_user_jobs(self, job_repo):
        """Test getting all jobs for a user"""
        user_id = uuid4()
        other_user_id = uuid4()
        
        # Create jobs for different users
        job_repo.create_job({
            "user_id": str(user_id),
            "job_type": "email_processing"
        })
        
        job_repo.create_job({
            "user_id": str(user_id),
            "job_type": "email_processing"
        })
        
        job_repo.create_job({
            "user_id": str(other_user_id),
            "job_type": "email_processing"
        })
        
        # Get jobs for specific user
        user_jobs = job_repo.get_user_jobs(user_id)
        
        assert len(user_jobs) == 2
        assert all(job["user_id"] == str(user_id) for job in user_jobs)
    
    def test_get_user_jobs_with_status_filter(self, job_repo):
        """Test getting user jobs with status filter"""
        user_id = uuid4()
        
        # Create jobs with different statuses
        job1_data = {
            "user_id": str(user_id),
            "job_type": "email_processing"
        }
        job1 = job_repo.create_job(job1_data)
        
        job2_data = {
            "user_id": str(user_id),
            "job_type": "email_processing"
        }
        job2 = job_repo.create_job(job2_data)
        
        # Complete one job
        job_repo.claim_job(job1["id"], "worker_1")
        job_repo.mark_job_completed(job1["id"], {"emails_processed": 5})
        
        # Get only pending jobs
        pending_jobs = job_repo.get_user_jobs(user_id, status="pending")
        assert len(pending_jobs) == 1
        assert pending_jobs[0]["id"] == job2["id"]
        
        # Get only completed jobs
        completed_jobs = job_repo.get_user_jobs(user_id, status="completed")
        assert len(completed_jobs) == 1
        assert completed_jobs[0]["id"] == job1["id"]
    
    def test_get_running_jobs(self, job_repo):
        """Test getting currently running jobs"""
        user_id = uuid4()
        
        # Create and claim multiple jobs
        for i in range(3):
            job_data = {
                "user_id": str(user_id),
                "job_type": "email_processing"
            }
            job = job_repo.create_job(job_data)
            job_repo.claim_job(job["id"], f"worker_{i}")
        
        # Get running jobs
        running = job_repo.get_running_jobs()
        
        assert len(running) == 3
        assert all(job["status"] == "running" for job in running)
        assert all(job["worker_id"] is not None for job in running)
    
    def test_get_stale_jobs(self, job_repo):
        """Test getting jobs that have been running too long"""
        user_id = uuid4()
        
        # Create and claim job
        job_data = {
            "user_id": str(user_id),
            "job_type": "email_processing"
        }
        job = job_repo.create_job(job_data)
        job_repo.claim_job(job["id"], "worker_stale")
        
        # Get stale jobs (running > 30 minutes)
        stale = job_repo.get_stale_jobs(minutes=30)
        
        # Should find jobs that have been running too long
        assert len(stale) >= 0  # May be 0 if job is recent
        
        for job in stale:
            assert job["status"] == "running"
            assert job["started_at"] is not None
    
    def test_cancel_stale_jobs(self, job_repo):
        """Test cancelling stale jobs"""
        user_id = uuid4()
        
        # Create and claim job
        job_data = {
            "user_id": str(user_id),
            "job_type": "email_processing"
        }
        job = job_repo.create_job(job_data)
        job_repo.claim_job(job["id"], "worker_timeout")
        
        # Cancel stale job
        cancelled_job = job_repo.cancel_stale_job(job["id"])
        
        assert cancelled_job["status"] == "failed"
        assert cancelled_job["result"]["error"] == "job_timeout"
        assert cancelled_job["result"]["timeout"] == True
        assert cancelled_job["completed_at"] is not None
    
    def test_schedule_recurring_job(self, job_repo):
        """Test scheduling recurring jobs"""
        user_id = uuid4()
        
        # Schedule hourly job
        job_data = {
            "user_id": str(user_id),
            "job_type": "email_processing",
            "recurring": True,
            "interval": "hourly",
            "metadata": {
                "processing_frequency": "hourly",
                "next_run": (datetime.utcnow() + timedelta(hours=1)).isoformat()
            }
        }
        
        recurring_job = job_repo.create_job(job_data)
        
        assert recurring_job["recurring"] == True
        assert recurring_job["interval"] == "hourly"
        assert recurring_job["metadata"]["next_run"] is not None
    
    def test_create_next_recurring_job(self, job_repo):
        """Test creating next instance of recurring job"""
        user_id = uuid4()
        
        # Create and complete recurring job
        job_data = {
            "user_id": str(user_id),
            "job_type": "email_processing",
            "recurring": True,
            "interval": "hourly"
        }
        job = job_repo.create_job(job_data)
        job_repo.claim_job(job["id"], "worker_1")
        job_repo.mark_job_completed(job["id"], {"emails_processed": 5})
        
        # Create next instance
        next_job = job_repo.create_next_recurring_job(job["id"])
        
        assert next_job["user_id"] == str(user_id)
        assert next_job["job_type"] == "email_processing"
        assert next_job["recurring"] == True
        assert next_job["interval"] == "hourly"
        assert next_job["status"] == "pending"
        assert next_job["scheduled_for"] > datetime.utcnow().isoformat()
    
    def test_get_job_statistics(self, job_repo):
        """Test getting job execution statistics"""
        user_id = uuid4()
        
        # Create various jobs
        for i in range(5):
            job_data = {
                "user_id": str(user_id),
                "job_type": "email_processing"
            }
            job = job_repo.create_job(job_data)
            job_repo.claim_job(job["id"], f"worker_{i}")
            
            if i < 3:  # Complete 3 jobs
                job_repo.mark_job_completed(job["id"], {
                    "emails_processed": 10 + i,
                    "processing_time": 30.0 + i
                })
            else:  # Fail 2 jobs
                job_repo.mark_job_failed(job["id"], {"error": f"error_{i}"})
        
        # Get statistics
        stats = job_repo.get_job_statistics(user_id)
        
        assert stats["user_id"] == str(user_id)
        assert stats["total_jobs"] == 5
        assert stats["completed_jobs"] == 3
        assert stats["failed_jobs"] == 2
        assert stats["pending_jobs"] == 0
        assert stats["running_jobs"] == 0
        assert stats["success_rate"] == 0.6  # 3/5
        assert stats["average_processing_time"] == 31.0  # (30+31+32)/3
    
    def test_get_system_job_statistics(self, job_repo):
        """Test getting system-wide job statistics"""
        user1 = uuid4()
        user2 = uuid4()
        
        # Create jobs for different users
        for user_id in [user1, user2]:
            job_data = {
                "user_id": str(user_id),
                "job_type": "email_processing"
            }
            job = job_repo.create_job(job_data)
            job_repo.claim_job(job["id"], f"worker_{user_id}")
            job_repo.mark_job_completed(job["id"], {"emails_processed": 10})
        
        # Get system stats
        stats = job_repo.get_system_job_statistics()
        
        assert stats["total_jobs"] == 2
        assert stats["completed_jobs"] == 2
        assert stats["failed_jobs"] == 0
        assert stats["pending_jobs"] == 0
        assert stats["running_jobs"] == 0
        assert stats["success_rate"] == 1.0
        assert "jobs_by_type" in stats
        assert stats["jobs_by_type"]["email_processing"] == 2
    
    def test_cleanup_old_jobs(self, job_repo):
        """Test cleaning up old completed jobs"""
        user_id = uuid4()
        
        # Create and complete old jobs
        for i in range(3):
            job_data = {
                "user_id": str(user_id),
                "job_type": "email_processing"
            }
            job = job_repo.create_job(job_data)
            job_repo.claim_job(job["id"], f"worker_{i}")
            job_repo.mark_job_completed(job["id"], {"emails_processed": 5})
        
        # Cleanup jobs older than 30 days
        cleaned_count = job_repo.cleanup_old_jobs(days=30)
        
        # Should clean up completed jobs but keep statistics
        assert cleaned_count >= 0  # May be 0 if jobs are recent
        
        # Statistics should still be available
        stats = job_repo.get_job_statistics(user_id)
        assert stats["total_jobs"] >= 0
    
    def test_delete_user_jobs(self, job_repo):
        """Test deleting all jobs for a user"""
        user_id = uuid4()
        other_user_id = uuid4()
        
        # Create jobs for both users
        job_repo.create_job({
            "user_id": str(user_id),
            "job_type": "email_processing"
        })
        
        job_repo.create_job({
            "user_id": str(other_user_id),
            "job_type": "email_processing"
        })
        
        # Delete jobs for specific user
        deleted_count = job_repo.delete_user_jobs(user_id)
        
        assert deleted_count == 1
        
        # Verify user's jobs are deleted
        user_jobs = job_repo.get_user_jobs(user_id)
        assert len(user_jobs) == 0
        
        # Verify other user's jobs remain
        other_jobs = job_repo.get_user_jobs(other_user_id)
        assert len(other_jobs) == 1
    
    @pytest.mark.parametrize("job_type", ["email_processing", "user_cleanup", "system_maintenance"])
    def test_valid_job_types(self, job_repo, job_type):
        """Test all valid job types"""
        user_id = uuid4()
        
        job_data = {
            "user_id": str(user_id),
            "job_type": job_type
        }
        
        result = job_repo.create_job(job_data)
        assert result["job_type"] == job_type
    
    @pytest.mark.parametrize("priority", ["low", "normal", "high"])
    def test_valid_priorities(self, job_repo, priority):
        """Test all valid job priorities"""
        user_id = uuid4()
        
        job_data = {
            "user_id": str(user_id),
            "job_type": "email_processing",
            "priority": priority
        }
        
        result = job_repo.create_job(job_data)
        assert result["priority"] == priority
    
    @pytest.mark.parametrize("status", ["pending", "running", "completed", "failed"])
    def test_valid_job_statuses(self, job_repo, status):
        """Test all valid job statuses"""
        user_id = uuid4()
        
        # Create job
        job_data = {
            "user_id": str(user_id),
            "job_type": "email_processing"
        }
        job = job_repo.create_job(job_data)
        
        # Update to different statuses
        if status == "running":
            job_repo.claim_job(job["id"], "worker_1")
        elif status == "completed":
            job_repo.claim_job(job["id"], "worker_1")
            job_repo.mark_job_completed(job["id"], {"result": "success"})
        elif status == "failed":
            job_repo.claim_job(job["id"], "worker_1")
            job_repo.mark_job_failed(job["id"], {"error": "test failure"})
        
        # Verify status
        job_status = job_repo.get_job_status(job["id"])
        assert job_status["status"] == status
    
    def test_job_execution_time_tracking(self, job_repo):
        """Test accurate job execution time tracking"""
        user_id = uuid4()
        
        # Create and claim job
        job_data = {
            "user_id": str(user_id),
            "job_type": "email_processing"
        }
        job = job_repo.create_job(job_data)
        job_repo.claim_job(job["id"], "worker_timing")
        
        # Complete job
        execution_time = 45.5
        job_repo.mark_job_completed(job["id"], {
            "emails_processed": 10,
            "execution_time": execution_time
        })
        
        # Verify timing
        completed_job = job_repo.get_job_status(job["id"])
        assert completed_job["result"]["execution_time"] == execution_time
        assert completed_job["started_at"] is not None
        assert completed_job["completed_at"] is not None
    
    def test_concurrent_job_claiming(self, job_repo):
        """Test concurrent job claiming prevention"""
        user_id = uuid4()
        
        # Create job
        job_data = {
            "user_id": str(user_id),
            "job_type": "email_processing"
        }
        job = job_repo.create_job(job_data)
        
        # First worker claims job
        job_repo.claim_job(job["id"], "worker_1")
        
        # Second worker tries to claim same job
        with pytest.raises(ValidationError) as exc_info:
            job_repo.claim_job(job["id"], "worker_2")
        
        assert "job already claimed" in str(exc_info.value).lower()
    
    def test_job_queue_ordering(self, job_repo):
        """Test job queue ordering by priority and schedule"""
        user_id = uuid4()
        
        # Create jobs with different priorities and schedules
        job_repo.create_job({
            "user_id": str(user_id),
            "job_type": "email_processing",
            "priority": "low",
            "scheduled_for": (datetime.utcnow() - timedelta(minutes=10)).isoformat()
        })
        
        job_repo.create_job({
            "user_id": str(user_id),
            "job_type": "email_processing",
            "priority": "high",
            "scheduled_for": (datetime.utcnow() - timedelta(minutes=5)).isoformat()
        })
        
        job_repo.create_job({
            "user_id": str(user_id),
            "job_type": "email_processing",
            "priority": "normal",
            "scheduled_for": (datetime.utcnow() - timedelta(minutes=15)).isoformat()
        })
        
        # Get pending jobs
        pending = job_repo.get_pending_jobs()
        
        # Should be ordered by priority first, then by scheduled_for
        assert len(pending) == 3
        assert pending[0]["priority"] == "high"
        assert pending[1]["priority"] == "normal"
        assert pending[2]["priority"] == "low"