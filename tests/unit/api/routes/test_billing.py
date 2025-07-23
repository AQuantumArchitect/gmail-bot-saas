# tests/unit/api/routes/test_billing.py
"""
Unit tests for the billing API routes.
"""
import pytest
from uuid import uuid4
from unittest.mock import patch, AsyncMock, MagicMock

from fastapi import FastAPI
from starlette.testclient import TestClient

# The router we are testing
from app.api.routes.billing import router as billing_router
# Dependencies we may need to override
from app.api.dependencies import UserContext, get_user_context, no_auth_required, require_credit_purchase_permission
# The module where services are instantiated, so we can patch them
from app.api.routes import billing as billing_module


@pytest.fixture(autouse=True)
def override_settings():
    """
    Patches the settings object for all tests in this module.
    This runs automatically for every test and prevents AttributeErrors
    during test collection when the billing_module is imported.
    """
    mock_settings = MagicMock()
    mock_settings.enable_stripe = True
    mock_settings.stripe_secret_key = "sk_test_123"
    # This is the crucial attribute that was missing
    mock_settings.stripe_webhook_secret = "whsec_test_123"
    
    with patch.object(billing_module, "settings", mock_settings):
        yield


@pytest.fixture
def client():
    """Fixture to create a test client with the billing router."""
    app = FastAPI()
    app.include_router(billing_router)

    # Override the no_auth_required dependency for consistency
    def override_no_auth():
        return True
    app.dependency_overrides[no_auth_required] = override_no_auth
    
    return TestClient(app)


@pytest.fixture
def mock_user_context():
    """Fixture to create a mock UserContext for authenticated endpoints."""
    return UserContext(
        user_data={
            "user_id": str(uuid4()),
            "email": "test@example.com",
            "credits_remaining": 100,
        },
        permissions={"can_purchase_credits": True}
    )


@pytest.mark.asyncio
class TestBillingPackageEndpoints:
    """Tests for the GET /billing/packages endpoints."""

    @pytest.fixture
    def sample_packages(self):
        """Provides a sample of the raw package data."""
        return {
            "starter": {"name": "Starter Pack", "credits": 100, "price_cents": 500},
            "pro": {"name": "Pro Pack", "credits": 500, "price_cents": 2000},
        }

    def test_get_credit_packages_success(self, client, sample_packages):
        """
        Test the successful retrieval and formatting of credit packages.
        """
        with patch.object(billing_module, "billing_service", new=MagicMock()) as mock_billing_service:
            mock_billing_service.get_credit_packages.return_value = sample_packages

            response = client.get("/billing/packages")

            assert response.status_code == 200
            response_data = response.json()
            assert response_data["billing_enabled"] is True
            assert len(response_data["packages"]) == 2
            pro_package = next(p for p in response_data["packages"] if p["key"] == "pro")
            assert pro_package["savings_percent"] == 20.0

    def test_get_package_details_success(self, client, sample_packages):
        """
        Test retrieving details for a single, specific package.
        """
        with patch.object(billing_module, "billing_service", new=MagicMock()) as mock_billing_service:
            mock_billing_service.get_credit_packages.return_value = sample_packages
            response = client.get("/billing/packages/starter")
            assert response.status_code == 200
            assert response.json()["key"] == "starter"

    def test_get_package_details_not_found(self, client, sample_packages):
        """
        Test requesting a package key that does not exist.
        """
        with patch.object(billing_module, "billing_service", new=MagicMock()) as mock_billing_service:
            mock_billing_service.get_credit_packages.return_value = sample_packages
            response = client.get("/billing/packages/nonexistent")
            assert response.status_code == 404


@pytest.mark.asyncio
class TestBillingBalanceAndHistory:
    """Tests for the /balance and /history endpoints."""

    def test_get_credit_balance_success(self, client, mock_user_context):
        """Test successful retrieval of a user's credit balance."""
        # --- Arrange ---
        with patch.object(billing_module, "user_service", spec=True) as mock_user_service:
            mock_user_service.get_credit_balance = AsyncMock(return_value={
                "credits_remaining": 123,
                "last_updated": "2025-07-18T12:00:00Z"
            })
            
            # Override dependency for this test
            async def override_get_user_context():
                return mock_user_context
            client.app.dependency_overrides[get_user_context] = override_get_user_context

            # --- Act ---
            response = client.get("/billing/balance")

            # --- Assert ---
            mock_user_service.get_credit_balance.assert_awaited_once_with(mock_user_context.user_id)
            assert response.status_code == 200
            response_data = response.json()
            assert response_data["user_id"] == mock_user_context.user_id
            assert response_data["credits_remaining"] == 123

        client.app.dependency_overrides = {}

    def test_get_billing_history_success(self, client, mock_user_context):
        """Test successful retrieval of a user's billing history."""
        # --- Arrange ---
        with patch.object(billing_module, "user_service", spec=True) as mock_user_service:
            mock_user_service.get_credit_history = AsyncMock(return_value={
                "transactions": [
                    {"id": "txn_1", "transaction_type": "purchase", "credit_amount": 100, "credit_balance_after": 100, "description": "Stripe credit purchase", "created_at": "2025-07-18T10:00:00Z"},
                    {"id": "txn_2", "transaction_type": "usage", "credit_amount": -5, "credit_balance_after": 95, "description": "Email processing", "created_at": "2025-07-18T11:00:00Z"},
                ],
                "total_transactions": 2
            })

            async def override_get_user_context():
                return mock_user_context
            client.app.dependency_overrides[get_user_context] = override_get_user_context

            # --- Act ---
            response = client.get("/billing/history")

            # --- Assert ---
            mock_user_service.get_credit_history.assert_awaited_once_with(mock_user_context.user_id, limit=50)
            assert response.status_code == 200
            response_data = response.json()
            assert response_data["user_id"] == mock_user_context.user_id
            assert len(response_data["transactions"]) == 2
            assert response_data["total_purchased"] == 100
            assert response_data["total_used"] == 5
            assert response_data["current_balance"] == mock_user_context.credits_remaining

        client.app.dependency_overrides = {}


@pytest.mark.asyncio
class TestPurchaseEndpoints:
    """Tests for the /create-checkout and /webhook endpoints."""

    def test_create_checkout_session_success(self, client, mock_user_context):
        """Test the successful creation of a Stripe checkout session."""
        # --- Arrange ---
        with patch.object(billing_module, "billing_service", spec=True) as mock_billing_service:
            # Mock the sync method with a direct return value
            mock_billing_service.get_credit_packages.return_value = {
                "pro": {"name": "Pro Pack", "credits": 500, "price_cents": 2000}
            }
            # Mock the async method by replacing it with an AsyncMock
            mock_billing_service.create_checkout_session = AsyncMock(return_value={
                "session_id": "cs_test_123",
                "checkout_url": "https://checkout.stripe.com/pay/cs_test_123"
            })

            async def override_purchase_permission():
                return mock_user_context
            client.app.dependency_overrides[require_credit_purchase_permission] = override_purchase_permission
            
            # --- Act ---
            payload = {"package_key": "pro", "user_email": mock_user_context.email}
            response = client.post("/billing/create-checkout", json=payload)

            # --- Assert ---
            mock_billing_service.create_checkout_session.assert_awaited_once_with(
                user_id=mock_user_context.user_id,
                package_key="pro"
            )
            assert response.status_code == 200
            response_data = response.json()
            assert response_data["success"] is True
            assert response_data["session_id"] == "cs_test_123"
            assert response_data["package_info"]["key"] == "pro"

        client.app.dependency_overrides = {}

    def test_stripe_webhook_success(self, client):
        """Test the successful processing of a Stripe webhook."""
        # --- Arrange ---
        with patch.object(billing_module, "billing_service", spec=True) as mock_billing_service:
            mock_billing_service.handle_webhook = AsyncMock(return_value={
                "event_type": "checkout.session.completed",
                "status": "processed"
            })
            
            # --- Act ---
            # The content and signature don't matter here as the service is mocked
            response = client.post("/billing/webhook", content="{}", headers={"stripe-signature": "t=123,v1=abc"})

            # --- Assert ---
            mock_billing_service.handle_webhook.assert_awaited_once()
            assert response.status_code == 200
            response_data = response.json()
            assert response_data["success"] is True
            assert response_data["status"] == "processed"

        client.app.dependency_overrides = {}


@pytest.mark.asyncio
class TestAdminAndHealthEndpoints:
    """Tests for the admin and health check endpoints."""

    def test_add_promotional_credits_success(self, client, mock_user_context):
        """Test adding promotional credits to a user's own account."""
        # --- Arrange ---
        with patch.object(billing_module, "billing_service", new=AsyncMock()) as mock_billing_service:
            mock_billing_service.add_promotional_credits.return_value = {
                "id": "txn_promo_123",
                "credit_balance_after": 150
            }

            async def override_get_user_context():
                return mock_user_context
            client.app.dependency_overrides[get_user_context] = override_get_user_context

            # --- Act ---
            payload = {"user_id": mock_user_context.user_id, "credits": 50, "note": "Welcome bonus"}
            response = client.post("/billing/add-credits", params=payload)

            # --- Assert ---
            mock_billing_service.add_promotional_credits.assert_awaited_once_with(
                user_id=mock_user_context.user_id,
                credits=50,
                note="Welcome bonus"
            )
            assert response.status_code == 200
            response_data = response.json()
            assert response_data["success"] is True
            assert response_data["credits_added"] == 50
            assert response_data["new_balance"] == 150

        client.app.dependency_overrides = {}

    def test_add_promotional_credits_forbidden(self, client, mock_user_context):
        """Test that a user cannot add credits to another user's account."""
        # --- Arrange ---
        async def override_get_user_context():
            return mock_user_context
        client.app.dependency_overrides[get_user_context] = override_get_user_context

        # --- Act ---
        another_user_id = str(uuid4())
        payload = {"user_id": another_user_id, "credits": 50}
        response = client.post("/billing/add-credits", params=payload)

        # --- Assert ---
        assert response.status_code == 403
        assert "your own account" in response.json()["detail"]

    def test_get_billing_status_success(self, client):
        """Test retrieving the overall billing system status."""
        # --- Arrange ---
        with patch.object(billing_module, "billing_service", new=MagicMock()) as mock_billing_service:
            mock_billing_service.get_billing_status.return_value = {"stripe_enabled": True, "status": "healthy"}
            mock_billing_service.get_credit_packages.return_value = {"starter": {}, "pro": {}}

            # --- Act ---
            response = client.get("/billing/status")

            # --- Assert ---
            assert response.status_code == 200
            response_data = response.json()
            assert response_data["status"] == "healthy"
            assert response_data["available_packages"] == 2
    
    def test_billing_health_check_success(self, client):
        """Test the billing health check endpoint."""
        # --- Arrange ---
        with patch.object(billing_module, "billing_service", new=MagicMock()) as mock_billing_service:
            mock_billing_service.get_billing_status.return_value = {"stripe_enabled": True, "status": "healthy"}
            mock_billing_service.get_credit_packages.return_value = {"starter": {}, "pro": {}}

            # --- Act ---
            response = client.get("/billing/health")

            # --- Assert ---
            assert response.status_code == 200
            response_data = response.json()
            assert response_data["status"] == "healthy"
            assert response_data["packages_available"] == 2

        client.app.dependency_overrides = {}


@pytest.mark.asyncio
class TestPortalEndpoint:
    """Tests for the GET /billing/portal endpoint."""

    def test_create_customer_portal_session_success(self, client, mock_user_context):
        """Test the successful creation of a Stripe customer portal session."""
        # --- Arrange ---
        with patch.object(billing_module, "billing_service", new=AsyncMock()) as mock_billing_service:
            mock_billing_service.create_portal_session.return_value = {
                "portal_url": "https://billing.stripe.com/p/session/123"
            }

            async def override_get_user_context():
                return mock_user_context
            client.app.dependency_overrides[get_user_context] = override_get_user_context

            # --- Act ---
            response = client.get("/billing/portal")

            # --- Assert ---
            mock_billing_service.create_portal_session.assert_awaited_once_with(mock_user_context.user_id)
            assert response.status_code == 200
            response_data = response.json()
            assert response_data["success"] is True
            assert response_data["portal_url"] == "https://billing.stripe.com/p/session/123"

        client.app.dependency_overrides = {}

    def test_create_customer_portal_session_disabled(self, client, mock_user_context):
        """Test that the endpoint returns an error when Stripe is disabled."""
        # --- Arrange ---
        # We need to override the autouse fixture for this one test
        mock_settings = MagicMock()
        mock_settings.enable_stripe = False # Disable Stripe

        with patch.object(billing_module, "settings", mock_settings):
            async def override_get_user_context():
                return mock_user_context
            client.app.dependency_overrides[get_user_context] = override_get_user_context

            # --- Act ---
            response = client.get("/billing/portal")

            # --- Assert ---
            assert response.status_code == 503 # Service Unavailable
            assert "disabled" in response.json()["detail"]

        client.app.dependency_overrides = {}
