import pytest
import os
from uuid import UUID, uuid4
from typing import AsyncGenerator, Dict, Any

# Ensure environment variables are loaded for local testing
from dotenv import load_dotenv
# Load variables from .env.test for integration testing
load_dotenv(dotenv_path=".env.test")

# Admin client is still needed for auth actions outside the app's client
from supabase import create_client, Client as AdminClient

# Import the repository and its components
from app.data.repositories.user_repository import UserRepository, UserProfileNotFoundError
from app.external.supabase_client import get_supabase_client, close_supabase_client

# --- Test Configuration ---

pytestmark = pytest.mark.integration

# Use dedicated test environment variables
SUPABASE_URL = os.environ.get("TEST_SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.environ.get("TEST_SUPABASE_SERVICE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    pytest.skip("Test Supabase credentials not found in .env.test, skipping integration tests.", allow_module_level=True)


# --- Pytest Fixtures ---

@pytest.fixture(scope="module")
def supabase_admin_client() -> AdminClient:
    """Provides a Supabase admin client with the service role key for user management."""
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

@pytest.fixture
async def prod_repo() -> AsyncGenerator[UserRepository, None]:
    """
    Provides a fresh instance of the UserRepository connected to the LIVE database.
    This now uses the singleton from your refactored client.
    """
    # Get the singleton client instance for the repository
    repo_client = get_supabase_client()
    yield UserRepository(supabase_client=repo_client)
    # Clean up the client connection after tests are done
    await close_supabase_client()

@pytest.fixture
async def live_test_user(supabase_admin_client: AdminClient) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Creates a temporary user in `auth.users` for the test.
    Guarantees cleanup by deleting the user afterward.
    """
    test_email = f"test-user-{uuid4()}@example.com"
    test_password = "password123"
    user_id_str = None
    
    try:
        # 1. Create the user using the ADMIN method to bypass email confirmation and rate limits
        response = supabase_admin_client.auth.admin.create_user({
            "email": test_email,
            "password": test_password,
            "email_confirm": True, # Instantly confirm the user, making them active.
        })
        
        assert response.user is not None, "Failed to create live test user in Supabase Auth."
        user_id_str = response.user.id
        
        # 2. Yield control to the test
        yield {"user_id": UUID(user_id_str), "email": test_email}
    
    finally:
        # 3. Cleanup: This code runs AFTER the test finishes, even if it fails
        if user_id_str:
            try:
                supabase_admin_client.auth.admin.delete_user(user_id_str)
                print(f"\nSuccessfully cleaned up live test user: {user_id_str}")
            except Exception as e:
                print(f"\nCRITICAL: Failed to clean up live test user {user_id_str}. Manual cleanup required. Error: {e}")


# --- Live Integration Tests ---

@pytest.mark.asyncio
async def test_live_crud_lifecycle(prod_repo: AsyncGenerator[UserRepository, None], live_test_user: AsyncGenerator[Dict[str, Any], None]):
    """
    Tests the full Create, Read, Update, Delete lifecycle on the live database.
    This single test verifies the most critical repository functions.
    
    FIX: This test now correctly consumes the async generator fixtures.
    """
    # Correctly consume the yielded values from the async generator fixtures
    async for repo in prod_repo:
        async for user_details in live_test_user:
            user_id = user_details["user_id"]
            email = user_details["email"]
            
            # 1. CREATE
            print(f"\n[CREATE] Creating settings for live user: {user_id}")
            create_data = {
                "user_id": str(user_id),
                "display_name": "Live Test User",
                "timezone": "US/Pacific",
                "bot_enabled": True,
                "processing_frequency_minutes": 30,
            }
            created_settings = await repo.create_user_settings(create_data)
            
            assert created_settings is not None
            assert created_settings.user_id == user_id
            assert created_settings.email == email
            assert created_settings.display_name == "Live Test User"
            
            # 2. READ
            print(f"[READ] Fetching settings for live user: {user_id}")
            fetched_settings = await repo.get_user_settings(user_id)
            
            assert fetched_settings is not None
            assert fetched_settings.user_id == user_id
            assert fetched_settings.timezone == "US/Pacific"
            
            # 3. UPDATE
            print(f"[UPDATE] Updating settings for live user: {user_id}")
            updates = {"timezone": "Europe/London", "bot_enabled": False}
            updated_settings = await repo.update_user_settings(user_id, updates)
            
            assert updated_settings.timezone == "Europe/London"
            assert updated_settings.bot_enabled is False
            
            # Verify the update persisted
            refetched_settings = await repo.get_user_settings(user_id)
            assert refetched_settings is not None
            assert refetched_settings.timezone == "Europe/London"
            
            # 4. DELETE
            print(f"[DELETE] Deleting settings for live user: {user_id}")
            delete_success = await repo.delete_user_settings(user_id)
            assert delete_success is True
            
            # Verify deletion
            with pytest.raises(UserProfileNotFoundError):
                await repo.update_user_settings(user_id, {"display_name": "Should Fail"})
            print("[SUCCESS] Live CRUD lifecycle completed successfully.")

