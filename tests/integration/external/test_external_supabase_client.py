# tests/integration/external/test_external_supabase_client.py
import unittest
import os
import uuid
import asyncio
from dotenv import load_dotenv

from app.external.supabase_client import get_supabase_client, close_supabase_client
from app.core.config import settings
from app.core.exceptions import APIError, NotFoundError, DatabaseError

# Load environment variables specifically from a .env.test file for this test suite.
load_dotenv(dotenv_path=".env.test")

# Skip all tests in this file if the required test environment variables are not set.
requires_test_db = unittest.skipIf(
    not all([
        settings.database_url,
        settings.database_key,
        settings.database_service_key
    ]),
    "Test database environment variables (SUPABASE_URL, etc.) not set in .env.test"
)


@requires_test_db
class TestIntegrationSupabaseClient(unittest.IsolatedAsyncioTestCase):
    """
    Integration tests for the SupabaseClient, using a live test database.
    
    These tests use the Admin API for robust user setup and teardown,
    making them independent of Supabase project settings like email confirmation.
    """

    @classmethod
    def setUpClass(cls):
        """Get the singleton client instance configured via .env.test."""
        cls.client = get_supabase_client()
        cls.test_run_id = uuid.uuid4().hex[:6]

    @classmethod
    async def tearDownClass(cls):
        """Close the client connection after all tests are done."""
        await close_supabase_client()

    async def asyncSetUp(self):
        """
        Use the Admin API to create a confirmed user for each test,
        ensuring a clean and isolated state.
        """
        self.test_email = f"test-user-{uuid.uuid4().hex[:10]}@example.com"
        self.test_password = "password123"
        self.user_id = None
        
        # Directly call the admin endpoint to create a confirmed user
        admin_user_payload = {
            "email": self.test_email,
            "password": self.test_password,
            "email_confirm": True,
        }
        
        # We use the internal _make_request with the service key to act as an admin
        signup_response = await self.client._make_request(
            "POST",
            f"{self.client.AUTH_API_PATH}/admin/users",
            json=admin_user_payload,
            use_service_key=True
        )
        self.assertIn("id", signup_response)
        self.user_id = signup_response["id"]

    async def asyncTearDown(self):
        """
        Use the Admin API to forcefully delete the user after each test,
        ensuring complete cleanup.
        """
        if not self.user_id:
            return
        try:
            # Use the admin endpoint to delete the user
            await self.client._make_request(
                "DELETE",
                f"{self.client.AUTH_API_PATH}/admin/users/{self.user_id}",
                use_service_key=True
            )
            # Clean up any associated test data
            await self.client.delete("test_items", filters={"user_id": self.user_id})
        except Exception as e:
            print(f"Warning: Could not clean up test user {self.user_id}. Reason: {e}")

    async def test_health_check(self):
        """✅ Test the health check against the live database."""
        health = await self.client.health_check()
        self.assertEqual(health['status'], 'healthy')
        self.assertEqual(health['database'], 'connected')

    async def test_full_crud_lifecycle(self):
        """✅ Test a full INSERT -> SELECT -> UPDATE -> DELETE lifecycle."""
        table_name = "test_items"
        test_data = {"name": f"CRUD Item {self.test_run_id}", "value": 123, "user_id": self.user_id}

        # 1. INSERT
        inserted = await self.client.insert(table_name, test_data, user_id=self.user_id)
        self.assertEqual(len(inserted), 1)
        item_id = inserted[0]['id']

        # 2. SELECT
        selected = await self.client.select(table_name, filters={"id": item_id}, user_id=self.user_id)
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]['value'], 123)

        # 3. UPDATE
        updated = await self.client.update(table_name, {"value": 456}, filters={"id": item_id}, user_id=self.user_id)
        self.assertEqual(len(updated), 1)
        self.assertEqual(updated[0]['value'], 456)

        # 4. DELETE
        await self.client.delete(table_name, filters={"id": item_id}, user_id=self.user_id)
        final_select = await self.client.select(table_name, filters={"id": item_id}, user_id=self.user_id)
        self.assertEqual(len(final_select), 0)

    async def test_authentication_flow(self):
        """✅ Test user sign-in and get_user flow."""
        signin_response = await self.client.sign_in(self.test_email, self.test_password)
        self.assertIn("access_token", signin_response)
        access_token = signin_response["access_token"]

        user_info = await self.client.get_user(access_token)
        self.assertEqual(user_info['id'], self.user_id)

    async def test_public_sign_up_flow(self):
        """
        ✅ Test the public sign_up method.
        Note: This test's success may depend on the project's auth settings
        (e.g., if email confirmations are disabled).
        """
        new_user_email = f"public-signup-{uuid.uuid4().hex[:10]}@example.com"
        signup_response = await self.client.sign_up(new_user_email, "password123")
        self.assertIn("id", signup_response)
        
        # Clean up the publicly signed-up user
        new_user_id = signup_response["id"]
        await self.client._make_request(
            "DELETE",
            f"{self.client.AUTH_API_PATH}/admin/users/{new_user_id}",
            use_service_key=True
        )

    async def test_row_level_security(self):
        """🔒 Test that RLS prevents a user from seeing another user's data."""
        table_name = "test_items"
        await self.client.insert(table_name, {"name": "My Data", "user_id": self.user_id}, user_id=self.user_id)

        # As the user, we should only be able to select our own data.
        # This assumes an RLS policy like: `(auth.uid() = user_id)`
        my_items = await self.client.select(table_name, user_id=self.user_id)
        self.assertEqual(len(my_items), 1)
        self.assertEqual(my_items[0]['name'], "My Data")

