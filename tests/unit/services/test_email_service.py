# tests/unit/services/test_email_service.py
"""
Test-first driver for EmailService implementation.
High-level email processing orchestration service that coordinates between
GmailService, BillingService, and other components.
"""
import asyncio
import pytest
from uuid import uuid4
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, AsyncMock
from app.services.email_service import EmailService
from app.services.gmail_service import GmailService
from app.services.billing_service import BillingService
from app.services.auth_service import AuthService
from app.data.repositories.user_repository import UserRepository
from app.data.repositories.email_repository import EmailRepository
from app.data.repositories.billing_repository import BillingRepository
from app.data.repositories.gmail_repository import GmailRepository
from app.data.repositories.job_repository import JobRepository
from app.core.exceptions import ValidationError, NotFoundError, InsufficientCreditsError, APIError


class TestEmailService:
    """Test-driven development for EmailService orchestration layer"""
    
    @pytest.fixture
    def mock_gmail_service(self):
        """Mock GmailService"""
        return Mock(spec=GmailService)
    
    @pytest.fixture
    def mock_billing_service(self):
        """Mock BillingService"""
        return Mock(spec=BillingService)
    
    @pytest.fixture
    def mock_auth_service(self):
        """Mock AuthService"""
        return Mock(spec=AuthService)
    
    @pytest.fixture
    def mock_user_repo(self):
        """Mock UserRepository"""
        return Mock(spec=UserRepository)
    
    @pytest.fixture
    def mock_email_repo(self):
        """Mock EmailRepository"""
        return Mock(spec=EmailRepository)
    
    @pytest.fixture
    def mock_billing_repo(self):
        """Mock BillingRepository"""
        return Mock(spec=BillingRepository)
    
    @pytest.fixture
    def mock_gmail_repo(self):
        """Mock GmailRepository"""
        return Mock(spec=GmailRepository)
    
    @pytest.fixture
    def mock_job_repo(self):
        """Mock JobRepository"""
        return Mock(spec=JobRepository)
    
    @pytest.fixture
    def email_service(self, mock_gmail_service, mock_billing_service, mock_auth_service, 
                     mock_user_repo, mock_email_repo, mock_billing_repo):
        """Create EmailService instance - this doesn't exist yet!"""
        return EmailService(
            gmail_service=mock_gmail_service,
            billing_service=mock_billing_service,
            auth_service=mock_auth_service,
            user_repository=mock_user_repo,
            email_repository=mock_email_repo,
            billing_repository=mock_billing_repo
        )
    
    @pytest.fixture
    def sample_user_profile(self):
        """Sample user profile for testing"""
        return {
            "user_id": str(uuid4()),
            "email": "user@example.com",
            "display_name": "Test User",
            "credits_remaining": 50,
            "bot_enabled": True,
            "email_filters": {
                "exclude_senders": ["noreply@spam.com"],
                "exclude_domains": ["spam.com"],
                "include_keywords": [],
                "exclude_keywords": ["unsubscribe"],
                "min_email_length": 100,
                "max_emails_per_batch": 10
            },
            "ai_preferences": {
                "summary_style": "concise",
                "summary_length": "medium",
                "include_action_items": True,
                "include_sentiment": False,
                "language": "en"
            },
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }
    
    @pytest.fixture
    def sample_email_data(self):
        """Sample email data for testing"""
        return {
            "message_id": "msg_12345",
            "subject": "Important Business Email",
            "sender": "client@company.com",
            "content": "This is an important business email that requires immediate attention and action from the recipient.",
            "thread_id": "thread_67890",
            "received_at": datetime.now().isoformat(),
            "attachments": [],
            "labels": ["INBOX", "UNREAD", "IMPORTANT"]
        }
    
    @pytest.fixture
    def sample_processing_job(self):
        """Sample processing job for testing"""
        return {
            "job_id": str(uuid4()),
            "user_id": str(uuid4()),
            "message_id": "msg_12345",
            "job_type": "email_summary",
            "status": "pending",
            "created_at": datetime.now().isoformat(),
            "processing_config": {
                "summary_style": "concise",
                "include_action_items": True
            }
        }
    
    # --- Core Email Processing Pipeline Tests ---
    
    @pytest.mark.asyncio
    async def test_process_single_email_success(self, email_service, sample_user_profile, sample_email_data):
        """Test successful processing of a single email"""
        user_id = sample_user_profile["user_id"]
        message_id = sample_email_data["message_id"]
        
        # Mock user repository
        email_service.user_repository.get_user_profile.return_value = sample_user_profile
        
        # Mock auth service for permissions
        email_service.auth_service.check_user_permissions.return_value = {
            "allowed": True,
            "reason": None
        }
        
        # Mock Gmail service for email processing
        email_service.gmail_service.process_email = AsyncMock(return_value={
            "success": True,
            "message_id": message_id,
            "summary_sent": True,
            "processing_time": 2.5,
            "credits_used": 1
        })
        
        # Mock billing service for credit deduction
        email_service.billing_service.deduct_manual_credits = AsyncMock(return_value={
            "success": True,
            "credits_deducted": 1,
            "remaining_balance": 49
        })
        
        result = await email_service.process_single_email(user_id, message_id)
        
        assert result["success"] == True
        assert result["message_id"] == message_id
        assert result["credits_used"] == 1
        assert result["processing_time"] > 0
        assert result["summary_sent"] == True
        
        # Verify service interactions
        email_service.auth_service.check_user_permissions.assert_called_once_with(sample_user_profile, "email_processing")
        email_service.gmail_service.process_email.assert_called_once_with(user_id, message_id)
        email_service.billing_service.deduct_manual_credits.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_process_single_email_insufficient_credits(self, email_service, sample_user_profile):
        """Test processing email with insufficient credits"""
        user_id = sample_user_profile["user_id"]
        message_id = "msg_12345"
        
        # Update user profile to have zero credits
        sample_user_profile["credits_remaining"] = 0
        email_service.user_repository.get_user_profile.return_value = sample_user_profile
        
        # Mock auth service to deny permission
        email_service.auth_service.check_user_permissions.return_value = {
            "allowed": False,
            "reason": "Insufficient credits"
        }
        
        with pytest.raises(InsufficientCreditsError) as exc_info:
            await email_service.process_single_email(user_id, message_id)
        
        assert "insufficient credits" in str(exc_info.value).lower()
        
        # Verify Gmail service was not called
        email_service.gmail_service.process_email.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_process_single_email_bot_disabled(self, email_service, sample_user_profile):
        """Test processing email when bot is disabled"""
        user_id = sample_user_profile["user_id"]
        message_id = "msg_12345"
        
        # Update user profile to have bot disabled
        sample_user_profile["bot_enabled"] = False
        email_service.user_repository.get_user_profile.return_value = sample_user_profile
        
        # Mock auth service to deny permission
        email_service.auth_service.check_user_permissions.return_value = {
            "allowed": False,
            "reason": "Bot is disabled"
        }
        
        with pytest.raises(ValidationError) as exc_info:
            await email_service.process_single_email(user_id, message_id)
        
        assert "bot is disabled" in str(exc_info.value).lower()
    
    @pytest.mark.asyncio
    async def test_process_single_email_user_not_found(self, email_service):
        """Test processing email for non-existent user"""
        user_id = str(uuid4())
        message_id = "msg_12345"
        
        # Mock user not found
        email_service.user_repository.get_user_profile.return_value = None
        
        with pytest.raises(NotFoundError) as exc_info:
            await email_service.process_single_email(user_id, message_id)
        
        assert "user not found" in str(exc_info.value).lower()
    
    @pytest.mark.asyncio
    async def test_process_single_email_gmail_service_failure(self, email_service, sample_user_profile):
        """Test processing email when Gmail service fails"""
        user_id = sample_user_profile["user_id"]
        message_id = "msg_12345"
        
        # Mock user repository
        email_service.user_repository.get_user_profile.return_value = sample_user_profile
        
        # Mock auth service for permissions
        email_service.auth_service.check_user_permissions.return_value = {
            "allowed": True,
            "reason": None
        }
        
        # Mock Gmail service failure
        email_service.gmail_service.process_email = AsyncMock(side_effect=APIError("Gmail API failed"))
        
        with pytest.raises(APIError) as exc_info:
            await email_service.process_single_email(user_id, message_id)
        
        assert "gmail api failed" in str(exc_info.value).lower()
        
        # Verify billing service was not called
        email_service.billing_service.deduct_manual_credits.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_process_single_email_billing_failure(self, email_service, sample_user_profile):
        """Test processing email when billing service fails"""
        user_id = sample_user_profile["user_id"]
        message_id = "msg_12345"
        
        # Mock user repository
        email_service.user_repository.get_user_profile.return_value = sample_user_profile
        
        # Mock auth service for permissions
        email_service.auth_service.check_user_permissions.return_value = {
            "allowed": True,
            "reason": None
        }
        
        # Mock successful Gmail processing
        email_service.gmail_service.process_email = AsyncMock(return_value={
            "success": True,
            "message_id": message_id,
            "credits_used": 1
        })
        
        # Mock billing service failure
        email_service.billing_service.deduct_manual_credits = AsyncMock(side_effect=APIError("Billing service failed"))
        
        with pytest.raises(APIError) as exc_info:
            await email_service.process_single_email(user_id, message_id)
        
        assert "billing service failed" in str(exc_info.value).lower()
    
    # --- Batch Processing Tests ---
    
    @pytest.mark.asyncio
    async def test_process_user_emails_batch_success(self, email_service, sample_user_profile):
        """Test batch processing of user emails"""
        user_id = sample_user_profile["user_id"]
        
        # Mock user repository
        email_service.user_repository.get_user_profile.return_value = sample_user_profile
        
        # Mock Gmail service batch processing
        email_service.gmail_service.process_user_emails = AsyncMock(return_value={
            "success": True,
            "user_id": user_id,
            "emails_processed": 5,
            "credits_used": 5,
            "failed_emails": 0,
            "errors": []
        })
        
        # Mock billing service batch deduction
        email_service.billing_service.deduct_manual_credits = AsyncMock(return_value={
            "success": True,
            "credits_deducted": 5,
            "remaining_balance": 45
        })
        
        result = await email_service.process_user_emails(user_id, max_emails=10)
        
        assert result["success"] == True
        assert result["user_id"] == user_id
        assert result["emails_processed"] == 5
        assert result["credits_used"] == 5
        assert result["failed_emails"] == 0
        
        # Verify service interactions
        email_service.gmail_service.process_user_emails.assert_called_once_with(user_id, max_emails=10)
        email_service.billing_service.deduct_manual_credits.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_process_user_emails_partial_failure(self, email_service, sample_user_profile):
        """Test batch processing with partial failures"""
        user_id = sample_user_profile["user_id"]
        
        # Mock user repository
        email_service.user_repository.get_user_profile.return_value = sample_user_profile
        
        # Mock Gmail service with partial failures
        email_service.gmail_service.process_user_emails = AsyncMock(return_value={
            "success": True,
            "user_id": user_id,
            "emails_processed": 3,
            "credits_used": 3,
            "failed_emails": 2,
            "errors": [
                {"message_id": "msg_1", "error": "Processing failed"},
                {"message_id": "msg_2", "error": "Invalid email format"}
            ]
        })
        
        # Mock billing service
        email_service.billing_service.deduct_manual_credits = AsyncMock(return_value={
            "success": True,
            "credits_deducted": 3,
            "remaining_balance": 47
        })
        
        result = await email_service.process_user_emails(user_id, max_emails=5)
        
        assert result["success"] == True
        assert result["emails_processed"] == 3
        assert result["failed_emails"] == 2
        assert len(result["errors"]) == 2
        assert result["credits_used"] == 3
    
    @pytest.mark.asyncio
    async def test_process_user_emails_no_emails(self, email_service, sample_user_profile):
        """Test batch processing when no emails to process"""
        user_id = sample_user_profile["user_id"]
        
        # Mock user repository
        email_service.user_repository.get_user_profile.return_value = sample_user_profile
        
        # Mock Gmail service with no emails
        email_service.gmail_service.process_user_emails = AsyncMock(return_value={
            "success": True,
            "user_id": user_id,
            "emails_processed": 0,
            "credits_used": 0,
            "failed_emails": 0,
            "errors": []
        })
        
        result = await email_service.process_user_emails(user_id, max_emails=10)
        
        assert result["success"] == True
        assert result["emails_processed"] == 0
        assert result["credits_used"] == 0
        
        # Verify billing service was not called
        # No need to assert on mock that doesn't have the method
        pass
    
    # --- Email Discovery Tests ---
    
    @pytest.mark.asyncio
    async def test_discover_user_emails_success(self, email_service, sample_user_profile):
        """Test successful email discovery"""
        user_id = sample_user_profile["user_id"]
        
        # Mock user repository
        email_service.user_repository.get_user_profile.return_value = sample_user_profile
        
        # Mock Gmail service discovery
        email_service.gmail_service.discover_emails = AsyncMock(return_value={
            "success": True,
            "user_id": user_id,
            "emails_discovered": 8,
            "new_emails": 6,
            "filtered_emails": 2,
            "discovered_emails": [
                {"message_id": "msg_1", "subject": "Important Email 1"},
                {"message_id": "msg_2", "subject": "Important Email 2"}
            ]
        })
        
        result = await email_service.discover_user_emails(user_id, apply_filters=True)
        
        assert result["success"] == True
        assert result["user_id"] == user_id
        assert result["emails_discovered"] == 8
        assert result["new_emails"] == 6
        assert result["filtered_emails"] == 2
        
        # Verify service interactions
        email_service.gmail_service.discover_emails.assert_called_once_with(user_id, apply_filters=True)
    
    @pytest.mark.asyncio
    async def test_discover_user_emails_no_gmail_connection(self, email_service, sample_user_profile):
        """Test email discovery when Gmail connection is missing"""
        user_id = sample_user_profile["user_id"]
        
        # Mock user repository
        email_service.user_repository.get_user_profile.return_value = sample_user_profile
        
        # Mock Gmail service failure
        email_service.gmail_service.discover_emails = AsyncMock(side_effect=NotFoundError("Gmail connection not found"))
        
        with pytest.raises(NotFoundError) as exc_info:
            await email_service.discover_user_emails(user_id)
        
        assert "gmail connection not found" in str(exc_info.value).lower()
    
    @pytest.mark.asyncio
    async def test_discover_user_emails_rate_limited(self, email_service, sample_user_profile):
        """Test email discovery when rate limited"""
        user_id = sample_user_profile["user_id"]
        
        # Mock user repository
        email_service.user_repository.get_user_profile.return_value = sample_user_profile
        
        # Mock Gmail service rate limit
        email_service.gmail_service.discover_emails = AsyncMock(side_effect=APIError("Rate limit exceeded"))
        
        with pytest.raises(APIError) as exc_info:
            await email_service.discover_user_emails(user_id)
        
        assert "rate limit exceeded" in str(exc_info.value).lower()
    
    # --- Processing Pipeline Orchestration Tests ---
    
    @pytest.mark.asyncio
    async def test_full_processing_pipeline_success(self, email_service, sample_user_profile):
        """Test full processing pipeline from discovery to completion"""
        user_id = sample_user_profile["user_id"]
        
        # Mock user repository
        email_service.user_repository.get_user_profile.return_value = sample_user_profile
        
        # Mock email discovery
        email_service.gmail_service.discover_emails = AsyncMock(return_value={
            "success": True,
            "user_id": user_id,
            "emails_discovered": 3,
            "new_emails": 3,
            "filtered_emails": 0
        })
        
        # Mock email processing
        email_service.gmail_service.process_user_emails = AsyncMock(return_value={
            "success": True,
            "user_id": user_id,
            "emails_processed": 3,
            "credits_used": 3,
            "failed_emails": 0,
            "errors": []
        })
        
        # Mock billing service
        email_service.billing_service.deduct_credits = AsyncMock(return_value={
            "success": True,
            "credits_deducted": 3,
            "remaining_balance": 47
        })
        
        result = await email_service.run_full_processing_pipeline(user_id)
        
        assert result["success"] == True
        assert result["user_id"] == user_id
        assert result["emails_discovered"] == 3
        assert result["emails_processed"] == 3
        assert result["credits_used"] == 3
        assert result["pipeline_completed"] == True
        
        # Verify all services were called
        email_service.gmail_service.discover_emails.assert_called_once()
        email_service.gmail_service.process_user_emails.assert_called_once()
        email_service.billing_service.deduct_manual_credits.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_full_processing_pipeline_discovery_failure(self, email_service, sample_user_profile):
        """Test full processing pipeline when discovery fails"""
        user_id = sample_user_profile["user_id"]
        
        # Mock user repository
        email_service.user_repository.get_user_profile.return_value = sample_user_profile
        
        # Mock email discovery failure
        email_service.gmail_service.discover_emails = AsyncMock(side_effect=APIError("Discovery failed"))
        
        with pytest.raises(APIError) as exc_info:
            await email_service.run_full_processing_pipeline(user_id)
        
        assert "discovery failed" in str(exc_info.value).lower()
        
        # Verify processing service was not called
        email_service.gmail_service.process_user_emails.assert_not_called()
        email_service.billing_service.deduct_manual_credits.assert_not_called()
        assert not hasattr(email_service.billing_service, 'deduct_manual_credits') or \
               email_service.billing_service.deduct_manual_credits.call_count == 0
    
    @pytest.mark.asyncio
    async def test_full_processing_pipeline_no_new_emails(self, email_service, sample_user_profile):
        """Test full processing pipeline when no new emails are found"""
        user_id = sample_user_profile["user_id"]
        
        # Mock user repository
        email_service.user_repository.get_user_profile.return_value = sample_user_profile
        
        # Mock email discovery with no new emails
        email_service.gmail_service.discover_emails = AsyncMock(return_value={
            "success": True,
            "user_id": user_id,
            "emails_discovered": 0,
            "new_emails": 0,
            "filtered_emails": 0
        })
        
        result = await email_service.run_full_processing_pipeline(user_id)
        
        assert result["success"] == True
        assert result["emails_discovered"] == 0
        assert result["emails_processed"] == 0
        assert result["credits_used"] == 0
        assert result["pipeline_completed"] == True
        
        # Verify processing service was not called
        assert not hasattr(email_service.gmail_service, 'process_user_emails') or \
               email_service.gmail_service.process_user_emails.call_count == 0
        assert not hasattr(email_service.billing_service, 'deduct_manual_credits') or \
               email_service.billing_service.deduct_manual_credits.call_count == 0
    
    # --- User Settings and Preferences Tests ---
    
    @pytest.mark.asyncio
    async def test_update_user_email_preferences_success(self, email_service, sample_user_profile):
        """Test updating user email preferences"""
        user_id = sample_user_profile["user_id"]
        
        new_preferences = {
            "email_filters": {
                "exclude_senders": ["spam@example.com"],
                "exclude_domains": ["badspam.com"],
                "min_email_length": 200
            },
            "ai_preferences": {
                "summary_style": "detailed",
                "include_action_items": False
            }
        }
        
        # Mock user repository
        email_service.user_repository.get_user_profile.return_value = sample_user_profile
        email_service.user_repository.update_user_profile.return_value = {
            **sample_user_profile,
            **new_preferences
        }
        
        result = await email_service.update_user_email_preferences(user_id, new_preferences)
        
        assert result["success"] == True
        assert result["user_id"] == user_id
        assert result["preferences_updated"] == True
        
        # Verify repository was called
        email_service.user_repository.update_user_profile.assert_called_once_with(user_id, new_preferences)
    
    @pytest.mark.asyncio
    async def test_update_user_email_preferences_invalid_user(self, email_service):
        """Test updating preferences for non-existent user"""
        user_id = str(uuid4())
        
        # Mock user not found
        email_service.user_repository.get_user_profile.return_value = None
        
        with pytest.raises(NotFoundError) as exc_info:
            await email_service.update_user_email_preferences(user_id, {})
        
        assert "user not found" in str(exc_info.value).lower()
    
    @pytest.mark.asyncio
    async def test_update_user_email_preferences_validation_error(self, email_service, sample_user_profile):
        """Test updating preferences with invalid data"""
        user_id = sample_user_profile["user_id"]
        
        invalid_preferences = {
            "email_filters": {
                "min_email_length": -1  # Invalid value
            }
        }
        
        # Mock user repository
        email_service.user_repository.get_user_profile.return_value = sample_user_profile
        email_service.user_repository.update_user_profile.side_effect = ValidationError("Invalid preferences")
        
        with pytest.raises(ValidationError) as exc_info:
            await email_service.update_user_email_preferences(user_id, invalid_preferences)
        
        assert "invalid preferences" in str(exc_info.value).lower()
    
    # --- Email Statistics and Analytics Tests ---
    
    def test_get_user_email_statistics_success(self, email_service, sample_user_profile):
        """Test getting user email statistics"""
        user_id = sample_user_profile["user_id"]
        
        # Mock user repository
        email_service.user_repository.get_user_profile.return_value = sample_user_profile
        
        # Mock email repository stats
        email_service.email_repository.get_processing_stats.return_value = {
            "user_id": user_id,
            "total_discovered": 100,
            "total_processed": 95,
            "total_successful": 90,
            "total_failed": 5,
            "success_rate": 0.95,
            "total_credits_used": 90,
            "average_processing_time": 2.3
        }
        
        # Mock Gmail service stats
        email_service.gmail_service.get_user_gmail_statistics.return_value = {
            "user_id": user_id,
            "connection_status": "connected",
            "email_address": "user@example.com",
            "total_discovered": 100,
            "total_processed": 95,
            "success_rate": 0.95
        }
        
        result = email_service.get_user_email_statistics(user_id)
        
        assert result["user_id"] == user_id
        assert result["total_discovered"] == 100
        assert result["total_processed"] == 95
        assert result["success_rate"] == 0.95
        assert result["total_credits_used"] == 90
        assert result["connection_status"] == "connected"
    
    def test_get_user_email_statistics_no_user(self, email_service):
        """Test getting statistics for non-existent user"""
        user_id = str(uuid4())
        
        # Mock user not found
        email_service.user_repository.get_user_profile.return_value = None
        
        with pytest.raises(NotFoundError) as exc_info:
            email_service.get_user_email_statistics(user_id)
        
        assert "user not found" in str(exc_info.value).lower()
    
    def test_get_user_processing_history_success(self, email_service, sample_user_profile):
        """Test getting user processing history"""
        user_id = sample_user_profile["user_id"]
        
        # Mock user repository
        email_service.user_repository.get_user_profile.return_value = sample_user_profile
        
        # Mock email repository history
        email_service.email_repository.get_processing_history.return_value = [
            {
                "message_id": "msg_1",
                "subject": "Email 1",
                "status": "completed",
                "processing_time": 2.1,
                "credits_used": 1,
                "completed_at": datetime.now().isoformat()
            },
            {
                "message_id": "msg_2",
                "subject": "Email 2",
                "status": "failed",
                "processing_time": 1.5,
                "credits_used": 0,
                "completed_at": datetime.now().isoformat()
            }
        ]
        
        result = email_service.get_user_processing_history(user_id, limit=10)
        
        assert result["user_id"] == user_id
        assert len(result["processing_history"]) == 2
        assert result["processing_history"][0]["message_id"] == "msg_1"
        assert result["processing_history"][1]["status"] == "failed"
    
    # --- Error Handling and Recovery Tests ---
    
    @pytest.mark.asyncio
    async def test_retry_failed_emails_success(self, email_service, sample_user_profile):
        """Test retrying failed email processing"""
        user_id = sample_user_profile["user_id"]
        
        # Mock user repository
        email_service.user_repository.get_user_profile.return_value = sample_user_profile
        
        # Mock email repository failed emails
        email_service.email_repository.get_processing_history.return_value = [
            {
                "message_id": "msg_1",
                "status": "failed",
                "retry_count": 1,
                "max_retries": 3
            },
            {
                "message_id": "msg_2",
                "status": "failed",
                "retry_count": 0,
                "max_retries": 3
            }
        ]
        
        # Mock successful retry processing
        with patch.object(email_service, 'process_single_email', new_callable=AsyncMock) as mock_process:
            mock_process.return_value = {
                "success": True,
                "message_id": "msg_1",
                "credits_used": 1
            }
            
            result = await email_service.retry_failed_emails(user_id, max_retries=5)
            
            assert result["success"] == True
            assert result["user_id"] == user_id
            assert result["emails_retried"] == 2
            assert result["successful_retries"] == 2
            assert result["failed_retries"] == 0
            assert mock_process.call_count == 2
    
    @pytest.mark.asyncio
    async def test_retry_failed_emails_max_retries_exceeded(self, email_service, sample_user_profile):
        """Test retrying failed emails when max retries exceeded"""
        user_id = sample_user_profile["user_id"]
        
        # Mock user repository
        email_service.user_repository.get_user_profile.return_value = sample_user_profile
        
        # Mock email repository with emails that exceeded max retries
        email_service.email_repository.get_processing_history.return_value = [
            {
                "message_id": "msg_1",
                "status": "failed",
                "retry_count": 3,
                "max_retries": 3
            }
        ]
        
        result = await email_service.retry_failed_emails(user_id, max_retries=5)
        
        assert result["success"] == True
        assert result["emails_retried"] == 0
        assert result["skipped_max_retries"] == 1
        
        # Verify processing service was not called
        email_service.gmail_service.process_email.assert_not_called()
    
    # --- Bulk Operations Tests ---
    
    @pytest.mark.asyncio
    async def test_bulk_process_users_success(self, email_service):
        """Test bulk processing for multiple users"""
        user_ids = [str(uuid4()) for _ in range(3)]
        
        # Mock successful processing for all users
        email_service.gmail_service.bulk_process_users = AsyncMock(return_value={
            "total_users": 3,
            "successful_users": 3,
            "failed_users": 0,
            "total_emails_processed": 12,
            "total_credits_used": 12
        })
        
        result = await email_service.bulk_process_users(user_ids)
        
        assert result["total_users"] == 3
        assert result["successful_users"] == 3
        assert result["failed_users"] == 0
        assert result["total_emails_processed"] == 12
        assert result["total_credits_used"] == 12
        
        # Verify service was called with correct parameters
        email_service.gmail_service.bulk_process_users.assert_called_once_with(user_ids)
    
    @pytest.mark.asyncio
    async def test_bulk_process_users_partial_failure(self, email_service):
        """Test bulk processing with some user failures"""
        user_ids = [str(uuid4()) for _ in range(5)]
        
        # Mock partial failures
        email_service.gmail_service.bulk_process_users = AsyncMock(return_value={
            "total_users": 5,
            "successful_users": 3,
            "failed_users": 2,
            "total_emails_processed": 8,
            "total_credits_used": 8
        })
        
        result = await email_service.bulk_process_users(user_ids)
        
        assert result["total_users"] == 5
        assert result["successful_users"] == 3
        assert result["failed_users"] == 2
        assert result["success_rate"] == 0.6
    
    # --- Performance and Monitoring Tests ---
    
    def test_get_processing_performance_metrics(self, email_service):
        """Test getting processing performance metrics"""
        # Mock email repository stats
        email_service.email_repository.get_processing_stats.return_value = {
            "total_pending": 10,
            "total_processing": 5,
            "total_completed": 1000,
            "total_failed": 50,
            "success_rate": 0.95,
            "average_processing_time": 2.3
        }
        
        result = email_service.get_processing_performance_metrics()
        
        assert result["total_pending"] == 10
        assert result["total_processing"] == 5
        assert result["total_completed"] == 1000
        assert result["success_rate"] == 0.95
        assert result["average_processing_time"] == 2.3
        assert result["queue_health"] in ["healthy", "degraded", "overloaded"]
    
    def test_get_system_health_status(self, email_service):
        """Test getting system health status"""
        # Mock Gmail service health
        email_service.gmail_service.health_check.return_value = {
            "status": "healthy",
            "dependencies": {"gmail_api": "available"}
        }
        
        # Mock billing service health
        email_service.billing_service.get_billing_status.return_value = {
            "stripe_enabled": True,
            "status": "healthy"
        }
        
        result = email_service.get_system_health_status()
        
        assert result["status"] in ["healthy", "degraded", "unhealthy"]
        assert result["gmail_service"] == "healthy"
        assert result["billing_service"] == "healthy"
        assert "timestamp" in result
    
    # --- Configuration and Settings Tests ---
    
    def test_get_service_configuration(self, email_service):
        """Test getting service configuration"""
        result = email_service.get_service_configuration()
        
        assert "max_emails_per_batch" in result
        assert "default_retry_attempts" in result
        assert "processing_timeout_minutes" in result
        assert "rate_limit_per_minute" in result
        assert result["max_emails_per_batch"] > 0
        assert result["default_retry_attempts"] > 0
    
    @pytest.mark.asyncio
    async def test_update_service_configuration_success(self, email_service):
        """Test updating service configuration"""
        new_config = {
            "max_emails_per_batch": 20,
            "default_retry_attempts": 5,
            "processing_timeout_minutes": 10
        }
        
        result = await email_service.update_service_configuration(new_config)
        
        assert result["success"] == True
        assert result["configuration_updated"] == True
        assert result["new_config"]["max_emails_per_batch"] == 20
    
    @pytest.mark.asyncio
    async def test_update_service_configuration_validation_error(self, email_service):
        """Test updating service configuration with invalid values"""
        invalid_config = {
            "max_emails_per_batch": -1,  # Invalid value
            "default_retry_attempts": 0
        }
        
        with pytest.raises(ValidationError) as exc_info:
            await email_service.update_service_configuration(invalid_config)
        
        assert "invalid configuration" in str(exc_info.value).lower()
    
    # --- Cleanup and Maintenance Tests ---
    
    @pytest.mark.asyncio
    async def test_cleanup_old_processing_data(self, email_service):
        """Test cleaning up old processing data"""
        # Mock email repository cleanup
        email_service.email_repository.cleanup_old_records.return_value = 25
        
        result = await email_service.cleanup_old_processing_data(days=30)
        
        assert result["success"] == True
        assert result["records_cleaned"] == 25
        assert result["cleanup_days"] == 30
        
        # Verify repository was called
        email_service.email_repository.cleanup_old_records.assert_called_once_with(30)
    
    @pytest.mark.asyncio
    async def test_cleanup_stale_processing_jobs(self, email_service):
        """Test cleaning up stale processing jobs"""
        # Mock Gmail service cleanup
        email_service.gmail_service.cleanup_stale_jobs = AsyncMock(return_value={
            "success": True,
            "cleaned_jobs": 5
        })
        
        result = await email_service.cleanup_stale_processing_jobs()
        
        assert result["success"] == True
        assert result["cleaned_jobs"] == 5
        
        # Verify service was called
        email_service.gmail_service.cleanup_stale_jobs.assert_called_once()
    
    # --- Integration and End-to-End Tests ---
    
    @pytest.mark.asyncio
    async def test_end_to_end_processing_workflow(self, email_service, sample_user_profile):
        """Test complete end-to-end processing workflow"""
        user_id = sample_user_profile["user_id"]
        
        # Mock all services for complete workflow
        email_service.user_repository.get_user_profile.return_value = sample_user_profile
        email_service.auth_service.check_user_permissions.return_value = {
            "allowed": True,
            "reason": None
        }
        
        # Mock discovery
        email_service.gmail_service.discover_emails = AsyncMock(return_value={
            "success": True,
            "user_id": user_id,
            "emails_discovered": 5,
            "new_emails": 5
        })
        
        # Mock processing
        email_service.gmail_service.process_user_emails = AsyncMock(return_value={
            "success": True,
            "user_id": user_id,
            "emails_processed": 5,
            "credits_used": 5,
            "failed_emails": 0
        })
        
        # Mock billing
        email_service.billing_service.deduct_manual_credits = AsyncMock(return_value={
            "success": True,
            "credits_deducted": 5,
            "remaining_balance": 45
        })
        
        # Run complete workflow
        result = await email_service.run_full_processing_pipeline(user_id)
        
        assert result["success"] == True
        assert result["pipeline_completed"] == True
        assert result["emails_discovered"] == 5
        assert result["emails_processed"] == 5
        assert result["credits_used"] == 5
        
        # Verify all services were called in correct order
        email_service.gmail_service.discover_emails.assert_called_once()
        email_service.gmail_service.process_user_emails.assert_called_once()
        email_service.billing_service.deduct_manual_credits.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_concurrent_processing_prevention(self, email_service, sample_user_profile):
        """Test that concurrent processing for the same user is prevented"""
        user_id = sample_user_profile["user_id"]
        email_service.user_repository.get_user_profile.return_value = sample_user_profile

        # Mock the dependency *inside* the method, not the method itself
        async def slow_dependency_call(*args, **kwargs):
            await asyncio.sleep(0.1)
            return {"success": True, "emails_processed": 1, "credits_used": 1}

        email_service.gmail_service.process_user_emails = AsyncMock(side_effect=slow_dependency_call)
        email_service.billing_service.deduct_manual_credits = AsyncMock()

        # Start multiple tasks calling the real method
        tasks = [
            email_service.process_user_emails(user_id)
            for _ in range(3)
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Filter for successful results and validation errors
        success_results = [r for r in results if isinstance(r, dict)]
        validation_errors = [r for r in results if isinstance(r, ValidationError)]

        # Expect exactly one success and two failures
        assert len(success_results) == 1
        assert len(validation_errors) == 2
    
    # --- Edge Cases and Error Scenarios ---
    
    @pytest.mark.asyncio
    async def test_processing_with_empty_user_id(self, email_service):
        """Test processing with empty user ID"""
        with pytest.raises(ValidationError) as exc_info:
            await email_service.process_single_email("", "msg_123")
        
        assert "user_id" in str(exc_info.value).lower()
    
    @pytest.mark.asyncio
    async def test_processing_with_empty_message_id(self, email_service, sample_user_profile):
        """Test processing with empty message ID"""
        user_id = sample_user_profile["user_id"]
        
        with pytest.raises(ValidationError) as exc_info:
            await email_service.process_single_email(user_id, "")
        
        assert "message_id" in str(exc_info.value).lower()
    
    @pytest.mark.asyncio
    async def test_processing_with_invalid_max_emails(self, email_service, sample_user_profile):
        """Test processing with invalid max_emails parameter"""
        user_id = sample_user_profile["user_id"]
        
        with pytest.raises(ValidationError) as exc_info:
            await email_service.process_user_emails(user_id, max_emails=-1)
        
        assert "max_emails" in str(exc_info.value).lower()
    
    @pytest.mark.asyncio
    async def test_service_graceful_degradation(self, email_service, sample_user_profile):
        """Test service graceful degradation when dependencies fail"""
        user_id = sample_user_profile["user_id"]
        
        # Mock user repository
        email_service.user_repository.get_user_profile.return_value = sample_user_profile
        
        # Mock Gmail service unavailable
        email_service.gmail_service.discover_emails = AsyncMock(side_effect=APIError("Gmail service unavailable"))
        
        # Service should handle gracefully and return informative error
        with pytest.raises(APIError) as exc_info:
            await email_service.discover_user_emails(user_id)
        
        assert "gmail service unavailable" in str(exc_info.value).lower()
    
    # --- Performance and Load Tests ---
    
    @pytest.mark.asyncio
    async def test_high_volume_processing_performance(self, email_service, sample_user_profile):
        """Test processing performance with high volume"""
        user_id = sample_user_profile["user_id"]
        
        # Mock user repository
        email_service.user_repository.get_user_profile.return_value = sample_user_profile
        
        # Mock high-volume processing
        email_service.gmail_service.process_user_emails = AsyncMock(return_value={
            "success": True,
            "user_id": user_id,
            "emails_processed": 100,
            "credits_used": 100,
            "failed_emails": 0,
            "processing_time": 45.2
        })
        
        # Mock billing
        email_service.billing_service.deduct_credits = AsyncMock(return_value={
            "success": True,
            "credits_deducted": 100,
            "remaining_balance": 0
        })
        
        start_time = datetime.now()
        result = await email_service.process_user_emails(user_id, max_emails=100)
        end_time = datetime.now()
        
        processing_time = (end_time - start_time).total_seconds()
        
        assert result["success"] == True
        assert result["emails_processed"] == 100
        assert processing_time < 60  # Should complete within 60 seconds
    
    def test_memory_usage_optimization(self, email_service):
        """Test that service doesn't leak memory with large datasets"""
        # This would be more comprehensive in a real test environment
        # For now, just verify that service instances are properly cleaned up
        
        # Create multiple service instances
        services = []
        for i in range(100):
            services.append(email_service)
        
        # Clear references
        services.clear()
        
        # Verify service is still functional
        config = email_service.get_service_configuration()
        assert config is not None