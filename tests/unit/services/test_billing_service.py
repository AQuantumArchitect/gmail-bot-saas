import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4
from datetime import datetime

# Import classes to be tested, mocked, and used in tests
from app.services.billing_service import BillingService, InvalidPackageError, PaymentProcessingError, WebhookValidationError
from app.data.repositories.billing_repository import BillingRepository
from app.data.repositories.user_repository import UserRepository
from app.external.stripe_client import StripeClient
from app.models.billing import CreditBalance, TransactionRecord, CheckoutSession, WebhookEvent, BillingHistory
from app.core.config import settings, CreditPackage
from app.core.exceptions import NotFoundError, InsufficientCreditsError, ValidationError, ConfigurationError

# --- Fixtures ---

@pytest.fixture
def mock_billing_repo() -> MagicMock:
    """Provides a mock BillingRepository with async methods."""
    mock = MagicMock(spec=BillingRepository)
    mock.create_transaction = AsyncMock()
    mock.list_transactions_for_user = AsyncMock()
    mock.get_transaction_by_id = AsyncMock()
    mock.find_transaction_by_reference = AsyncMock()
    mock.get_user_transaction_summary = AsyncMock()
    return mock

@pytest.fixture
def mock_user_repo() -> MagicMock:
    """Provides a mock UserRepository."""
    mock = MagicMock(spec=UserRepository)
    mock.get_user_profile = MagicMock()
    mock.update_user_profile = MagicMock()
    mock.update_credits = MagicMock()
    return mock

@pytest.fixture
def test_user_id() -> UUID:
    """Provides a consistent UUID for a test user."""
    return uuid4()

# --- Test Classes ---

class TestBillingServiceInitialization:
    """Tests for the initialization of the BillingService."""

    def test_initialization_success_stripe_disabled(self, mock_billing_repo, mock_user_repo):
        """Test that the service initializes correctly with Stripe disabled."""
        with patch('app.services.billing_service.settings.enable_stripe', False):
            service = BillingService(billing_repo=mock_billing_repo, user_repo=mock_user_repo)
            assert service.billing_repo is mock_billing_repo
            assert service.user_repo is mock_user_repo
            assert service.stripe_client is None

    def test_initialization_with_stripe_enabled_and_key(self, mock_billing_repo, mock_user_repo):
        """Test that the Stripe client is created when Stripe is enabled and a key is present."""
        with patch('app.services.billing_service.settings.enable_stripe', True), \
             patch('app.services.billing_service.settings.stripe_secret_key', 'sk_test_123'), \
             patch('app.services.billing_service.StripeClient') as MockStripe:
            
            service = BillingService(billing_repo=mock_billing_repo, user_repo=mock_user_repo)
            assert service.stripe_client is not None
            MockStripe.assert_called_once_with(secret_key='sk_test_123', webhook_secret=settings.stripe_webhook_secret)

    def test_initialization_with_stripe_enabled_no_key_raises_error(self, mock_billing_repo, mock_user_repo):
        """Test that a ConfigurationError is raised if Stripe is enabled without a secret key."""
        with patch('app.services.billing_service.settings.enable_stripe', True), \
             patch('app.services.billing_service.settings.stripe_secret_key', None):
            
            with pytest.raises(ConfigurationError, match="Stripe secret key required"):
                BillingService(billing_repo=mock_billing_repo, user_repo=mock_user_repo)

@pytest.mark.asyncio
class TestCreditBalanceOperations:
    """Tests for credit balance methods in BillingService."""

    async def test_get_credit_balance_success(self, mock_billing_repo, mock_user_repo, test_user_id):
        mock_user_repo.get_user_profile.return_value = {"user_id": str(test_user_id), "credits_remaining": 100}
        service = BillingService(billing_repo=mock_billing_repo, user_repo=mock_user_repo)
        
        balance = await service.get_credit_balance(test_user_id)
        
        assert isinstance(balance, CreditBalance)
        assert balance.user_id == test_user_id
        assert balance.credits_remaining == 100

    async def test_get_credit_balance_user_not_found(self, mock_billing_repo, mock_user_repo, test_user_id):
        mock_user_repo.get_user_profile.return_value = None
        service = BillingService(billing_repo=mock_billing_repo, user_repo=mock_user_repo)
        
        with pytest.raises(NotFoundError):
            await service.get_credit_balance(test_user_id)

    async def test_check_credit_sufficiency_true(self, mock_billing_repo, mock_user_repo, test_user_id):
        mock_user_repo.get_user_profile.return_value = {"user_id": str(test_user_id), "credits_remaining": 50}
        service = BillingService(billing_repo=mock_billing_repo, user_repo=mock_user_repo)
        
        has_enough = await service.check_credit_sufficiency(test_user_id, 20)
        assert has_enough is True

@pytest.mark.asyncio
class TestCreditTransactions:
    """Tests for adding and deducting credits."""

    async def test_deduct_credits_success(self, mock_billing_repo, mock_user_repo, test_user_id):
        initial_balance = 100
        mock_user_repo.get_user_profile.return_value = {"user_id": str(test_user_id), "credits_remaining": initial_balance}
        service = BillingService(billing_repo=mock_billing_repo, user_repo=mock_user_repo)

        await service.deduct_credits(user_id=test_user_id, credit_amount=10, description="Test usage")

        mock_user_repo.update_credits.assert_called_once_with(str(test_user_id), 90)
        mock_billing_repo.create_transaction.assert_awaited_once()

    async def test_deduct_credits_insufficient_funds(self, mock_billing_repo, mock_user_repo, test_user_id):
        mock_user_repo.get_user_profile.return_value = {"user_id": str(test_user_id), "credits_remaining": 5}
        service = BillingService(billing_repo=mock_billing_repo, user_repo=mock_user_repo)

        with pytest.raises(InsufficientCreditsError):
            await service.deduct_credits(test_user_id, 10, "Test usage")

    async def test_deduct_credits_invalid_amount(self, mock_billing_repo, mock_user_repo, test_user_id):
        service = BillingService(billing_repo=mock_billing_repo, user_repo=mock_user_repo)
        with pytest.raises(ValidationError, match="Credit amount must be positive"):
            await service.deduct_credits(test_user_id, 0, "Invalid amount")

    async def test_add_credits_success(self, mock_billing_repo, mock_user_repo, test_user_id):
        initial_balance = 50
        mock_user_repo.get_user_profile.return_value = {"user_id": str(test_user_id), "credits_remaining": initial_balance}
        service = BillingService(billing_repo=mock_billing_repo, user_repo=mock_user_repo)

        await service.add_credits(user_id=test_user_id, credit_amount=100, description="Test purchase")

        mock_user_repo.update_credits.assert_called_once_with(str(test_user_id), 150)
        mock_billing_repo.create_transaction.assert_awaited_once()

@pytest.mark.asyncio
@patch('app.services.billing_service.settings.enable_stripe', True)
@patch('app.services.billing_service.settings.stripe_secret_key', 'sk_test_123')
@patch('app.services.billing_service.StripeClient')
class TestPaymentProcessing:
    """Tests for payment processing, from checkout to fulfillment."""

    async def test_create_checkout_session_success(self, MockStripe, mock_billing_repo, mock_user_repo, test_user_id):
        mock_user_repo.get_user_profile.return_value = {"user_id": str(test_user_id), "email": "test@example.com", "stripe_customer_id": "cus_123"}
        mock_stripe_instance = MockStripe.return_value
        mock_stripe_instance.create_checkout_session = AsyncMock(return_value={"id": "cs_test_123", "url": "http://test.com"})
        service = BillingService(billing_repo=mock_billing_repo, user_repo=mock_user_repo)
        
        session = await service.create_checkout_session(test_user_id, 'pro')

        assert isinstance(session, CheckoutSession)
        mock_stripe_instance.create_checkout_session.assert_awaited_once()

    async def test_create_checkout_session_user_not_found(self, MockStripe, mock_billing_repo, mock_user_repo, test_user_id):
        mock_user_repo.get_user_profile.return_value = None
        service = BillingService(billing_repo=mock_billing_repo, user_repo=mock_user_repo)
        
        with pytest.raises(NotFoundError):
            await service.create_checkout_session(test_user_id, 'pro')

    async def test_handle_payment_success(self, MockStripe, mock_billing_repo, mock_user_repo, test_user_id):
        session_id = "cs_test_123"
        package = settings.get_credit_package_by_key('pro')
        mock_billing_repo.find_transaction_by_reference.return_value = None
        mock_stripe_instance = MockStripe.return_value
        mock_stripe_instance.get_checkout_session = AsyncMock(return_value={"id": session_id, "metadata": {"user_id": str(test_user_id), "package_key": "pro", "credits": str(package.credits)}})
        
        service = BillingService(billing_repo=mock_billing_repo, user_repo=mock_user_repo)
        service.add_credits = AsyncMock()

        await service.handle_payment_success(session_id)

        mock_stripe_instance.get_checkout_session.assert_awaited_once_with(session_id)
        mock_billing_repo.find_transaction_by_reference.assert_awaited_once_with(session_id, "stripe_checkout")
        service.add_credits.assert_awaited_once()

    async def test_handle_payment_success_idempotency(self, MockStripe, mock_billing_repo, mock_user_repo, test_user_id):
        session_id = "cs_test_idempotent_456"
        existing_transaction = MagicMock(spec=TransactionRecord)
        mock_stripe_instance = MockStripe.return_value
        mock_stripe_instance.get_checkout_session = AsyncMock(return_value={"id": session_id, "metadata": {"user_id": str(test_user_id), "package_key": "pro", "credits": "1000"}})
        mock_billing_repo.find_transaction_by_reference.return_value = existing_transaction
        service = BillingService(billing_repo=mock_billing_repo, user_repo=mock_user_repo)
        service.add_credits = AsyncMock()

        result_transaction = await service.handle_payment_success(session_id)

        service.add_credits.assert_not_awaited()
        assert result_transaction is existing_transaction

@pytest.mark.asyncio
@patch('app.services.billing_service.settings.enable_stripe', True)
@patch('app.services.billing_service.settings.stripe_secret_key', 'sk_test_123')
@patch('app.services.billing_service.StripeClient')
class TestWebhookProcessing:
    """Tests for handling incoming Stripe webhooks."""

    async def test_process_stripe_webhook_success(self, MockStripe, mock_billing_repo, mock_user_repo):
        payload = '{"id": "evt_123", "type": "checkout.session.completed", "data": {"object": {"id": "cs_123", "payment_status": "paid"}}}'
        signature = "sig_123"
        mock_stripe_instance = MockStripe.return_value
        mock_stripe_instance.construct_webhook_event.return_value = {"id": "evt_123", "type": "checkout.session.completed", "data": {"object": {"id": "cs_123", "payment_status": "paid"}}}
        service = BillingService(billing_repo=mock_billing_repo, user_repo=mock_user_repo)
        
        mock_transaction = MagicMock(spec=TransactionRecord)
        mock_transaction.id = uuid4()
        mock_transaction.credit_amount = 1000
        service.handle_payment_success = AsyncMock(return_value=mock_transaction)

        event = await service.process_stripe_webhook(payload, signature)

        assert event.success is True
        assert event.event_type == "checkout.session.completed"
        service.handle_payment_success.assert_awaited_once_with("cs_123")

    async def test_process_stripe_webhook_unhandled_event(self, MockStripe, mock_billing_repo, mock_user_repo):
        payload = '{"id": "evt_123", "type": "customer.created", "data": {}}'
        signature = "sig_123"
        mock_stripe_instance = MockStripe.return_value
        mock_stripe_instance.construct_webhook_event.return_value = {"id": "evt_123", "type": "customer.created", "data": {}}
        service = BillingService(billing_repo=mock_billing_repo, user_repo=mock_user_repo)
        service.handle_payment_success = AsyncMock()

        event = await service.process_stripe_webhook(payload, signature)

        assert event.success is False
        assert "unhandled_event_type" in event.result["reason"]
        service.handle_payment_success.assert_not_awaited()

    async def test_process_stripe_webhook_invalid_signature(self, MockStripe, mock_billing_repo, mock_user_repo):
        mock_stripe_instance = MockStripe.return_value
        mock_stripe_instance.construct_webhook_event.side_effect = WebhookValidationError("Invalid signature")
        service = BillingService(billing_repo=mock_billing_repo, user_repo=mock_user_repo)

        with pytest.raises(WebhookValidationError):
            await service.process_stripe_webhook("payload", "bad_sig")

@pytest.mark.asyncio
class TestHistoryAndAnalytics:
    """Tests for retrieving billing history and analytics."""

    async def test_get_billing_history(self, mock_billing_repo, mock_user_repo, test_user_id):
        mock_user_repo.get_user_profile.return_value = {"user_id": str(test_user_id), "credits_remaining": 100}
        mock_transaction = MagicMock(spec=TransactionRecord)
        mock_transaction.transaction_type = 'purchase'
        mock_transaction.credit_amount = 1000
        mock_transaction.usd_amount = 40.0
        mock_transaction.created_at = datetime.utcnow()
        mock_billing_repo.list_transactions_for_user.return_value = [mock_transaction]
        service = BillingService(billing_repo=mock_billing_repo, user_repo=mock_user_repo)

        history = await service.get_billing_history(test_user_id)

        assert isinstance(history, BillingHistory)
        assert len(history.transactions) == 1
        mock_billing_repo.list_transactions_for_user.assert_awaited_once_with(test_user_id, 50)

@pytest.mark.asyncio
class TestAdminFunctions:
    """Tests for administrative billing functions."""

    async def test_create_bonus_credits(self, mock_billing_repo, mock_user_repo, test_user_id):
        service = BillingService(billing_repo=mock_billing_repo, user_repo=mock_user_repo)
        service.add_credits = AsyncMock()

        await service.create_bonus_credits(user_id=test_user_id, credit_amount=500, description="Welcome bonus")

        service.add_credits.assert_awaited_once_with(
            user_id=test_user_id,
            credit_amount=500,
            description="Welcome bonus",
            reference_id=None,
            reference_type="bonus"
        )
