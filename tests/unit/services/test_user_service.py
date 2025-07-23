# tests/unit/services/test_user_service.py
"""
Test suite for UserService - focused on core email bot functionality.
Tests user profiles, preferences, credits, and bot management.
"""
import pytest
from uuid import uuid4
from datetime import datetime
from unittest.mock import Mock, AsyncMock

from app.services.user_service import UserService
from app.services.billing_service import BillingService
from app.data.repositories.user_repository import UserRepository
from app.data.repositories.billing_repository import BillingRepository
from app.data.repositories.email_repository import EmailRepository
from app.data.repositories.gmail_repository import GmailRepository
from app.core.exceptions import ValidationError, NotFoundError


class TestUserService:
    """Test suite for UserService"""
    
    @pytest.fixture
    def mock_user_repo(self):
        """Mock UserRepository"""
        return Mock(spec=UserRepository)
    
    @pytest.fixture
    def mock_billing_service(self):
        """Mock BillingService"""
        return Mock(spec=BillingService)
    
    @pytest.fixture
    def mock_billing_repo(self):
        """Mock BillingRepository"""
        return Mock(spec=BillingRepository)
    
    @pytest.fixture
    def mock_email_repo(self):
        """Mock EmailRepository"""
        return Mock(spec=EmailRepository)
    
    @pytest.fixture
    def mock_gmail_repo(self):
        """Mock GmailRepository"""
        return Mock(spec=GmailRepository)
    
    @pytest.fixture
    def user_service(self, mock_user_repo, mock_billing_service, mock_billing_repo, 
                    mock_email_repo, mock_gmail_repo):
        """Create UserService instance"""
        return UserService(
            user_repository=mock_user_repo,
            billing_service=mock_billing_service,
            billing_repository=mock_billing_repo,
            email_repository=mock_email_repo,
            gmail_repository=mock_gmail_repo
        )
    
    @pytest.fixture
    def sample_user_profile(self):
        """Sample user profile"""
        return {
            "user_id": str(uuid4()),
            "email": "grandma@example.com",
            "display_name": "Grandma Smith",
            "timezone": "America/New_York",
            "email_filters": {
                "exclude_senders": ["noreply@spam.com"],
                "exclude_domains": ["spam.com"],
                "min_email_length": 100
            },
            "ai_preferences": {
                "summary_style": "concise",
                "summary_length": "medium",
                "include_action_items": True,
                "language": "en"
            },
            "credits_remaining": 25,
            "bot_enabled": True,
            "processing_frequency": "30min",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }
    
    # --- Core User Profile Tests ---
    
    @pytest.mark.asyncio
    async def test_get_user_profile_success(self, user_service, sample_user_profile):
        """Test getting user profile"""
        user_id = sample_user_profile["user_id"]
        
        # Mock repository
        user_service.user_repository.get_user_profile.return_value = sample_user_profile
        
        result = await user_service.get_user_profile(user_id)
        
        assert result["user_id"] == user_id
        assert result["email"] == "grandma@example.com"
        assert result["display_name"] == "Grandma Smith"
        assert result["credits_remaining"] == 25
        assert result["bot_enabled"] == True
    
    @pytest.mark.asyncio
    async def test_get_user_profile_not_found(self, user_service):
        """Test getting non-existent user"""
        user_id = str(uuid4())
        
        # Mock repository
        user_service.user_repository.get_user_profile.return_value = None
        
        with pytest.raises(NotFoundError) as exc_info:
            await user_service.get_user_profile(user_id)
        
        assert "not found" in str(exc_info.value).lower()
    
    @pytest.mark.asyncio
    async def test_create_user_profile_success(self, user_service, sample_user_profile):
        """Test creating new user profile"""
        user_data = {
            "user_id": sample_user_profile["user_id"],
            "email": "grandma@example.com",
            "display_name": "Grandma Smith",
            "timezone": "America/New_York"
        }
        
        # Create expected profile with default values
        expected_profile = {
            **sample_user_profile,
            "email": "grandma@example.com",
            "display_name": "Grandma Smith",
            "timezone": "America/New_York",
            "credits_remaining": 5,  # Default starter credits
            "bot_enabled": True  # Default enabled
        }
        
        # Mock repository
        user_service.user_repository.create_user_profile.return_value = expected_profile
        
        result = await user_service.create_user_profile(user_data)
        
        assert result["user_id"] == user_data["user_id"]
        assert result["email"] == user_data["email"]
        assert result["credits_remaining"] == 5  # Default starter credits
        assert result["bot_enabled"] == True  # Default enabled
    
    @pytest.mark.asyncio
    async def test_create_user_profile_validation_error(self, user_service):
        """Test creating user with invalid data"""
        invalid_data = {
            "user_id": "",  # Empty user_id
            "email": "not-an-email"  # Invalid email
        }
        
        with pytest.raises(ValidationError):
            await user_service.create_user_profile(invalid_data)
    
    @pytest.mark.asyncio
    async def test_update_user_profile_success(self, user_service, sample_user_profile):
        """Test updating user profile"""
        user_id = sample_user_profile["user_id"]
        updates = {
            "display_name": "Grandma Jones",
            "timezone": "Europe/London"
        }
        
        # Mock repository
        user_service.user_repository.get_user_profile.return_value = sample_user_profile
        updated_profile = {**sample_user_profile, **updates}
        user_service.user_repository.update_user_profile.return_value = updated_profile
        
        result = await user_service.update_user_profile(user_id, updates)
        
        assert result["display_name"] == "Grandma Jones"
        assert result["timezone"] == "Europe/London"
    
    @pytest.mark.asyncio
    async def test_delete_user_profile_success(self, user_service, sample_user_profile):
        """Test deleting user profile"""
        user_id = sample_user_profile["user_id"]
        
        # Mock repository
        user_service.user_repository.get_user_profile.return_value = sample_user_profile
        user_service.user_repository.delete_user_profile.return_value = True
        user_service.email_repository.delete_user_email_data.return_value = 15
        user_service.gmail_repository.cleanup_user_connections.return_value = True
        
        result = await user_service.delete_user_profile(user_id)
        
        assert result["success"] == True
        assert result["user_id"] == user_id
        assert result["data_cleaned"] == True
        assert result["emails_cleaned"] == 15
    
    # --- User Preferences Tests ---
    
    @pytest.mark.asyncio
    async def test_get_user_preferences_success(self, user_service, sample_user_profile):
        """Test getting user preferences"""
        user_id = sample_user_profile["user_id"]
        
        # Mock repository
        user_service.user_repository.get_user_profile.return_value = sample_user_profile
        
        result = await user_service.get_user_preferences(user_id)
        
        assert result["user_id"] == user_id
        assert result["email_filters"]["exclude_senders"] == ["noreply@spam.com"]
        assert result["ai_preferences"]["summary_style"] == "concise"
        assert result["processing_frequency"] == "30min"
    
    @pytest.mark.asyncio
    async def test_update_email_filters_success(self, user_service, sample_user_profile):
        """Test updating email filters"""
        user_id = sample_user_profile["user_id"]
        new_filters = {
            "exclude_senders": ["noreply@spam.com", "marketing@ads.com"],
            "exclude_domains": ["spam.com", "ads.com"],
            "min_email_length": 200
        }
        
        # Mock repository
        user_service.user_repository.get_user_profile.return_value = sample_user_profile
        updated_profile = {**sample_user_profile, "email_filters": new_filters}
        user_service.user_repository.update_user_profile.return_value = updated_profile
        
        result = await user_service.update_email_filters(user_id, new_filters)
        
        assert result["success"] == True
        assert result["email_filters"]["min_email_length"] == 200
        assert len(result["email_filters"]["exclude_senders"]) == 2
    
    @pytest.mark.asyncio
    async def test_update_ai_preferences_success(self, user_service, sample_user_profile):
        """Test updating AI preferences"""
        user_id = sample_user_profile["user_id"]
        new_preferences = {
            "summary_style": "detailed",
            "summary_length": "long",
            "include_action_items": False,
            "language": "en"
        }
        
        # Mock repository
        user_service.user_repository.get_user_profile.return_value = sample_user_profile
        updated_profile = {**sample_user_profile, "ai_preferences": new_preferences}
        user_service.user_repository.update_user_profile.return_value = updated_profile
        
        result = await user_service.update_ai_preferences(user_id, new_preferences)
        
        assert result["success"] == True
        assert result["ai_preferences"]["summary_style"] == "detailed"
        assert result["ai_preferences"]["include_action_items"] == False
    
    @pytest.mark.asyncio
    async def test_reset_preferences_to_default(self, user_service, sample_user_profile):
        """Test resetting preferences to defaults"""
        user_id = sample_user_profile["user_id"]
        
        # Mock repository
        user_service.user_repository.get_user_profile.return_value = sample_user_profile
        user_service.user_repository.update_user_profile.return_value = sample_user_profile
        
        result = await user_service.reset_preferences_to_default(user_id)
        
        assert result["success"] == True
        assert result["preferences_reset"] == True
    
    # --- Settings Tests ---
    
    @pytest.mark.asyncio
    async def test_update_timezone_success(self, user_service, sample_user_profile):
        """Test updating timezone"""
        user_id = sample_user_profile["user_id"]
        new_timezone = "Europe/London"
        
        # Mock repository
        user_service.user_repository.get_user_profile.return_value = sample_user_profile
        updated_profile = {**sample_user_profile, "timezone": new_timezone}
        user_service.user_repository.update_user_profile.return_value = updated_profile
        
        result = await user_service.update_timezone(user_id, new_timezone)
        
        assert result["success"] == True
        assert result["timezone"] == new_timezone
    
    @pytest.mark.asyncio
    async def test_update_timezone_invalid(self, user_service, sample_user_profile):
        """Test updating to invalid timezone"""
        user_id = sample_user_profile["user_id"]
        invalid_timezone = "Invalid/Timezone"
        
        # Mock repository
        user_service.user_repository.get_user_profile.return_value = sample_user_profile
        
        with pytest.raises(ValidationError) as exc_info:
            await user_service.update_timezone(user_id, invalid_timezone)
        
        assert "invalid timezone" in str(exc_info.value).lower()
    
    # --- Credit Management Tests ---
    
    @pytest.mark.asyncio
    async def test_get_credit_balance_success(self, user_service, sample_user_profile):
        """Test getting credit balance"""
        user_id = sample_user_profile["user_id"]
        
        # Mock repository
        user_service.user_repository.get_user_profile.return_value = sample_user_profile
        
        result = await user_service.get_credit_balance(user_id)
        
        assert result["user_id"] == user_id
        assert result["credits_remaining"] == 25
        assert result["last_updated"] is not None
    
    @pytest.mark.asyncio
    async def test_get_credit_history_success(self, user_service, sample_user_profile):
        """Test getting credit history"""
        user_id = sample_user_profile["user_id"]
        sample_transactions = [
            {
                "id": str(uuid4()),
                "transaction_type": "purchase",
                "credit_amount": 100,
                "description": "Credit purchase",
                "created_at": datetime.now().isoformat()
            },
            {
                "id": str(uuid4()),
                "transaction_type": "usage",
                "credit_amount": -5,
                "description": "Email processing",
                "created_at": datetime.now().isoformat()
            }
        ]
        
        # Mock repository
        user_service.user_repository.get_user_profile.return_value = sample_user_profile
        user_service.billing_repository.get_transactions_for_user = AsyncMock(return_value=sample_transactions)
        
        result = await user_service.get_credit_history(user_id, limit=10)
        
        assert result["user_id"] == user_id
        assert len(result["transactions"]) == 2
        assert result["transactions"][0]["transaction_type"] == "purchase"
    
    @pytest.mark.asyncio
    async def test_check_sufficient_credits_true(self, user_service, sample_user_profile):
        """Test checking sufficient credits - has enough"""
        user_id = sample_user_profile["user_id"]
        
        # Mock repository
        user_service.user_repository.get_user_profile.return_value = sample_user_profile
        
        result = await user_service.check_sufficient_credits(user_id, 10)
        
        assert result == True  # User has 25 credits, needs 10
    
    @pytest.mark.asyncio
    async def test_check_sufficient_credits_false(self, user_service, sample_user_profile):
        """Test checking sufficient credits - not enough"""
        user_id = sample_user_profile["user_id"]
        
        # Mock repository
        user_service.user_repository.get_user_profile.return_value = sample_user_profile
        
        result = await user_service.check_sufficient_credits(user_id, 50)
        
        assert result == False  # User has 25 credits, needs 50
    
    # --- Bot Management Tests ---
    
    @pytest.mark.asyncio
    async def test_enable_bot_success(self, user_service, sample_user_profile):
        """Test enabling bot"""
        user_id = sample_user_profile["user_id"]
        
        # Mock repository
        user_service.user_repository.get_user_profile.return_value = sample_user_profile
        updated_profile = {**sample_user_profile, "bot_enabled": True}
        user_service.user_repository.update_user_profile.return_value = updated_profile
        
        result = await user_service.enable_bot(user_id)
        
        assert result["success"] == True
        assert result["bot_enabled"] == True
    
    @pytest.mark.asyncio
    async def test_disable_bot_success(self, user_service, sample_user_profile):
        """Test disabling bot"""
        user_id = sample_user_profile["user_id"]
        
        # Mock repository
        user_service.user_repository.get_user_profile.return_value = sample_user_profile
        updated_profile = {**sample_user_profile, "bot_enabled": False}
        user_service.user_repository.update_user_profile.return_value = updated_profile
        
        result = await user_service.disable_bot(user_id)
        
        assert result["success"] == True
        assert result["bot_enabled"] == False
    
    @pytest.mark.asyncio
    async def test_get_bot_status_active(self, user_service, sample_user_profile):
        """Test getting bot status - active"""
        user_id = sample_user_profile["user_id"]
        
        # Mock repository
        user_service.user_repository.get_user_profile.return_value = sample_user_profile
        user_service.gmail_repository.get_connection_info.return_value = {
            "user_id": user_id,
            "connection_status": "connected",
            "email_address": "grandma@example.com"
        }
        
        result = await user_service.get_bot_status(user_id)
        
        assert result["user_id"] == user_id
        assert result["bot_enabled"] == True
        assert result["gmail_connected"] == True
        assert result["credits_remaining"] == 25
        assert result["status"] == "active"
        assert result["processing_frequency"] == "30min"
    
    @pytest.mark.asyncio
    async def test_get_bot_status_no_gmail(self, user_service, sample_user_profile):
        """Test getting bot status - no Gmail connection"""
        user_id = sample_user_profile["user_id"]
        
        # Mock repository
        user_service.user_repository.get_user_profile.return_value = sample_user_profile
        user_service.gmail_repository.get_connection_info.return_value = None
        
        result = await user_service.get_bot_status(user_id)
        
        assert result["status"] == "no_gmail"
        assert result["gmail_connected"] == False
    
    @pytest.mark.asyncio
    async def test_get_bot_status_no_credits(self, user_service, sample_user_profile):
        """Test getting bot status - no credits"""
        user_id = sample_user_profile["user_id"]
        
        # Mock repository - user with no credits
        no_credits_profile = {**sample_user_profile, "credits_remaining": 0}
        user_service.user_repository.get_user_profile.return_value = no_credits_profile
        user_service.gmail_repository.get_connection_info.return_value = {
            "connection_status": "connected"
        }
        
        result = await user_service.get_bot_status(user_id)
        
        assert result["status"] == "no_credits"
        assert result["credits_remaining"] == 0
    
    @pytest.mark.asyncio
    async def test_update_processing_frequency_success(self, user_service, sample_user_profile):
        """Test updating processing frequency"""
        user_id = sample_user_profile["user_id"]
        new_frequency = "1h"
        
        # Mock repository
        user_service.user_repository.get_user_profile.return_value = sample_user_profile
        updated_profile = {**sample_user_profile, "processing_frequency": new_frequency}
        user_service.user_repository.update_user_profile.return_value = updated_profile
        
        result = await user_service.update_processing_frequency(user_id, new_frequency)
        
        assert result["success"] == True
        assert result["processing_frequency"] == new_frequency
    
    @pytest.mark.asyncio
    async def test_update_processing_frequency_invalid(self, user_service, sample_user_profile):
        """Test updating to invalid frequency"""
        user_id = sample_user_profile["user_id"]
        invalid_frequency = "5min"  # Not in valid list
        
        # Mock repository
        user_service.user_repository.get_user_profile.return_value = sample_user_profile
        
        with pytest.raises(ValidationError) as exc_info:
            await user_service.update_processing_frequency(user_id, invalid_frequency)
        
        assert "invalid frequency" in str(exc_info.value).lower()
    
    # --- Dashboard Data Tests ---
    
    @pytest.mark.asyncio
    async def test_get_dashboard_data_success(self, user_service, sample_user_profile):
        """Test getting dashboard data"""
        user_id = sample_user_profile["user_id"]
        
        # Mock all repositories
        user_service.user_repository.get_user_profile.return_value = sample_user_profile
        user_service.gmail_repository.get_connection_info.return_value = {
            "connection_status": "connected",
            "email_address": "grandma@example.com"
        }
        user_service.email_repository.get_processing_stats.return_value = {
            "total_processed": 50,
            "total_successful": 48,
            "success_rate": 0.96
        }
        user_service.billing_repository.get_transactions_for_user = AsyncMock(return_value=[
            {"transaction_type": "purchase", "credit_amount": 100}
        ])
        
        result = await user_service.get_dashboard_data(user_id)
        
        assert result["user_id"] == user_id
        assert result["user_profile"]["display_name"] == "Grandma Smith"
        assert result["bot_status"]["status"] == "active"
        assert result["credits"]["remaining"] == 25
        assert result["email_stats"]["total_processed"] == 50
        assert result["email_stats"]["success_rate"] == 0.96
        assert result["timestamp"] is not None
    
    @pytest.mark.asyncio
    async def test_get_user_statistics_success(self, user_service, sample_user_profile):
        """Test getting user statistics"""
        user_id = sample_user_profile["user_id"]
        
        # Mock repository
        user_service.user_repository.get_user_profile.return_value = sample_user_profile
        user_service.email_repository.get_processing_stats.return_value = {
            "total_processed": 75,
            "total_successful": 70,
            "total_failed": 5,
            "success_rate": 0.93,
            "total_credits_used": 75
        }
        
        result = await user_service.get_user_statistics(user_id)
        
        assert result["user_id"] == user_id
        assert result["total_emails_processed"] == 75
        assert result["successful_emails"] == 70
        assert result["failed_emails"] == 5
        assert result["success_rate"] == 0.93
        assert result["credits_used"] == 75
    
    # --- Lifecycle Tests ---
    
    @pytest.mark.asyncio
    async def test_suspend_user_success(self, user_service, sample_user_profile):
        """Test suspending user"""
        user_id = sample_user_profile["user_id"]
        reason = "Spam complaints"
        
        # Mock repository
        user_service.user_repository.get_user_profile.return_value = sample_user_profile
        suspended_profile = {
            **sample_user_profile,
            "status": "suspended",
            "bot_enabled": False,
            "suspension_reason": reason
        }
        user_service.user_repository.update_user_profile.return_value = suspended_profile
        
        result = await user_service.suspend_user(user_id, reason)
        
        assert result["success"] == True
        assert result["status"] == "suspended"
        assert result["reason"] == reason
    
    @pytest.mark.asyncio
    async def test_reactivate_user_success(self, user_service, sample_user_profile):
        """Test reactivating user"""
        user_id = sample_user_profile["user_id"]
        
        # Mock repository
        user_service.user_repository.get_user_profile.return_value = sample_user_profile
        reactivated_profile = {
            **sample_user_profile,
            "status": "active",
            "suspension_reason": None
        }
        user_service.user_repository.update_user_profile.return_value = reactivated_profile
        
        result = await user_service.reactivate_user(user_id)
        
        assert result["success"] == True
        assert result["status"] == "active"
    
    # --- Edge Cases and Error Handling ---
    
    @pytest.mark.asyncio
    async def test_get_user_profile_empty_id(self, user_service):
        """Test getting user profile with empty ID"""
        with pytest.raises(ValidationError) as exc_info:
            await user_service.get_user_profile("")
        
        assert "user_id cannot be empty" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_update_readonly_field(self, user_service, sample_user_profile):
        """Test updating readonly field"""
        user_id = sample_user_profile["user_id"]
        
        # Mock repository
        user_service.user_repository.get_user_profile.return_value = sample_user_profile
        
        with pytest.raises(ValidationError) as exc_info:
            await user_service.update_user_profile(user_id, {"user_id": "new_id"})
        
        assert "readonly field" in str(exc_info.value).lower()
    
    @pytest.mark.asyncio
    async def test_invalid_email_filter(self, user_service, sample_user_profile):
        """Test invalid email filter"""
        user_id = sample_user_profile["user_id"]
        invalid_filters = {
            "min_email_length": -10  # Invalid negative value
        }
        
        # Mock repository
        user_service.user_repository.get_user_profile.return_value = sample_user_profile
        
        with pytest.raises(ValidationError) as exc_info:
            await user_service.update_email_filters(user_id, invalid_filters)
        
        assert "min_email_length" in str(exc_info.value).lower()
    
    @pytest.mark.asyncio
    async def test_invalid_ai_preference(self, user_service, sample_user_profile):
        """Test invalid AI preference"""
        user_id = sample_user_profile["user_id"]
        invalid_preferences = {
            "summary_style": "invalid_style"  # Not in valid list
        }
        
        # Mock repository
        user_service.user_repository.get_user_profile.return_value = sample_user_profile
        
        with pytest.raises(ValidationError) as exc_info:
            await user_service.update_ai_preferences(user_id, invalid_preferences)
        
        assert "invalid summary_style" in str(exc_info.value).lower()