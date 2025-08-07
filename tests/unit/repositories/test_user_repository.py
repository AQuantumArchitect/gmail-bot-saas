import pytest
from uuid import uuid4, UUID
from datetime import datetime, timedelta
from typing import Any, Dict, List

# Import the repository and its domain models
from app.data.repositories.user_repository import UserRepository, UserSettings

# Import ALL exceptions from the central, single source of truth
from app.core.exceptions import (
    UserProfileNotFoundError,
    UserProfileExistsError,
    InvalidTimezoneError,
    ValidationError
)


# --- Test Constants ---
USER_ID = str(uuid4())
OTHER_USER_ID = str(uuid4())

# --- Pytest Fixtures ---

@pytest.fixture
def user_repo() -> UserRepository:
    """
    Provides a fresh instance of the UserRepository for each test.
    It uses in-memory storage, perfect for isolated unit testing.
    """
    return UserRepository()

@pytest.fixture
def sample_user_settings_data() -> dict:
    """Provides a reusable dictionary of valid user settings data."""
    return {
        "user_id": USER_ID,
        "email": "test.user@example.com",
        "display_name": "Test User",
        "timezone": "UTC",
        "bot_enabled": True,
        "processing_frequency_minutes": 60,
        "last_processed_at": None,
        "email_filters": {"exclude_senders": ["spam@test.com"]},
        "ai_preferences": {"summary_style": "concise", "include_action_items": True},
    }

@pytest.fixture
def multiple_user_settings_data(sample_user_settings_data: dict) -> List[dict]:
    """Provides a list of user settings for testing list operations."""
    profile1 = sample_user_settings_data.copy()
    profile2 = {
        **sample_user_settings_data,
        "user_id": OTHER_USER_ID,
        "email": "another.user@test.com",
        "bot_enabled": False,
        "timezone": "US/Pacific",
        "processing_frequency_minutes": 120,
    }
    profile3 = {
        **sample_user_settings_data,
        "user_id": str(uuid4()),
        "email": "test.user@otherdomain.com",
        "bot_enabled": True,
        "timezone": "UTC",
        "processing_frequency_minutes": 30,
    }
    return [profile1, profile2, profile3]

### Core CRUD Tests ###

@pytest.mark.asyncio
async def test_create_user_settings_success(user_repo: UserRepository, sample_user_settings_data: dict):
    settings = await user_repo.create_user_settings(sample_user_settings_data)
    assert isinstance(settings, UserSettings)
    assert settings.user_id == UUID(USER_ID)
    # Verify it was actually stored
    stored_settings = await user_repo.get_user_settings(UUID(USER_ID))
    assert stored_settings is not None
    assert stored_settings.email == "test.user@example.com"
    assert stored_settings.processing_frequency_minutes == 60

@pytest.mark.asyncio
async def test_create_user_settings_already_exists(user_repo: UserRepository, sample_user_settings_data: dict):
    await user_repo.create_user_settings(sample_user_settings_data) # Create the first time
    with pytest.raises(UserProfileExistsError):
        await user_repo.create_user_settings(sample_user_settings_data) # Attempt to create again

@pytest.mark.asyncio
async def test_get_user_settings_found(user_repo: UserRepository, sample_user_settings_data: dict):
    await user_repo.create_user_settings(sample_user_settings_data)
    settings = await user_repo.get_user_settings(UUID(USER_ID))
    assert settings is not None
    assert settings.user_id == UUID(USER_ID)

@pytest.mark.asyncio
async def test_get_user_settings_not_found(user_repo: UserRepository):
    settings = await user_repo.get_user_settings(uuid4())
    assert settings is None

@pytest.mark.asyncio
async def test_update_user_settings(user_repo: UserRepository, sample_user_settings_data: dict):
    await user_repo.create_user_settings(sample_user_settings_data)
    updates = {"display_name": "Updated Name", "bot_enabled": False, "processing_frequency_minutes": 90}
    updated_settings = await user_repo.update_user_settings(UUID(USER_ID), updates)
    assert updated_settings.display_name == "Updated Name"
    assert updated_settings.bot_enabled is False
    assert updated_settings.processing_frequency_minutes == 90
    # Verify the change persisted
    stored_settings = await user_repo.get_user_settings(UUID(USER_ID))
    assert stored_settings.display_name == "Updated Name"

@pytest.mark.asyncio
async def test_delete_user_settings(user_repo: UserRepository, sample_user_settings_data: dict):
    await user_repo.create_user_settings(sample_user_settings_data)
    success = await user_repo.delete_user_settings(UUID(USER_ID))
    assert success is True
    assert await user_repo.get_user_settings(UUID(USER_ID)) is None

### Listing, Pagination, and Sorting Tests ###

@pytest.mark.asyncio
async def test_list_user_settings(user_repo: UserRepository, multiple_user_settings_data: list):
    await user_repo.create_bulk_user_settings(multiple_user_settings_data)
    settings_list = await user_repo.list_user_settings()
    assert len(settings_list) == 3

@pytest.mark.asyncio
async def test_list_user_settings_with_filters(user_repo: UserRepository, multiple_user_settings_data: list):
    await user_repo.create_bulk_user_settings(multiple_user_settings_data)
    filters = {"bot_enabled": True, "timezone": "UTC"}
    settings_list = await user_repo.list_user_settings(filters=filters)
    assert len(settings_list) == 2
    assert all(s.bot_enabled and s.timezone == "UTC" for s in settings_list)

@pytest.mark.asyncio
async def test_list_user_settings_filter_by_email_domain(user_repo: UserRepository, multiple_user_settings_data: list):
    """[NEW] Test filtering by email domain."""
    await user_repo.create_bulk_user_settings(multiple_user_settings_data)
    # From the fixture, only one user has a 'test.com' domain
    profiles = await user_repo.list_user_settings(filters={"email_domain": "test.com"})
    assert len(profiles) == 1
    assert profiles[0].email == "another.user@test.com"

@pytest.mark.asyncio
async def test_list_user_settings_pagination(user_repo: UserRepository, multiple_user_settings_data: list):
    await user_repo.create_bulk_user_settings(multiple_user_settings_data)
    # Get the second user (offset=1, limit=1)
    settings_list = await user_repo.list_user_settings(limit=1, offset=1, order_by="email")
    assert len(settings_list) == 1
    # Sort original data by email to find the expected second item
    all_settings = sorted(multiple_user_settings_data, key=lambda p: p['email'])
    assert settings_list[0].email == all_settings[1]['email']

@pytest.mark.asyncio
async def test_list_user_settings_sorting(user_repo: UserRepository, multiple_user_settings_data: list):
    await user_repo.create_bulk_user_settings(multiple_user_settings_data)
    # Sort by processing frequency, descending
    settings_list = await user_repo.list_user_settings(order_by="processing_frequency_minutes", descending=True)
    assert len(settings_list) == 3
    assert settings_list[0].processing_frequency_minutes == 120
    assert settings_list[1].processing_frequency_minutes == 60
    assert settings_list[2].processing_frequency_minutes == 30

@pytest.mark.asyncio
async def test_count_user_settings(user_repo: UserRepository, multiple_user_settings_data: list):
    await user_repo.create_bulk_user_settings(multiple_user_settings_data)
    count = await user_repo.count_user_settings()
    assert count == 3

@pytest.mark.asyncio
async def test_count_user_settings_with_filters(user_repo: UserRepository, multiple_user_settings_data: list):
    """[NEW] Test counting with filters applied."""
    await user_repo.create_bulk_user_settings(multiple_user_settings_data)
    # From the fixture, 2 users have bot_enabled: True
    count = await user_repo.count_user_settings(filters={"bot_enabled": True})
    assert count == 2

### Finder Method Tests ###

@pytest.mark.asyncio
async def test_find_user_by_email(user_repo: UserRepository, sample_user_settings_data: dict):
    await user_repo.create_user_settings(sample_user_settings_data)
    other_data = {**sample_user_settings_data, "user_id": str(uuid4()), "email": "another@example.com"}
    await user_repo.create_user_settings(other_data)
    
    found_settings = await user_repo.find_user_by_email("test.user@example.com")
    assert found_settings is not None
    assert found_settings.user_id == UUID(USER_ID)

@pytest.mark.asyncio
async def test_find_active_users(user_repo: UserRepository, multiple_user_settings_data: list):
    await user_repo.create_bulk_user_settings(multiple_user_settings_data)
    # Expect 2 active users, as defined by `bot_enabled: True`
    active_users = await user_repo.find_active_users()
    assert len(active_users) == 2
    user_ids = {u.user_id for u in active_users}
    assert UUID(USER_ID) in user_ids
    assert UUID(OTHER_USER_ID) not in user_ids

@pytest.mark.asyncio
async def test_find_users_due_for_processing(user_repo: UserRepository, sample_user_settings_data: dict):
    now = datetime.utcnow()
    user1_data = sample_user_settings_data.copy() # Due: last_processed_at is None
    user2_data = {**sample_user_settings_data, "user_id": str(uuid4()), "email": "u2@e.com", "bot_enabled": True, "processing_frequency_minutes": 30, "last_processed_at": now - timedelta(minutes=45)} # Due: time has passed
    user3_data = {**sample_user_settings_data, "user_id": str(uuid4()), "email": "u3@e.com", "bot_enabled": True, "processing_frequency_minutes": 60, "last_processed_at": now - timedelta(minutes=30)} # Not due
    user4_data = {**sample_user_settings_data, "user_id": str(uuid4()), "email": "u4@e.com", "bot_enabled": False, "last_processed_at": None} # Not due: bot disabled

    await user_repo.create_bulk_user_settings([user1_data, user2_data, user3_data, user4_data])
    
    due_users = await user_repo.find_users_due_for_processing()
    
    assert len(due_users) == 2
    due_user_ids = {u.user_id for u in due_users}
    assert UUID(user1_data['user_id']) in due_user_ids
    assert UUID(user2_data['user_id']) in due_user_ids

### Convenience Method & Validation Tests ###

@pytest.mark.asyncio
async def test_enable_disable_bot(user_repo: UserRepository, sample_user_settings_data: dict):
    sample_user_settings_data['bot_enabled'] = False
    await user_repo.create_user_settings(sample_user_settings_data)
    
    enabled_settings = await user_repo.enable_bot(UUID(USER_ID))
    assert enabled_settings.bot_enabled is True
    
    disabled_settings = await user_repo.disable_bot(UUID(USER_ID))
    assert disabled_settings.bot_enabled is False

@pytest.mark.asyncio
async def test_update_last_processed(user_repo: UserRepository, sample_user_settings_data: dict):
    await user_repo.create_user_settings(sample_user_settings_data)
    
    settings1 = await user_repo.update_last_processed(UUID(USER_ID))
    assert settings1.last_processed_at is not None
    assert isinstance(settings1.last_processed_at, datetime)
    
    past_time = datetime.utcnow() - timedelta(days=1)
    settings2 = await user_repo.update_last_processed(UUID(USER_ID), processed_at=past_time)
    assert settings2.last_processed_at == past_time

### Bulk Operation Tests ###

@pytest.mark.asyncio
async def test_create_bulk_settings_partial_failure(user_repo: UserRepository, sample_user_settings_data: dict):
    valid_user_2 = sample_user_settings_data.copy()
    valid_user_2["user_id"] = str(uuid4())
    valid_user_2["email"] = "another@test.com"
    
    users_to_create = [ sample_user_settings_data, sample_user_settings_data, valid_user_2 ]
    
    created_settings = await user_repo.create_bulk_user_settings(users_to_create)
    assert len(created_settings) == 2
    
    total_settings = await user_repo.list_user_settings()
    assert len(total_settings) == 2

### Error Condition & Advanced Validation Tests ###

@pytest.mark.asyncio
async def test_delete_user_settings_not_found(user_repo: UserRepository):
    """[NEW] Test deleting a user that does not exist."""
    success = await user_repo.delete_user_settings(uuid4())
    assert success is False

@pytest.mark.asyncio
async def test_create_settings_invalid_timezone(user_repo: UserRepository):
    with pytest.raises(InvalidTimezoneError):
        await user_repo.create_user_settings({"user_id": str(uuid4()), "email": "a@b.com", "timezone": "Mars/Olympus_Mons"})

@pytest.mark.asyncio
@pytest.mark.parametrize("freq", [5, 250, "sixty"])
async def test_update_settings_invalid_frequency(user_repo: UserRepository, sample_user_settings_data: dict, freq: Any):
    await user_repo.create_user_settings(sample_user_settings_data)
    with pytest.raises(ValidationError, match="processing_frequency_minutes must be between 15 and 240"):
        await user_repo.update_user_settings(UUID(USER_ID), {"processing_frequency_minutes": freq})

@pytest.mark.asyncio
@pytest.mark.parametrize("pref_key, pref_value", [("summary_style", "witty"), ("language", "klingon")])
async def test_create_settings_invalid_ai_prefs(user_repo: UserRepository, pref_key: str, pref_value: str):
    with pytest.raises(ValidationError):
        await user_repo.create_user_settings({"user_id": str(uuid4()), "email": "a@b.com", "ai_preferences": {pref_key: pref_value}})

@pytest.mark.asyncio
async def test_update_settings_not_found(user_repo: UserRepository):
    with pytest.raises(UserProfileNotFoundError):
        await user_repo.update_user_settings(uuid4(), {"display_name": "Ghost"})

@pytest.mark.asyncio
async def test_create_user_settings_missing_id(user_repo: UserRepository):
    with pytest.raises(ValidationError, match="user_id is required"):
        await user_repo.create_user_settings({"email": "test@test.com"})

@pytest.mark.asyncio
async def test_update_settings_nested_object_replaces_not_merges(user_repo: UserRepository, sample_user_settings_data: dict):
    """[NEW] Test that updating a nested object replaces it entirely, not merges."""
    settings = await user_repo.create_user_settings(sample_user_settings_data)
    assert settings.ai_preferences.summary_style == "concise"
    assert settings.ai_preferences.include_action_items is True

    updates = {"ai_preferences": {"language": "fr"}}
    updated_settings = await user_repo.update_user_settings(settings.user_id, updates)

    assert updated_settings.ai_preferences.language == "fr"
    # Verify other keys were reset to their defaults, proving replacement.
    # The default for summary_style is 'concise', which matches the original.
    # The default for include_action_items is True.
    assert updated_settings.ai_preferences.summary_style == "concise"
    assert updated_settings.ai_preferences.include_action_items is True

### Analytics and Health Tests ###

@pytest.mark.asyncio
async def test_get_user_statistics(user_repo: UserRepository, multiple_user_settings_data: list):
    await user_repo.create_bulk_user_settings(multiple_user_settings_data)
    stats = await user_repo.get_user_statistics()
    
    assert stats.total_users == 3
    assert stats.active_users == 2
    assert stats.inactive_users == 1
    assert stats.average_processing_frequency == round((60+120+30)/3, 2)
    assert stats.timezone_distribution == {"UTC": 2, "US/Pacific": 1}
    assert stats.email_domain_distribution == {"example.com": 1, "test.com": 1, "otherdomain.com": 1}

@pytest.mark.asyncio
async def test_get_user_statistics_on_empty_repo(user_repo: UserRepository):
    """[NEW] Test statistics on an empty repository."""
    stats = await user_repo.get_user_statistics()
    assert stats.total_users == 0
    assert stats.active_users == 0
    assert stats.inactive_users == 0
    assert stats.average_processing_frequency == 0.0
    assert stats.timezone_distribution == {}
    assert stats.email_domain_distribution == {}

@pytest.mark.asyncio
async def test_health_check_in_memory(user_repo: UserRepository, sample_user_settings_data: dict):
    await user_repo.create_user_settings(sample_user_settings_data)    
    health = await user_repo.health_check()
    assert health["healthy"] is True
    assert health["storage_type"] == "in_memory"
    assert health["total_settings"] == 1
    assert "timestamp" in health
