# tests/unit/repositories/test_user_repository.py
"""
Test-first driver for UserRepository implementation.
These tests define the interface and behavior before the repository exists.
"""
import pytest
from uuid import uuid4
from datetime import datetime
from app.data.repositories.user_repository import UserRepository
from app.data.database import ValidationError, NotFoundError

class TestUserRepository:
    """Test-driven development for UserRepository"""
    
    @pytest.fixture
    def user_repo(self):
        """Create UserRepository instance - this doesn't exist yet!"""
        return UserRepository()
    
    def test_create_user_with_minimal_data(self, user_repo):
        """Test creating user with only required fields"""
        user_data = {
            "auth_id": "auth-123e4567-e89b-12d3-a456-426614174000",
            "email": "john@example.com"
        }
        
        result = user_repo.create_user(user_data)
        
        # Should return the created user with defaults
        assert result["auth_id"] == "auth-123e4567-e89b-12d3-a456-426614174000"
        assert result["email"] == "john@example.com"
        assert result["credits_remaining"] == 100  # Default starter credits
        assert result["bot_enabled"] == False      # Default disabled
        assert result["processing_frequency"] == "daily"  # Default frequency
        assert "id" in result                      # Should have UUID
        assert "created_at" in result             # Should have timestamp
    
    def test_create_user_with_full_data(self, user_repo):
        """Test creating user with all optional fields"""
        user_data = {
            "auth_id": "auth-456",
            "email": "jane@example.com",
            "full_name": "Jane Doe",
            "credits_remaining": 500,
            "bot_enabled": True,
            "processing_frequency": "hourly",
            "timezone": "America/New_York",
            "metadata": {"plan": "premium", "source": "referral"}
        }
        
        result = user_repo.create_user(user_data)
        
        assert result["full_name"] == "Jane Doe"
        assert result["credits_remaining"] == 500
        assert result["bot_enabled"] == True
        assert result["processing_frequency"] == "hourly"
        assert result["timezone"] == "America/New_York"
        assert result["metadata"]["plan"] == "premium"
    
    def test_create_user_invalid_email(self, user_repo):
        """Test creating user with invalid email"""
        user_data = {
            "auth_id": "auth-789",
            "email": "invalid-email"
        }
        
        with pytest.raises(ValidationError) as exc_info:
            user_repo.create_user(user_data)
        
        assert "email" in str(exc_info.value).lower()
    
    def test_create_user_missing_required_fields(self, user_repo):
        """Test creating user without required fields"""
        user_data = {"email": "test@example.com"}  # Missing auth_id
        
        with pytest.raises(ValidationError) as exc_info:
            user_repo.create_user(user_data)
        
        assert "auth_id" in str(exc_info.value).lower()
    
    def test_create_user_duplicate_email(self, user_repo):
        """Test creating user with duplicate email"""
        user_data = {
            "auth_id": "auth-111",
            "email": "duplicate@example.com"
        }
        
        # First creation should succeed
        user_repo.create_user(user_data)
        
        # Second creation should fail
        duplicate_data = {
            "auth_id": "auth-222",
            "email": "duplicate@example.com"
        }
        
        with pytest.raises(ValidationError) as exc_info:
            user_repo.create_user(duplicate_data)
        
        assert "email already exists" in str(exc_info.value).lower()
    
    def test_get_by_auth_id_success(self, user_repo):
        """Test getting user by auth ID"""
        # Create user first
        user_data = {
            "auth_id": "auth-get-test",
            "email": "get@example.com",
            "full_name": "Get Test"
        }
        created_user = user_repo.create_user(user_data)
        
        # Get by auth_id
        result = user_repo.get_by_auth_id("auth-get-test")
        
        assert result["id"] == created_user["id"]
        assert result["auth_id"] == "auth-get-test"
        assert result["email"] == "get@example.com"
        assert result["full_name"] == "Get Test"
    
    def test_get_by_auth_id_not_found(self, user_repo):
        """Test getting user by non-existent auth ID"""
        result = user_repo.get_by_auth_id("nonexistent-auth-id")
        assert result is None
    
    def test_get_by_email_success(self, user_repo):
        """Test getting user by email"""
        # Create user first
        user_data = {
            "auth_id": "auth-email-test",
            "email": "email@example.com"
        }
        created_user = user_repo.create_user(user_data)
        
        # Get by email
        result = user_repo.get_by_email("email@example.com")
        
        assert result["id"] == created_user["id"]
        assert result["email"] == "email@example.com"
    
    def test_get_by_email_not_found(self, user_repo):
        """Test getting user by non-existent email"""
        result = user_repo.get_by_email("nonexistent@example.com")
        assert result is None
    
    def test_update_credits_success(self, user_repo):
        """Test updating user credits"""
        # Create user first
        user_data = {
            "auth_id": "auth-credits-test",
            "email": "credits@example.com",
            "credits_remaining": 100
        }
        created_user = user_repo.create_user(user_data)
        
        # Update credits
        success = user_repo.update_credits(created_user["id"], 50)
        assert success == True
        
        # Verify update
        updated_user = user_repo.get_by_auth_id("auth-credits-test")
        assert updated_user["credits_remaining"] == 150
    
    def test_update_credits_insufficient_balance(self, user_repo):
        """Test updating credits with insufficient balance"""
        # Create user with low balance
        user_data = {
            "auth_id": "auth-insufficient",
            "email": "insufficient@example.com",
            "credits_remaining": 10
        }
        created_user = user_repo.create_user(user_data)
        
        # Try to deduct more than available
        with pytest.raises(ValidationError) as exc_info:
            user_repo.update_credits(created_user["id"], -50)
        
        assert "insufficient credits" in str(exc_info.value).lower()
    
    def test_update_credits_prevents_negative_balance(self, user_repo):
        """Test that credits cannot go below zero"""
        # Create user
        user_data = {
            "auth_id": "auth-negative",
            "email": "negative@example.com",
            "credits_remaining": 30
        }
        created_user = user_repo.create_user(user_data)
        
        # Try to deduct exactly the balance (should work)
        success = user_repo.update_credits(created_user["id"], -30)
        assert success == True
        
        # Verify balance is now 0
        user = user_repo.get_by_auth_id("auth-negative")
        assert user["credits_remaining"] == 0
        
        # Try to deduct from zero balance (should fail)
        with pytest.raises(ValidationError):
            user_repo.update_credits(created_user["id"], -1)
    
    def test_set_bot_status(self, user_repo):
        """Test enabling/disabling bot"""
        # Create user with bot disabled
        user_data = {
            "auth_id": "auth-bot-test",
            "email": "bot@example.com",
            "bot_enabled": False
        }
        created_user = user_repo.create_user(user_data)
        
        # Enable bot
        success = user_repo.set_bot_status(created_user["id"], True)
        assert success == True
        
        # Verify bot is enabled
        updated_user = user_repo.get_by_auth_id("auth-bot-test")
        assert updated_user["bot_enabled"] == True
        
        # Disable bot
        success = user_repo.set_bot_status(created_user["id"], False)
        assert success == True
        
        # Verify bot is disabled
        updated_user = user_repo.get_by_auth_id("auth-bot-test")
        assert updated_user["bot_enabled"] == False
    
    def test_update_processing_frequency(self, user_repo):
        """Test updating processing frequency"""
        # Create user
        user_data = {
            "auth_id": "auth-freq-test",
            "email": "freq@example.com",
            "processing_frequency": "daily"
        }
        created_user = user_repo.create_user(user_data)
        
        # Update frequency
        success = user_repo.update_processing_frequency(created_user["id"], "hourly")
        assert success == True
        
        # Verify update
        updated_user = user_repo.get_by_auth_id("auth-freq-test")
        assert updated_user["processing_frequency"] == "hourly"
    
    def test_update_processing_frequency_invalid(self, user_repo):
        """Test updating processing frequency with invalid value"""
        # Create user
        user_data = {
            "auth_id": "auth-invalid-freq",
            "email": "invalid@example.com"
        }
        created_user = user_repo.create_user(user_data)
        
        # Try invalid frequency
        with pytest.raises(ValidationError) as exc_info:
            user_repo.update_processing_frequency(created_user["id"], "invalid")
        
        assert "invalid frequency" in str(exc_info.value).lower()
    
    def test_get_user_stats(self, user_repo):
        """Test getting user statistics"""
        # Create user
        user_data = {
            "auth_id": "auth-stats-test",
            "email": "stats@example.com",
            "credits_remaining": 75
        }
        created_user = user_repo.create_user(user_data)
        
        # Get stats
        stats = user_repo.get_user_stats(created_user["id"])
        
        # Should return comprehensive stats
        assert stats["user_id"] == created_user["id"]
        assert stats["credits_remaining"] == 75
        assert "emails_processed" in stats
        assert "last_activity" in stats
        assert "bot_enabled" in stats
        assert "processing_frequency" in stats
    
    def test_get_users_by_processing_frequency(self, user_repo):
        """Test getting users by processing frequency"""
        # Create users with different frequencies
        user_repo.create_user({
            "auth_id": "auth-hourly-1",
            "email": "hourly1@example.com",
            "processing_frequency": "hourly",
            "bot_enabled": True
        })
        
        user_repo.create_user({
            "auth_id": "auth-hourly-2",
            "email": "hourly2@example.com",
            "processing_frequency": "hourly",
            "bot_enabled": True
        })
        
        user_repo.create_user({
            "auth_id": "auth-daily-1",
            "email": "daily1@example.com",
            "processing_frequency": "daily",
            "bot_enabled": True
        })
        
        # Get hourly users
        hourly_users = user_repo.get_users_by_processing_frequency("hourly")
        
        assert len(hourly_users) == 2
        assert all(user["processing_frequency"] == "hourly" for user in hourly_users)
        assert all(user["bot_enabled"] == True for user in hourly_users)
    
    def test_get_users_needing_processing(self, user_repo):
        """Test getting users who need email processing"""
        # Create users with different last_processed times
        user_repo.create_user({
            "auth_id": "auth-needs-processing-1",
            "email": "needs1@example.com",
            "bot_enabled": True,
            "processing_frequency": "hourly",
            "credits_remaining": 50
        })
        
        user_repo.create_user({
            "auth_id": "auth-needs-processing-2",
            "email": "needs2@example.com",
            "bot_enabled": True,
            "processing_frequency": "daily",
            "credits_remaining": 25
        })
        
        user_repo.create_user({
            "auth_id": "auth-no-credits",
            "email": "nocredits@example.com",
            "bot_enabled": True,
            "processing_frequency": "hourly",
            "credits_remaining": 0  # No credits
        })
        
        user_repo.create_user({
            "auth_id": "auth-bot-disabled",
            "email": "disabled@example.com",
            "bot_enabled": False,  # Bot disabled
            "processing_frequency": "hourly",
            "credits_remaining": 100
        })
        
        # Get users needing processing
        users = user_repo.get_users_needing_processing()
        
        # Should only return users with credits and bot enabled
        assert len(users) == 2
        assert all(user["credits_remaining"] > 0 for user in users)
        assert all(user["bot_enabled"] == True for user in users)
    
    def test_update_user_profile(self, user_repo):
        """Test updating user profile information"""
        # Create user
        user_data = {
            "auth_id": "auth-profile-test",
            "email": "profile@example.com",
            "full_name": "Original Name"
        }
        created_user = user_repo.create_user(user_data)
        
        # Update profile
        updates = {
            "full_name": "Updated Name",
            "timezone": "America/Los_Angeles",
            "metadata": {"preference": "dark_mode"}
        }
        
        updated_user = user_repo.update_user_profile(created_user["id"], updates)
        
        assert updated_user["full_name"] == "Updated Name"
        assert updated_user["timezone"] == "America/Los_Angeles"
        assert updated_user["metadata"]["preference"] == "dark_mode"
        assert "updated_at" in updated_user
    
    def test_update_user_profile_readonly_fields(self, user_repo):
        """Test that readonly fields cannot be updated"""
        # Create user
        user_data = {
            "auth_id": "auth-readonly-test",
            "email": "readonly@example.com"
        }
        created_user = user_repo.create_user(user_data)
        
        # Try to update readonly fields
        invalid_updates = {
            "auth_id": "different-auth-id",
            "email": "different@example.com",
            "id": "different-id",
            "created_at": "2020-01-01T00:00:00Z"
        }
        
        with pytest.raises(ValidationError) as exc_info:
            user_repo.update_user_profile(created_user["id"], invalid_updates)
        
        assert "readonly field" in str(exc_info.value).lower()
    
    def test_delete_user(self, user_repo):
        """Test deleting a user"""
        # Create user
        user_data = {
            "auth_id": "auth-delete-test",
            "email": "delete@example.com"
        }
        created_user = user_repo.create_user(user_data)
        
        # Delete user
        success = user_repo.delete_user(created_user["id"])
        assert success == True
        
        # Verify user is deleted
        deleted_user = user_repo.get_by_auth_id("auth-delete-test")
        assert deleted_user is None
    
    def test_delete_nonexistent_user(self, user_repo):
        """Test deleting non-existent user"""
        # Try to delete non-existent user
        success = user_repo.delete_user(uuid4())
        assert success == False
    
    @pytest.mark.parametrize("frequency", ["hourly", "daily", "weekly"])
    def test_valid_processing_frequencies(self, user_repo, frequency):
        """Test all valid processing frequencies"""
        user_data = {
            "auth_id": f"auth-{frequency}-test",
            "email": f"{frequency}@example.com",
            "processing_frequency": frequency
        }
        
        result = user_repo.create_user(user_data)
        assert result["processing_frequency"] == frequency
    
    @pytest.mark.parametrize("invalid_frequency", ["minutely", "monthly", "yearly", ""])
    def test_invalid_processing_frequencies(self, user_repo, invalid_frequency):
        """Test invalid processing frequencies"""
        user_data = {
            "auth_id": "auth-invalid-freq-test",
            "email": "invalid@example.com",
            "processing_frequency": invalid_frequency
        }
        
        with pytest.raises(ValidationError):
            user_repo.create_user(user_data)
    
    def test_user_count(self, user_repo):
        """Test counting users"""
        initial_count = user_repo.count()
        
        # Create some users
        user_repo.create_user({
            "auth_id": "auth-count-1",
            "email": "count1@example.com"
        })
        
        user_repo.create_user({
            "auth_id": "auth-count-2",
            "email": "count2@example.com"
        })
        
        final_count = user_repo.count()
        assert final_count == initial_count + 2
    
    def test_user_exists(self, user_repo):
        """Test checking if user exists"""
        # Create user
        user_data = {
            "auth_id": "auth-exists-test",
            "email": "exists@example.com"
        }
        created_user = user_repo.create_user(user_data)
        
        # Check exists
        assert user_repo.exists(created_user["id"]) == True
        assert user_repo.exists(uuid4()) == False
    
    def test_list_users(self, user_repo):
        """Test listing users with pagination"""
        # Create multiple users
        for i in range(5):
            user_repo.create_user({
                "auth_id": f"auth-list-{i}",
                "email": f"list{i}@example.com"
            })
        
        # List first 3 users
        users = user_repo.list(limit=3)
        assert len(users) <= 3
        
        # List with offset
        users_offset = user_repo.list(limit=3, offset=2)
        assert len(users_offset) <= 3
    
    def test_search_users(self, user_repo):
        """Test searching users"""
        # Create users with searchable data
        user_repo.create_user({
            "auth_id": "auth-search-1",
            "email": "john.doe@example.com",
            "full_name": "John Doe"
        })
        
        user_repo.create_user({
            "auth_id": "auth-search-2",
            "email": "jane.smith@example.com",
            "full_name": "Jane Smith"
        })
        
        # Search by email
        results = user_repo.search("john.doe@example.com")
        assert len(results) == 1
        assert results[0]["email"] == "john.doe@example.com"
        
        # Search by name
        results = user_repo.search("Jane")
        assert len(results) == 1
        assert results[0]["full_name"] == "Jane Smith"