# tests/unit/repositories/test_gmail_repository.py
"""
Test-first driver for GmailRepository implementation.
These tests define the Gmail connection and OAuth management interface.
"""
import pytest
from uuid import uuid4
from datetime import datetime, timedelta
from app.data.repositories.gmail_repository import GmailRepository
from app.data.database import ValidationError, NotFoundError

class TestGmailRepository:
    """Test-driven development for GmailRepository"""
    
    @pytest.fixture
    def gmail_repo(self):
        """Create GmailRepository instance - this doesn't exist yet!"""
        return GmailRepository()
    
    @pytest.fixture
    def sample_oauth_tokens(self):
        """Sample OAuth tokens for testing"""
        return {
            "access_token": "ya29.a0ARrdaM9VKjRqN3t_sample_access_token",
            "refresh_token": "1//04_sample_refresh_token",
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": "https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.modify"
        }
    
    def test_store_oauth_tokens_basic(self, gmail_repo, sample_oauth_tokens):
        """Test storing OAuth tokens with encryption"""
        user_id = uuid4()
        
        success = gmail_repo.store_oauth_tokens(user_id, sample_oauth_tokens)
        assert success == True
        
        # Verify tokens are stored and can be retrieved
        stored_tokens = gmail_repo.get_oauth_tokens(user_id)
        assert stored_tokens["access_token"] == sample_oauth_tokens["access_token"]
        assert stored_tokens["refresh_token"] == sample_oauth_tokens["refresh_token"]
        assert stored_tokens["expires_in"] == sample_oauth_tokens["expires_in"]
    
    def test_store_oauth_tokens_with_user_info(self, gmail_repo, sample_oauth_tokens):
        """Test storing OAuth tokens with user profile information"""
        user_id = uuid4()
        user_info = {
            "email": "user@example.com",
            "name": "John Doe",
            "picture": "https://example.com/profile.jpg"
        }
        
        success = gmail_repo.store_oauth_tokens(user_id, sample_oauth_tokens, user_info)
        assert success == True
        
        # Verify connection info includes user details
        connection_info = gmail_repo.get_connection_info(user_id)
        assert connection_info["email_address"] == "user@example.com"
        assert connection_info["profile_info"]["name"] == "John Doe"
        assert connection_info["connection_status"] == "connected"
    
    def test_store_oauth_tokens_validation(self, gmail_repo):
        """Test validation of OAuth token storage"""
        user_id = uuid4()
        
        # Missing access token
        with pytest.raises(ValidationError) as exc_info:
            gmail_repo.store_oauth_tokens(user_id, {
                "refresh_token": "refresh_token",
                "expires_in": 3600
            })
        
        assert "access_token is required" in str(exc_info.value)
        
        # Missing refresh token
        with pytest.raises(ValidationError) as exc_info:
            gmail_repo.store_oauth_tokens(user_id, {
                "access_token": "access_token",
                "expires_in": 3600
            })
        
        assert "refresh_token is required" in str(exc_info.value)
        
        # Invalid expires_in
        with pytest.raises(ValidationError) as exc_info:
            gmail_repo.store_oauth_tokens(user_id, {
                "access_token": "access_token",
                "refresh_token": "refresh_token",
                "expires_in": "invalid"
            })
        
        assert "expires_in must be integer" in str(exc_info.value)
    
    def test_get_oauth_tokens_success(self, gmail_repo, sample_oauth_tokens):
        """Test successful OAuth token retrieval"""
        user_id = uuid4()
        
        # Store tokens first
        gmail_repo.store_oauth_tokens(user_id, sample_oauth_tokens)
        
        # Retrieve tokens
        retrieved_tokens = gmail_repo.get_oauth_tokens(user_id)
        
        assert retrieved_tokens["access_token"] == sample_oauth_tokens["access_token"]
        assert retrieved_tokens["refresh_token"] == sample_oauth_tokens["refresh_token"]
        assert retrieved_tokens["expires_in"] == sample_oauth_tokens["expires_in"]
    
    def test_get_oauth_tokens_not_found(self, gmail_repo):
        """Test getting OAuth tokens when connection doesn't exist"""
        user_id = uuid4()
        
        result = gmail_repo.get_oauth_tokens(user_id)
        assert result is None
    
    def test_get_oauth_tokens_decryption(self, gmail_repo, sample_oauth_tokens):
        """Test that tokens are properly encrypted/decrypted"""
        user_id = uuid4()
        
        # Store tokens
        gmail_repo.store_oauth_tokens(user_id, sample_oauth_tokens)
        
        # Retrieve tokens should decrypt them
        retrieved_tokens = gmail_repo.get_oauth_tokens(user_id)
        
        # Tokens should be identical to original
        assert retrieved_tokens == sample_oauth_tokens
    
    def test_update_connection_status(self, gmail_repo, sample_oauth_tokens):
        """Test updating Gmail connection status"""
        user_id = uuid4()
        
        # Store tokens first
        gmail_repo.store_oauth_tokens(user_id, sample_oauth_tokens)
        
        # Update status to disconnected
        success = gmail_repo.update_connection_status(user_id, "disconnected")
        assert success == True
        
        # Verify status was updated
        connection_info = gmail_repo.get_connection_info(user_id)
        assert connection_info["connection_status"] == "disconnected"
        assert "updated_at" in connection_info
    
    def test_update_connection_status_with_error(self, gmail_repo, sample_oauth_tokens):
        """Test updating connection status with error information"""
        user_id = uuid4()
        
        # Store tokens first
        gmail_repo.store_oauth_tokens(user_id, sample_oauth_tokens)
        
        # Update status with error
        error_info = {
            "error_type": "invalid_grant",
            "error_description": "Token has been expired or revoked",
            "error_timestamp": datetime.now().isoformat(),
            "retry_count": 3
        }
        
        success = gmail_repo.update_connection_status(user_id, "error", error_info)
        assert success == True
        
        # Verify error info was stored
        connection_info = gmail_repo.get_connection_info(user_id)
        assert connection_info["connection_status"] == "error"
        assert connection_info["error_info"]["error_type"] == "invalid_grant"
        assert connection_info["error_info"]["retry_count"] == 3
    
    def test_update_connection_status_validation(self, gmail_repo):
        """Test validation of connection status updates"""
        user_id = uuid4()
        
        # Invalid status
        with pytest.raises(ValidationError) as exc_info:
            gmail_repo.update_connection_status(user_id, "invalid_status")
        
        assert "invalid connection status" in str(exc_info.value).lower()
    
    def test_get_connection_info_comprehensive(self, gmail_repo, sample_oauth_tokens):
        """Test getting comprehensive connection information"""
        user_id = uuid4()
        user_info = {
            "email": "user@example.com",
            "name": "John Doe"
        }
        
        # Store tokens with user info
        gmail_repo.store_oauth_tokens(user_id, sample_oauth_tokens, user_info)
        
        # Get connection info
        connection_info = gmail_repo.get_connection_info(user_id)
        
        assert connection_info["user_id"] == str(user_id)
        assert connection_info["email_address"] == "user@example.com"
        assert connection_info["connection_status"] == "connected"
        assert connection_info["profile_info"]["name"] == "John Doe"
        assert "scopes" in connection_info
        assert "created_at" in connection_info
        assert "updated_at" in connection_info
    
    def test_get_connection_info_not_found(self, gmail_repo):
        """Test getting connection info when connection doesn't exist"""
        user_id = uuid4()
        
        result = gmail_repo.get_connection_info(user_id)
        assert result is None
    
    def test_refresh_access_token_success(self, gmail_repo, sample_oauth_tokens):
        """Test successful access token refresh"""
        user_id = uuid4()
        
        # Store initial tokens
        gmail_repo.store_oauth_tokens(user_id, sample_oauth_tokens)
        
        # Refresh token
        new_tokens = gmail_repo.refresh_access_token(user_id)
        
        assert new_tokens is not None
        assert "access_token" in new_tokens
        assert "expires_in" in new_tokens
        assert new_tokens["access_token"] != sample_oauth_tokens["access_token"]  # Should be different
        
        # Verify stored tokens were updated
        stored_tokens = gmail_repo.get_oauth_tokens(user_id)
        assert stored_tokens["access_token"] == new_tokens["access_token"]
    
    def test_refresh_access_token_invalid_refresh_token(self, gmail_repo, sample_oauth_tokens):
        """Test access token refresh with invalid refresh token"""
        user_id = uuid4()
        
        # Store tokens with invalid refresh token
        invalid_tokens = sample_oauth_tokens.copy()
        invalid_tokens["refresh_token"] = "invalid_refresh_token"
        gmail_repo.store_oauth_tokens(user_id, invalid_tokens)
        
        # Refresh should fail
        with pytest.raises(ValidationError) as exc_info:
            gmail_repo.refresh_access_token(user_id)
        
        assert "invalid refresh token" in str(exc_info.value).lower()
        
        # Connection status should be updated to error
        connection_info = gmail_repo.get_connection_info(user_id)
        assert connection_info["connection_status"] == "error"
    
    def test_refresh_access_token_no_connection(self, gmail_repo):
        """Test refreshing token when no connection exists"""
        user_id = uuid4()
        
        with pytest.raises(NotFoundError) as exc_info:
            gmail_repo.refresh_access_token(user_id)
        
        assert "connection not found" in str(exc_info.value).lower()
    
    def test_update_sync_metadata(self, gmail_repo, sample_oauth_tokens):
        """Test updating Gmail sync metadata"""
        user_id = uuid4()
        
        # Store tokens first
        gmail_repo.store_oauth_tokens(user_id, sample_oauth_tokens)
        
        # Update sync metadata
        sync_metadata = {
            "history_id": "67890",
            "last_sync": datetime.now().isoformat(),
            "messages_synced": 25,
            "sync_duration": 2.5,
            "next_sync": (datetime.now() + timedelta(hours=1)).isoformat()
        }
        
        success = gmail_repo.update_sync_metadata(user_id, sync_metadata)
        assert success == True
        
        # Verify metadata was stored
        connection_info = gmail_repo.get_connection_info(user_id)
        assert connection_info["sync_metadata"]["history_id"] == "67890"
        assert connection_info["sync_metadata"]["messages_synced"] == 25
        assert connection_info["sync_metadata"]["sync_duration"] == 2.5
    
    def test_get_connections_by_status(self, gmail_repo, sample_oauth_tokens):
        """Test getting connections by status"""
        # Create multiple connections with different statuses
        user1 = uuid4()
        user2 = uuid4()
        user3 = uuid4()
        
        # Connected users
        gmail_repo.store_oauth_tokens(user1, sample_oauth_tokens)
        gmail_repo.store_oauth_tokens(user2, sample_oauth_tokens)
        
        # Disconnected user
        gmail_repo.store_oauth_tokens(user3, sample_oauth_tokens)
        gmail_repo.update_connection_status(user3, "disconnected")
        
        # Get connected users
        connected = gmail_repo.get_connections_by_status("connected")
        assert len(connected) == 2
        assert all(conn["connection_status"] == "connected" for conn in connected)
        
        # Get disconnected users
        disconnected = gmail_repo.get_connections_by_status("disconnected")
        assert len(disconnected) == 1
        assert disconnected[0]["connection_status"] == "disconnected"
    
    def test_get_connections_needing_refresh(self, gmail_repo, sample_oauth_tokens):
        """Test getting connections that need token refresh"""
        user_id = uuid4()
        
        # Store tokens that expire soon
        expiring_tokens = sample_oauth_tokens.copy()
        expiring_tokens["expires_in"] = 300  # 5 minutes
        gmail_repo.store_oauth_tokens(user_id, expiring_tokens)
        
        # Get connections needing refresh
        connections = gmail_repo.get_connections_needing_refresh()
        
        assert len(connections) == 1
        assert connections[0]["user_id"] == str(user_id)
        assert connections[0]["connection_status"] == "connected"
    
    def test_update_scopes(self, gmail_repo, sample_oauth_tokens):
        """Test updating Gmail API scopes"""
        user_id = uuid4()
        
        # Store tokens first
        gmail_repo.store_oauth_tokens(user_id, sample_oauth_tokens)
        
        # Update scopes
        new_scopes = [
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.modify",
            "https://www.googleapis.com/auth/gmail.send"
        ]
        
        success = gmail_repo.update_scopes(user_id, new_scopes)
        assert success == True
        
        # Verify scopes were updated
        connection_info = gmail_repo.get_connection_info(user_id)
        assert connection_info["scopes"] == new_scopes
    
    def test_update_scopes_validation(self, gmail_repo, sample_oauth_tokens):
        """Test validation of scope updates"""
        user_id = uuid4()
        
        # Store tokens first
        gmail_repo.store_oauth_tokens(user_id, sample_oauth_tokens)
        
        # Invalid scopes (empty list)
        with pytest.raises(ValidationError) as exc_info:
            gmail_repo.update_scopes(user_id, [])
        
        assert "scopes cannot be empty" in str(exc_info.value).lower()
        
        # Invalid scope format
        with pytest.raises(ValidationError) as exc_info:
            gmail_repo.update_scopes(user_id, ["invalid_scope"])
        
        assert "invalid scope format" in str(exc_info.value).lower()
    
    def test_delete_connection(self, gmail_repo, sample_oauth_tokens):
        """Test deleting Gmail connection"""
        user_id = uuid4()
        
        # Store tokens first
        gmail_repo.store_oauth_tokens(user_id, sample_oauth_tokens)
        
        # Verify connection exists
        connection_info = gmail_repo.get_connection_info(user_id)
        assert connection_info is not None
        
        # Delete connection
        success = gmail_repo.delete_connection(user_id)
        assert success == True
        
        # Verify connection is deleted
        connection_info = gmail_repo.get_connection_info(user_id)
        assert connection_info is None
        
        # Verify tokens are also deleted
        tokens = gmail_repo.get_oauth_tokens(user_id)
        assert tokens is None
    
    def test_delete_nonexistent_connection(self, gmail_repo):
        """Test deleting non-existent connection"""
        user_id = uuid4()
        
        success = gmail_repo.delete_connection(user_id)
        assert success == False
    
    def test_get_connection_stats(self, gmail_repo, sample_oauth_tokens):
        """Test getting connection statistics"""
        user_id = uuid4()
        
        # Store tokens first
        gmail_repo.store_oauth_tokens(user_id, sample_oauth_tokens)
        
        # Get stats
        stats = gmail_repo.get_connection_stats(user_id)
        
        assert stats["user_id"] == str(user_id)
        assert "total_emails_processed" in stats
        assert "successful_syncs" in stats
        assert "failed_syncs" in stats
        assert "average_sync_time" in stats
        assert "last_successful_sync" in stats
        assert "connection_uptime" in stats
        assert "scopes_count" in stats
    
    def test_record_sync_attempt(self, gmail_repo, sample_oauth_tokens):
        """Test recording a sync attempt"""
        user_id = uuid4()
        
        # Store tokens first
        gmail_repo.store_oauth_tokens(user_id, sample_oauth_tokens)
        
        # Record sync attempt
        sync_data = {
            "user_id": str(user_id),
            "started_at": datetime.now().isoformat(),
            "status": "in_progress",
            "sync_type": "incremental",
            "metadata": {
                "history_id": "12345",
                "query": "is:unread"
            }
        }
        
        sync_record = gmail_repo.record_sync_attempt(sync_data)
        
        assert sync_record["user_id"] == str(user_id)
        assert sync_record["status"] == "in_progress"
        assert sync_record["sync_type"] == "incremental"
        assert sync_record["metadata"]["history_id"] == "12345"
        assert "sync_id" in sync_record
        assert "started_at" in sync_record
    
    def test_update_sync_completion(self, gmail_repo, sample_oauth_tokens):
        """Test updating sync completion status"""
        user_id = uuid4()
        
        # Store tokens first
        gmail_repo.store_oauth_tokens(user_id, sample_oauth_tokens)
        
        # Record sync attempt
        sync_data = {
            "user_id": str(user_id),
            "started_at": datetime.now().isoformat(),
            "status": "in_progress",
            "sync_type": "full"
        }
        
        sync_record = gmail_repo.record_sync_attempt(sync_data)
        
        # Update completion
        completion_data = {
            "completed_at": datetime.now().isoformat(),
            "status": "completed",
            "messages_processed": 25,
            "errors": [],
            "duration": 150.5
        }
        
        success = gmail_repo.update_sync_completion(sync_record["sync_id"], completion_data)
        assert success == True
        
        # Verify completion was recorded
        sync_history = gmail_repo.get_sync_history(user_id, limit=1)
        assert len(sync_history) == 1
        assert sync_history[0]["status"] == "completed"
        assert sync_history[0]["messages_processed"] == 25
        assert sync_history[0]["duration"] == 150.5
    
    def test_get_sync_history(self, gmail_repo, sample_oauth_tokens):
        """Test getting Gmail sync history"""
        user_id = uuid4()
        
        # Store tokens first
        gmail_repo.store_oauth_tokens(user_id, sample_oauth_tokens)
        
        # Record multiple sync attempts
        sync1 = gmail_repo.record_sync_attempt({
            "user_id": str(user_id),
            "started_at": datetime.now().isoformat(),
            "status": "in_progress",
            "sync_type": "full"
        })
        
        sync2 = gmail_repo.record_sync_attempt({
            "user_id": str(user_id),
            "started_at": datetime.now().isoformat(),
            "status": "in_progress",
            "sync_type": "incremental"
        })
        
        # Complete the syncs
        gmail_repo.update_sync_completion(sync1["sync_id"], {
            "completed_at": datetime.now().isoformat(),
            "status": "completed",
            "messages_processed": 50
        })
        
        gmail_repo.update_sync_completion(sync2["sync_id"], {
            "completed_at": datetime.now().isoformat(),
            "status": "completed",
            "messages_processed": 10
        })
        
        # Get sync history
        history = gmail_repo.get_sync_history(user_id, limit=10)
        
        assert len(history) == 2
        # Should be ordered by started_at descending (newest first)
        assert history[0]["sync_type"] == "incremental"
        assert history[1]["sync_type"] == "full"
        assert all(sync["status"] == "completed" for sync in history)
    
    def test_get_sync_history_with_status_filter(self, gmail_repo, sample_oauth_tokens):
        """Test getting sync history with status filter"""
        user_id = uuid4()
        
        # Store tokens first
        gmail_repo.store_oauth_tokens(user_id, sample_oauth_tokens)
        
        # Record sync attempts with different statuses
        sync1 = gmail_repo.record_sync_attempt({
            "user_id": str(user_id),
            "started_at": datetime.now().isoformat(),
            "status": "in_progress",
            "sync_type": "full"
        })
        
        sync2 = gmail_repo.record_sync_attempt({
            "user_id": str(user_id),
            "started_at": datetime.now().isoformat(),
            "status": "in_progress",
            "sync_type": "incremental"
        })
        
        # Complete only one sync
        gmail_repo.update_sync_completion(sync1["sync_id"], {
            "completed_at": datetime.now().isoformat(),
            "status": "completed",
            "messages_processed": 50
        })
        
        # Leave sync2 as in_progress
        
        # Get only completed syncs
        completed = gmail_repo.get_sync_history(user_id, status="completed")
        assert len(completed) == 1
        assert completed[0]["status"] == "completed"
        
        # Get only in_progress syncs
        in_progress = gmail_repo.get_sync_history(user_id, status="in_progress")
        assert len(in_progress) == 1
        assert in_progress[0]["status"] == "in_progress"
    
    def test_batch_update_connection_status(self, gmail_repo, sample_oauth_tokens):
        """Test batch updating connection status for multiple users"""
        user1 = uuid4()
        user2 = uuid4()
        user3 = uuid4()
        
        # Store tokens for all users
        gmail_repo.store_oauth_tokens(user1, sample_oauth_tokens)
        gmail_repo.store_oauth_tokens(user2, sample_oauth_tokens)
        gmail_repo.store_oauth_tokens(user3, sample_oauth_tokens)
        
        # Batch update statuses
        status_updates = [
            {"user_id": str(user1), "status": "connected"},
            {"user_id": str(user2), "status": "error"},
            {"user_id": str(user3), "status": "disconnected"}
        ]
        
        updated_count = gmail_repo.batch_update_connection_status(status_updates)
        assert updated_count == 3
        
        # Verify each status was updated
        assert gmail_repo.get_connection_info(user1)["connection_status"] == "connected"
        assert gmail_repo.get_connection_info(user2)["connection_status"] == "error"
        assert gmail_repo.get_connection_info(user3)["connection_status"] == "disconnected"
    
    def test_check_connection_health(self, gmail_repo, sample_oauth_tokens):
        """Test connection health check"""
        user_id = uuid4()
        
        # Store tokens first
        gmail_repo.store_oauth_tokens(user_id, sample_oauth_tokens)
        
        # Check health
        health = gmail_repo.check_connection_health(user_id)
        
        assert health["user_id"] == str(user_id)
        assert health["connection_status"] == "connected"
        assert "token_valid" in health
        assert "token_expires_in" in health
        assert "last_successful_api_call" in health
        assert "api_quota_remaining" in health
        assert "scopes_valid" in health
        assert "health_score" in health
        assert 0 <= health["health_score"] <= 1
    
    def test_check_connection_health_no_connection(self, gmail_repo):
        """Test health check when no connection exists"""
        user_id = uuid4()
        
        health = gmail_repo.check_connection_health(user_id)
        assert health is None
    
    def test_rotate_encryption_key(self, gmail_repo, sample_oauth_tokens):
        """Test rotating encryption key for stored tokens"""
        user_id = uuid4()
        
        # Store tokens first
        gmail_repo.store_oauth_tokens(user_id, sample_oauth_tokens)
        
        # Rotate encryption key
        success = gmail_repo.rotate_encryption_key(user_id)
        assert success == True
        
        # Verify tokens are still retrievable (re-encrypted with new key)
        retrieved_tokens = gmail_repo.get_oauth_tokens(user_id)
        assert retrieved_tokens["access_token"] == sample_oauth_tokens["access_token"]
        assert retrieved_tokens["refresh_token"] == sample_oauth_tokens["refresh_token"]
    
    def test_rotate_encryption_key_no_connection(self, gmail_repo):
        """Test rotating encryption key when no connection exists"""
        user_id = uuid4()
        
        success = gmail_repo.rotate_encryption_key(user_id)
        assert success == False
    
    @pytest.mark.parametrize("status", ["connected", "disconnected", "error", "pending"])
    def test_valid_connection_statuses(self, gmail_repo, sample_oauth_tokens, status):
        """Test all valid connection statuses"""
        user_id = uuid4()
        
        # Store tokens first
        gmail_repo.store_oauth_tokens(user_id, sample_oauth_tokens)
        
        # Update to test status
        success = gmail_repo.update_connection_status(user_id, status)
        assert success == True
        
        # Verify status
        connection_info = gmail_repo.get_connection_info(user_id)
        assert connection_info["connection_status"] == status
    
    @pytest.mark.parametrize("invalid_status", ["invalid", "", "unknown", "active"])
    def test_invalid_connection_statuses(self, gmail_repo, invalid_status):
        """Test invalid connection statuses"""
        user_id = uuid4()
        
        with pytest.raises(ValidationError):
            gmail_repo.update_connection_status(user_id, invalid_status)
    
    def test_connection_expiry_tracking(self, gmail_repo, sample_oauth_tokens):
        """Test tracking token expiry"""
        user_id = uuid4()
        
        # Store tokens with short expiry
        short_expiry_tokens = sample_oauth_tokens.copy()
        short_expiry_tokens["expires_in"] = 60  # 1 minute
        
        gmail_repo.store_oauth_tokens(user_id, short_expiry_tokens)
        
        # Check connection info includes expiry
        connection_info = gmail_repo.get_connection_info(user_id)
        assert "token_expires_at" in connection_info
        
        # Check that connection shows up in needing refresh
        connections = gmail_repo.get_connections_needing_refresh(threshold_minutes=5)
        assert len(connections) == 1
        assert connections[0]["user_id"] == str(user_id)
    
    def test_connection_metadata_storage(self, gmail_repo, sample_oauth_tokens):
        """Test storing and retrieving connection metadata"""
        user_id = uuid4()
        
        # Store tokens first
        gmail_repo.store_oauth_tokens(user_id, sample_oauth_tokens)
        
        # Update with comprehensive metadata
        metadata = {
            "gmail_profile": {
                "profile_id": "profile_123",
                "history_id": "12345",
                "labels": ["INBOX", "UNREAD", "IMPORTANT"],
                "thread_count": 1500,
                "message_count": 2000
            },
            "sync_preferences": {
                "query_filter": "is:unread -label:spam",
                "max_results": 100,
                "include_attachments": False
            },
            "performance_metrics": {
                "avg_sync_time": 3.2,
                "success_rate": 0.95,
                "last_optimization": "2024-01-15T10:30:00Z"
            }
        }
        
        success = gmail_repo.update_connection_metadata(user_id, metadata)
        assert success == True
        
        # Verify metadata is stored
        connection_info = gmail_repo.get_connection_info(user_id)
        assert connection_info["metadata"]["gmail_profile"]["profile_id"] == "profile_123"
        assert connection_info["metadata"]["sync_preferences"]["max_results"] == 100
        assert connection_info["metadata"]["performance_metrics"]["success_rate"] == 0.95
    
    def test_connection_activity_logging(self, gmail_repo, sample_oauth_tokens):
        """Test logging connection activity"""
        user_id = uuid4()
        
        # Store tokens first
        gmail_repo.store_oauth_tokens(user_id, sample_oauth_tokens)
        
        # Log various activities
        activities = [
            {
                "activity_type": "token_refresh",
                "timestamp": datetime.now().isoformat(),
                "success": True,
                "details": {"new_expires_in": 3600}
            },
            {
                "activity_type": "api_call",
                "timestamp": datetime.now().isoformat(),
                "success": True,
                "details": {"endpoint": "messages/list", "response_time": 0.5}
            },
            {
                "activity_type": "sync_operation",
                "timestamp": datetime.now().isoformat(),
                "success": False,
                "details": {"error": "quota_exceeded", "retry_after": 60}
            }
        ]
        
        for activity in activities:
            success = gmail_repo.log_connection_activity(user_id, activity)
            assert success == True
        
        # Get activity log
        activity_log = gmail_repo.get_connection_activity_log(user_id, limit=10)
        assert len(activity_log) == 3
        
        # Verify activities are properly logged
        activity_types = [activity["activity_type"] for activity in activity_log]
        assert "token_refresh" in activity_types
        assert "api_call" in activity_types
        assert "sync_operation" in activity_types
    
    def test_connection_cleanup_on_user_deletion(self, gmail_repo, sample_oauth_tokens):
        """Test that connection is cleaned up when user is deleted"""
        user_id = uuid4()
        
        # Store tokens first
        gmail_repo.store_oauth_tokens(user_id, sample_oauth_tokens)
        
        # Verify connection exists
        connection_info = gmail_repo.get_connection_info(user_id)
        assert connection_info is not None
        
        # Simulate user deletion cleanup
        success = gmail_repo.cleanup_user_connections(user_id)
        assert success == True
        
        # Verify all user connection data is cleaned up
        assert gmail_repo.get_connection_info(user_id) is None
        assert gmail_repo.get_oauth_tokens(user_id) is None
        assert gmail_repo.get_sync_history(user_id) == []
        assert gmail_repo.get_connection_activity_log(user_id) == []
    
    def test_connection_statistics_aggregation(self, gmail_repo, sample_oauth_tokens):
        """Test aggregating connection statistics"""
        user_id = uuid4()
        
        # Store tokens first
        gmail_repo.store_oauth_tokens(user_id, sample_oauth_tokens)
        
        # Record multiple sync operations
        for i in range(5):
            sync_record = gmail_repo.record_sync_attempt({
                "user_id": str(user_id),
                "started_at": datetime.now().isoformat(),
                "status": "in_progress",
                "sync_type": "incremental"
            })
            
            gmail_repo.update_sync_completion(sync_record["sync_id"], {
                "completed_at": datetime.now().isoformat(),
                "status": "completed",
                "messages_processed": 10 + i,
                "duration": 2.0 + (i * 0.5)
            })
        
        # Get aggregated stats
        stats = gmail_repo.get_connection_stats(user_id)
        
        assert stats["total_emails_processed"] == 60  # 10+11+12+13+14
        assert stats["successful_syncs"] == 5
        assert stats["failed_syncs"] == 0
        assert stats["average_sync_time"] > 0
        assert stats["connection_uptime"] > 0
    
    def test_concurrent_token_operations(self, gmail_repo, sample_oauth_tokens):
        """Test concurrent token operations don't cause race conditions"""
        user_id = uuid4()
        
        # Store initial tokens
        gmail_repo.store_oauth_tokens(user_id, sample_oauth_tokens)
        
        # Simulate concurrent refresh attempts
        # In real implementation, this would test database-level atomicity
        success1 = gmail_repo.refresh_access_token(user_id)
        success2 = gmail_repo.refresh_access_token(user_id)
        
        # Both should succeed or one should fail gracefully
        assert success1 is not None or success2 is not None
        
        # Final state should be consistent
        final_tokens = gmail_repo.get_oauth_tokens(user_id)
        assert final_tokens is not None
        assert "access_token" in final_tokens
        assert "refresh_token" in final_tokens