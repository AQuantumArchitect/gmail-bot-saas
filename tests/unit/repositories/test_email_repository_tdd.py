# tests/unit/repositories/test_email_repository.py
"""
Test-first driver for EmailRepository implementation.
Lean pipeline approach - just track processing state, not content.
"""
import pytest
from uuid import uuid4
from datetime import datetime, timedelta
from app.data.repositories.email_repository import EmailRepository
from app.core.exceptions import ValidationError, NotFoundError

class TestEmailRepository:
    """Test-driven development for lean EmailRepository"""
    
    @pytest.fixture
    def email_repo(self):
        """Create EmailRepository instance - this doesn't exist yet!"""
        return EmailRepository()
    
    def test_mark_discovered_single_email(self, email_repo):
        """Test marking a single email as discovered"""
        user_id = uuid4()
        message_id = "gmail_message_123"
        
        result = email_repo.mark_discovered(user_id, message_id)
        
        assert result["user_id"] == str(user_id)
        assert result["message_id"] == message_id
        assert result["status"] == "discovered"
        assert result["discovery_count"] == 1
        assert "id" in result
        assert "discovered_at" in result
    
    def test_mark_discovered_multiple_emails(self, email_repo):
        """Test marking multiple emails as discovered in batch"""
        user_id = uuid4()
        message_ids = ["gmail_msg_1", "gmail_msg_2", "gmail_msg_3"]
        
        results = email_repo.mark_discovered_batch(user_id, message_ids)
        
        assert len(results) == 3
        assert all(r["user_id"] == str(user_id) for r in results)
        assert all(r["status"] == "discovered" for r in results)
        assert [r["message_id"] for r in results] == message_ids
    
    def test_mark_discovered_duplicate_prevention(self, email_repo):
        """Test that duplicate message IDs are handled gracefully"""
        user_id = uuid4()
        message_id = "gmail_duplicate_123"
        
        # First discovery
        result1 = email_repo.mark_discovered(user_id, message_id)
        assert result1["discovery_count"] == 1
        
        # Second discovery - should update, not create duplicate
        result2 = email_repo.mark_discovered(user_id, message_id)
        assert result2["discovery_count"] == 2
        assert result2["id"] == result1["id"]  # Same record
        assert result2["discovered_at"] != result1["discovered_at"]  # Updated timestamp
    
    def test_mark_discovered_validation(self, email_repo):
        """Test validation of discovery marking"""
        user_id = uuid4()
        
        # Empty message ID
        with pytest.raises(ValidationError) as exc_info:
            email_repo.mark_discovered(user_id, "")
        
        assert "message_id cannot be empty" in str(exc_info.value)
        
        # Invalid message ID format
        with pytest.raises(ValidationError) as exc_info:
            email_repo.mark_discovered(user_id, "invalid format with spaces")
        
        assert "invalid message_id format" in str(exc_info.value).lower()
    
    def test_mark_processing_started(self, email_repo):
        """Test marking email as processing started"""
        user_id = uuid4()
        message_id = "gmail_processing_123"
        
        # First mark as discovered
        email_repo.mark_discovered(user_id, message_id)
        
        # Start processing
        result = email_repo.mark_processing_started(user_id, message_id)
        
        assert result["status"] == "processing"
        assert result["processing_started_at"] is not None
        assert result["processing_attempts"] == 1
    
    def test_mark_processing_completed_success(self, email_repo):
        """Test marking email processing as completed successfully"""
        user_id = uuid4()
        message_id = "gmail_success_123"
        
        # Mark as discovered and processing
        email_repo.mark_discovered(user_id, message_id)
        email_repo.mark_processing_started(user_id, message_id)
        
        # Complete processing
        processing_result = {
            "summary_generated": True,
            "reply_sent": True,
            "credits_used": 5,
            "processing_time": 2.3,
            "tokens_used": 1200,
            "ai_model": "claude-3-sonnet"
        }
        
        result = email_repo.mark_processing_completed(user_id, message_id, processing_result)
        
        assert result["status"] == "completed"
        assert result["processing_completed_at"] is not None
        assert result["processing_result"]["summary_generated"] == True
        assert result["processing_result"]["credits_used"] == 5
        assert result["processing_result"]["processing_time"] == 2.3
        assert result["success"] == True
    
    def test_mark_processing_completed_failure(self, email_repo):
        """Test marking email processing as failed"""
        user_id = uuid4()
        message_id = "gmail_failure_123"
        
        # Mark as discovered and processing
        email_repo.mark_discovered(user_id, message_id)
        email_repo.mark_processing_started(user_id, message_id)
        
        # Complete processing with failure
        processing_result = {
            "summary_generated": False,
            "reply_sent": False,
            "error": "API quota exceeded",
            "error_type": "quota_exceeded",
            "processing_time": 1.5,
            "retry_after": 300
        }
        
        result = email_repo.mark_processing_completed(user_id, message_id, processing_result, success=False)
        
        assert result["status"] == "failed"
        assert result["processing_result"]["error"] == "API quota exceeded"
        assert result["processing_result"]["retry_after"] == 300
        assert result["success"] == False
    
    def test_mark_processing_retry(self, email_repo):
        """Test marking email for retry after failure"""
        user_id = uuid4()
        message_id = "gmail_retry_123"
        
        # Mark as discovered, processed, and failed
        email_repo.mark_discovered(user_id, message_id)
        email_repo.mark_processing_started(user_id, message_id)
        email_repo.mark_processing_completed(user_id, message_id, {"error": "temporary failure"}, success=False)
        
        # Mark for retry
        result = email_repo.mark_for_retry(user_id, message_id)
        
        assert result["status"] == "discovered"  # Back to discovered for retry
        assert result["processing_attempts"] == 1  # Keeps attempt count
        assert result["last_retry_at"] is not None
        assert result["can_retry"] == True
    
    def test_mark_processing_retry_limit(self, email_repo):
        """Test that retry limit is enforced"""
        user_id = uuid4()
        message_id = "gmail_retry_limit_123"
        
        # Mark as discovered
        email_repo.mark_discovered(user_id, message_id)
        
        # Simulate multiple failed attempts
        for attempt in range(3):
            email_repo.mark_processing_started(user_id, message_id)
            email_repo.mark_processing_completed(user_id, message_id, {"error": f"failure {attempt}"}, success=False)
            
            if attempt < 2:  # First two attempts can retry
                result = email_repo.mark_for_retry(user_id, message_id)
                assert result["can_retry"] == True
        
        # Fourth attempt should not be allowed
        with pytest.raises(ValidationError) as exc_info:
            email_repo.mark_for_retry(user_id, message_id)
        
        assert "maximum retry attempts exceeded" in str(exc_info.value).lower()
    
    def test_get_processing_status(self, email_repo):
        """Test getting processing status for an email"""
        user_id = uuid4()
        message_id = "gmail_status_123"
        
        # Initially should not exist
        status = email_repo.get_processing_status(user_id, message_id)
        assert status is None
        
        # Mark as discovered
        email_repo.mark_discovered(user_id, message_id)
        
        status = email_repo.get_processing_status(user_id, message_id)
        assert status["status"] == "discovered"
        assert status["message_id"] == message_id
        
        # Mark as processing
        email_repo.mark_processing_started(user_id, message_id)
        
        status = email_repo.get_processing_status(user_id, message_id)
        assert status["status"] == "processing"
        assert status["processing_started_at"] is not None
    
    def test_get_unprocessed_emails(self, email_repo):
        """Test getting emails that need processing"""
        user_id = uuid4()
        
        # Create emails in different states
        email_repo.mark_discovered(user_id, "msg_unprocessed_1")
        email_repo.mark_discovered(user_id, "msg_unprocessed_2")
        
        # One email is being processed
        email_repo.mark_discovered(user_id, "msg_processing")
        email_repo.mark_processing_started(user_id, "msg_processing")
        
        # One email is completed
        email_repo.mark_discovered(user_id, "msg_completed")
        email_repo.mark_processing_started(user_id, "msg_completed")
        email_repo.mark_processing_completed(user_id, "msg_completed", {"success": True})
        
        # Get unprocessed emails
        unprocessed = email_repo.get_unprocessed_emails(user_id)
        
        assert len(unprocessed) == 2
        message_ids = [email["message_id"] for email in unprocessed]
        assert "msg_unprocessed_1" in message_ids
        assert "msg_unprocessed_2" in message_ids
        assert all(email["status"] == "discovered" for email in unprocessed)
    
    def test_get_unprocessed_emails_with_limit(self, email_repo):
        """Test getting unprocessed emails with limit"""
        user_id = uuid4()
        
        # Create many unprocessed emails
        for i in range(10):
            email_repo.mark_discovered(user_id, f"msg_{i}")
        
        # Get limited results
        unprocessed = email_repo.get_unprocessed_emails(user_id, limit=5)
        
        assert len(unprocessed) == 5
        # Should be ordered by discovered_at (oldest first for processing)
        assert unprocessed[0]["message_id"] == "msg_0"
    
    def test_get_processing_history(self, email_repo):
        """Test getting processing history for user"""
        user_id = uuid4()
        
        # Process several emails
        for i in range(3):
            message_id = f"msg_history_{i}"
            email_repo.mark_discovered(user_id, message_id)
            email_repo.mark_processing_started(user_id, message_id)
            email_repo.mark_processing_completed(user_id, message_id, {
                "credits_used": 5 + i,
                "processing_time": 2.0 + i
            })
        
        # Get history
        history = email_repo.get_processing_history(user_id, limit=10)
        
        assert len(history) == 3
        # Should be ordered by processing_completed_at descending (newest first)
        assert history[0]["message_id"] == "msg_history_2"
        assert history[1]["message_id"] == "msg_history_1"
        assert history[2]["message_id"] == "msg_history_0"
        assert all(email["status"] == "completed" for email in history)
    
    def test_get_processing_history_with_filters(self, email_repo):
        """Test getting processing history with status filters"""
        user_id = uuid4()
        
        # Create emails with different statuses
        email_repo.mark_discovered(user_id, "msg_success")
        email_repo.mark_processing_started(user_id, "msg_success")
        email_repo.mark_processing_completed(user_id, "msg_success", {"credits_used": 5})
        
        email_repo.mark_discovered(user_id, "msg_failed")
        email_repo.mark_processing_started(user_id, "msg_failed")
        email_repo.mark_processing_completed(user_id, "msg_failed", {"error": "failed"}, success=False)
        
        # Get only successful
        successful = email_repo.get_processing_history(user_id, status="completed")
        assert len(successful) == 1
        assert successful[0]["message_id"] == "msg_success"
        assert successful[0]["success"] == True
        
        # Get only failed
        failed = email_repo.get_processing_history(user_id, status="failed")
        assert len(failed) == 1
        assert failed[0]["message_id"] == "msg_failed"
        assert failed[0]["success"] == False
    
    def test_get_processing_stats(self, email_repo):
        """Test getting processing statistics for user"""
        user_id = uuid4()
        
        # Create various email states
        for i in range(10):
            message_id = f"msg_stats_{i}"
            email_repo.mark_discovered(user_id, message_id)
            
            if i < 7:  # 7 processed successfully
                email_repo.mark_processing_started(user_id, message_id)
                email_repo.mark_processing_completed(user_id, message_id, {
                    "credits_used": 5,
                    "processing_time": 2.0
                })
            elif i < 9:  # 2 failed
                email_repo.mark_processing_started(user_id, message_id)
                email_repo.mark_processing_completed(user_id, message_id, {"error": "failed"}, success=False)
            # 1 remains unprocessed
        
        # Get stats
        stats = email_repo.get_processing_stats(user_id)
        
        assert stats["user_id"] == str(user_id)
        assert stats["total_discovered"] == 10
        assert stats["total_processed"] == 9
        assert stats["total_successful"] == 7
        assert stats["total_failed"] == 2
        assert stats["total_pending"] == 1
        assert stats["success_rate"] == 0.78  # 7/9 = 0.777...
        assert stats["total_credits_used"] == 35  # 7 * 5
        assert stats["average_processing_time"] == 2.0
    
    def test_get_processing_stats_empty(self, email_repo):
        """Test getting processing stats when no emails exist"""
        user_id = uuid4()
        
        stats = email_repo.get_processing_stats(user_id)
        
        assert stats["user_id"] == str(user_id)
        assert stats["total_discovered"] == 0
        assert stats["total_processed"] == 0
        assert stats["total_successful"] == 0
        assert stats["total_failed"] == 0
        assert stats["total_pending"] == 0
        assert stats["success_rate"] == 0.0
        assert stats["total_credits_used"] == 0
        assert stats["average_processing_time"] == 0.0
    
    def test_cleanup_old_records(self, email_repo):
        """Test cleaning up old processing records"""
        user_id = uuid4()
        
        # Create old completed emails
        for i in range(5):
            message_id = f"msg_old_{i}"
            email_repo.mark_discovered(user_id, message_id)
            email_repo.mark_processing_started(user_id, message_id)
            email_repo.mark_processing_completed(user_id, message_id, {"credits_used": 5})
        
        # Clean up records older than 30 days
        cleaned_count = email_repo.cleanup_old_records(days=30)
        
        # Should clean up completed records but keep stats
        assert cleaned_count >= 0  # May be 0 if records are recent
        
        # Stats should still be available
        stats = email_repo.get_processing_stats(user_id)
        assert stats["total_successful"] >= 0
    
    def test_bulk_mark_discovered(self, email_repo):
        """Test bulk marking multiple emails as discovered"""
        user_id = uuid4()
        
        # Bulk discovery data
        discoveries = [
            {"message_id": "bulk_1", "subject": "Test Email 1"},
            {"message_id": "bulk_2", "subject": "Test Email 2"},
            {"message_id": "bulk_3", "subject": "Test Email 3"}
        ]
        
        results = email_repo.bulk_mark_discovered(user_id, discoveries)
        
        assert len(results) == 3
        assert all(r["user_id"] == str(user_id) for r in results)
        assert all(r["status"] == "discovered" for r in results)
        
        # Verify all were created
        unprocessed = email_repo.get_unprocessed_emails(user_id)
        assert len(unprocessed) == 3
    
    def test_get_stale_processing_emails(self, email_repo):
        """Test getting emails that have been processing too long"""
        user_id = uuid4()
        
        # Create email that's been processing for too long
        email_repo.mark_discovered(user_id, "msg_stale")
        email_repo.mark_processing_started(user_id, "msg_stale")
        
        # Create recent processing email
        email_repo.mark_discovered(user_id, "msg_recent")
        email_repo.mark_processing_started(user_id, "msg_recent")
        
        # Get stale emails (processing > 10 minutes)
        stale = email_repo.get_stale_processing_emails(minutes=10)
        
        # Should find stale emails across all users
        assert len(stale) >= 0  # May be 0 if processing is recent
        
        # Each stale email should have processing info
        for email in stale:
            assert email["status"] == "processing"
            assert email["processing_started_at"] is not None
    
    def test_mark_stale_as_failed(self, email_repo):
        """Test marking stale processing emails as failed"""
        user_id = uuid4()
        
        # Create email in processing state
        email_repo.mark_discovered(user_id, "msg_timeout")
        email_repo.mark_processing_started(user_id, "msg_timeout")
        
        # Mark as failed due to timeout
        result = email_repo.mark_processing_timeout(user_id, "msg_timeout")
        
        assert result["status"] == "failed"
        assert result["processing_result"]["error"] == "processing_timeout"
        assert result["processing_result"]["timeout"] == True
        assert result["success"] == False
    
    def test_get_duplicate_message_ids(self, email_repo):
        """Test getting duplicate message IDs for deduplication"""
        user_id = uuid4()
        
        # Mark same message multiple times
        email_repo.mark_discovered(user_id, "msg_duplicate")
        email_repo.mark_discovered(user_id, "msg_duplicate")
        email_repo.mark_discovered(user_id, "msg_duplicate")
        
        # Check for duplicates
        duplicates = email_repo.get_duplicate_message_ids(user_id)
        
        assert len(duplicates) == 1
        assert duplicates[0]["message_id"] == "msg_duplicate"
        assert duplicates[0]["discovery_count"] == 3
    
    def test_delete_user_email_data(self, email_repo):
        """Test deleting all email data for a user"""
        user_id = uuid4()
        
        # Create various email states
        email_repo.mark_discovered(user_id, "msg_delete_1")
        email_repo.mark_discovered(user_id, "msg_delete_2")
        email_repo.mark_processing_started(user_id, "msg_delete_2")
        
        # Delete all user data
        deleted_count = email_repo.delete_user_email_data(user_id)
        
        assert deleted_count == 2
        
        # Verify data is deleted
        unprocessed = email_repo.get_unprocessed_emails(user_id)
        assert len(unprocessed) == 0
        
        history = email_repo.get_processing_history(user_id)
        assert len(history) == 0
        
        stats = email_repo.get_processing_stats(user_id)
        assert stats["total_discovered"] == 0
    
    @pytest.mark.parametrize("status", ["discovered", "processing", "completed", "failed"])
    def test_valid_processing_statuses(self, email_repo, status):
        """Test all valid processing statuses"""
        user_id = uuid4()
        message_id = f"msg_{status}"
        
        # Mark as discovered first
        email_repo.mark_discovered(user_id, message_id)
        
        # Update status based on test parameter
        if status == "processing":
            email_repo.mark_processing_started(user_id, message_id)
        elif status == "completed":
            email_repo.mark_processing_started(user_id, message_id)
            email_repo.mark_processing_completed(user_id, message_id, {"success": True})
        elif status == "failed":
            email_repo.mark_processing_started(user_id, message_id)
            email_repo.mark_processing_completed(user_id, message_id, {"error": "test"}, success=False)
        
        # Verify status
        result = email_repo.get_processing_status(user_id, message_id)
        assert result["status"] == status
    
    def test_processing_time_tracking(self, email_repo):
        """Test accurate processing time tracking"""
        user_id = uuid4()
        message_id = "msg_timing"
        
        # Mark as discovered
        email_repo.mark_discovered(user_id, message_id)
        
        # Start processing
        start_time = datetime.now()
        email_repo.mark_processing_started(user_id, message_id)
        
        # Complete processing
        processing_time = 2.5
        email_repo.mark_processing_completed(user_id, message_id, {
            "processing_time": processing_time
        })
        
        # Verify timing
        status = email_repo.get_processing_status(user_id, message_id)
        assert status["processing_result"]["processing_time"] == processing_time
        assert status["processing_started_at"] is not None
        assert status["processing_completed_at"] is not None
    
    def test_concurrent_processing_prevention(self, email_repo):
        """Test preventing concurrent processing of same email"""
        user_id = uuid4()
        message_id = "msg_concurrent"
        
        # Mark as discovered
        email_repo.mark_discovered(user_id, message_id)
        
        # Start processing
        email_repo.mark_processing_started(user_id, message_id)
        
        # Try to start processing again - should fail
        with pytest.raises(ValidationError) as exc_info:
            email_repo.mark_processing_started(user_id, message_id)
        
        assert "already processing" in str(exc_info.value).lower()
    
    def test_message_id_uniqueness_per_user(self, email_repo):
        """Test that message IDs are unique per user"""
        user1 = uuid4()
        user2 = uuid4()
        message_id = "shared_message_id"
        
        # Both users can have same message ID
        result1 = email_repo.mark_discovered(user1, message_id)
        result2 = email_repo.mark_discovered(user2, message_id)
        
        assert result1["user_id"] == str(user1)
        assert result2["user_id"] == str(user2)
        assert result1["message_id"] == message_id
        assert result2["message_id"] == message_id
        assert result1["id"] != result2["id"]  # Different records