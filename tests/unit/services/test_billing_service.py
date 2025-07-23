import pytest
import asyncio
from uuid import uuid4, UUID
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import stripe
from stripe import error as stripe_error

from app.services.billing_service import BillingService, StripeGateway
from app.data.repositories.user_repository import UserRepository
from app.data.repositories.billing_repository import BillingRepository
from app.data.repositories.audit_repository import AuditRepository
from app.core.exceptions import ValidationError, NotFoundError, APIError, AuthenticationError
from app.config import settings


@pytest.fixture(autouse=True)
def enable_stripe():
    # Ensure Stripe is enabled for tests
    settings.enable_stripe = True
    yield
    settings.enable_stripe = True


@pytest.fixture
def mock_user_repo():
    return MagicMock(spec=UserRepository)


@pytest.fixture
def mock_billing_repo():
    return AsyncMock(spec=BillingRepository)


@pytest.fixture
def mock_audit_repo():
    return AsyncMock(spec=AuditRepository)


@pytest.fixture
def mock_gateway():
    return MagicMock(spec=StripeGateway)


@pytest.fixture
def service(mock_user_repo, mock_billing_repo, mock_audit_repo, mock_gateway):
    return BillingService(
        user_repository=mock_user_repo,
        billing_repository=mock_billing_repo,
        audit_repository=mock_audit_repo,
        stripe_gateway=mock_gateway
    )


def test_get_credit_packages(service):
    packs = service.get_credit_packages()
    assert isinstance(packs, dict)
    assert "starter" in packs and "pro" in packs and "enterprise" in packs


def test_get_billing_status(service):
    settings.enable_stripe = True
    status = service.get_billing_status()
    assert status == {"stripe_enabled": True, "status": "healthy"}
    settings.enable_stripe = False
    status = service.get_billing_status()
    assert status == {"stripe_enabled": False, "status": "disabled"}


@pytest.mark.asyncio
async def test_create_checkout_session_existing_customer(service, mock_user_repo, mock_audit_repo):
    user_id = uuid4()
    pkg = service.credit_packages['starter']
    # Existing stripe_customer_id
    mock_user_repo.get_user_profile.return_value = {"stripe_customer_id": "cus_123", "email": "a@b.com", "credits_remaining": 0}
    fake_session = MagicMock(id="sess_1", url="http://checkout")
    service.gateway.create_checkout_session.return_value = fake_session

    res = await service.create_checkout_session(user_id, 'starter')

    service.gateway.create_customer.assert_not_called()
    service.gateway.create_checkout_session.assert_called_once()
    mock_user_repo.update_user_profile.assert_not_called()
    mock_audit_repo.log_event.assert_awaited_once_with(str(user_id), 'checkout_session_created', {'session_id': 'sess_1'})
    assert res == {'session_id': 'sess_1', 'checkout_url': 'http://checkout'}


@pytest.mark.asyncio
async def test_create_checkout_session_new_customer(service, mock_user_repo, mock_audit_repo):
    user_id = uuid4()
    # No stripe_customer_id
    mock_user_repo.get_user_profile.return_value = {"stripe_customer_id": None, "email": "a@b.com", "credits_remaining": 0}
    fake_customer = MagicMock(id="cus_new")
    fake_session = MagicMock(id="sess_2", url="http://checkout2")
    service.gateway.create_customer.return_value = fake_customer
    service.gateway.create_checkout_session.return_value = fake_session

    res = await service.create_checkout_session(user_id, 'pro')

    service.gateway.create_customer.assert_called_once()
    mock_user_repo.update_user_profile.assert_called_once_with(str(user_id), {'stripe_customer_id': 'cus_new'})
    # Check that audit log was called twice with the expected calls
    assert mock_audit_repo.log_event.await_count == 2
    calls = mock_audit_repo.log_event.await_args_list
    assert (str(user_id), 'stripe_customer_created', {'customer_id': 'cus_new'}) in [call[0] for call in calls]
    assert (str(user_id), 'checkout_session_created', {'session_id': 'sess_2'}) in [call[0] for call in calls]
    assert res['session_id'] == 'sess_2'


@pytest.mark.asyncio
async def test_create_checkout_session_invalid_package(service):
    with pytest.raises(ValidationError):
        await service.create_checkout_session(uuid4(), 'invalid')


@pytest.mark.asyncio
async def test_create_checkout_session_disabled(service):
    settings.enable_stripe = False
    with pytest.raises(APIError):
        await service.create_checkout_session(uuid4(), 'starter')
    settings.enable_stripe = True


@pytest.mark.asyncio
async def test_handle_webhook_checkout_processed(service, mock_billing_repo, mock_user_repo, mock_audit_repo):
    user_id = uuid4()
    ref_id = str(uuid4())
    metadata = {'user_id': str(user_id), 'credits': '10'}
    event = {'type': 'checkout.session.completed', 'data': {'object': {'id': ref_id, 'amount_total': 1000, 'metadata': metadata}}}
    service.gateway.construct_event.return_value = event
    mock_billing_repo.find_transaction_by_reference.return_value = None
    mock_user_repo.get_user_profile.return_value = {'stripe_customer_id': 'x', 'credits_remaining': 5}

    res = await service.handle_webhook('p', 's')

    mock_billing_repo.find_transaction_by_reference.assert_awaited_once_with(UUID(ref_id))
    mock_billing_repo.create_credit_purchase_transaction.assert_awaited_once()
    mock_user_repo.add_credits.assert_called_once_with(str(user_id), 10, "Stripe purchase")
    mock_audit_repo.log_event.assert_awaited_once_with(str(user_id), 'purchase_completed', {'reference_id': ref_id})
    assert res == {'status': 'processed', 'event_type': 'checkout.session.completed'}


@pytest.mark.asyncio
async def test_handle_webhook_idempotent(service, mock_billing_repo):
    ref_id = str(uuid4())
    metadata = {'user_id': str(uuid4()), 'credits': '5'}
    event = {'type': 'checkout.session.completed', 'data': {'object': {'id': ref_id, 'metadata': metadata}}}
    service.gateway.construct_event = MagicMock(return_value=event)
    mock_billing_repo.find_transaction_by_reference.return_value = {'id': 't'}

    res = await service.handle_webhook('p', 's')
    assert res['status'] == 'already_processed'


@pytest.mark.asyncio
async def test_handle_webhook_invalid_signature(service):
    service.gateway.construct_event.side_effect = AuthenticationError('bad sig')
    with pytest.raises(AuthenticationError):
        await service.handle_webhook('p', 's')


@pytest.mark.asyncio
async def test_create_portal_session_success(service, mock_user_repo, mock_audit_repo):
    user_id = uuid4()
    mock_user_repo.get_user_profile.return_value = {'stripe_customer_id': 'cus_portal'}
    fake = MagicMock(url='http://portal')
    service.gateway.create_portal_session.return_value = fake

    res = await service.create_portal_session(user_id)
    service.gateway.create_portal_session.assert_called_once()
    mock_audit_repo.log_event.assert_awaited_once_with(str(user_id), 'portal_session_created', {})
    assert res == {'portal_url': 'http://portal'}


@pytest.mark.asyncio
async def test_create_portal_session_not_found(service, mock_user_repo):
    user_id = uuid4()
    mock_user_repo.get_user_profile.return_value = None
    with pytest.raises(NotFoundError):
        await service.create_portal_session(user_id)


@pytest.mark.asyncio
async def test_get_user_billing_history(service, mock_billing_repo):
    user_id = uuid4()
    mock_billing_repo.get_transactions_for_user.return_value = [{'id': 't1'}]
    res = await service.get_user_billing_history(user_id)
    mock_billing_repo.get_transactions_for_user.assert_awaited_once_with(user_id=user_id, limit=50)
    assert res == [{'id': 't1'}]


@pytest.mark.asyncio
async def test_add_promotional_credits(service, mock_user_repo, mock_billing_repo, mock_audit_repo):
    user_id = uuid4()
    mock_user_repo.get_user_profile.return_value = {'credits_remaining': 5}
    txn = {'transaction_type': 'bonus', 'credit_amount': 20}
    mock_billing_repo.add_credits.return_value = txn
    mock_user_repo.add_credits.return_value = None

    res = await service.add_promotional_credits(user_id, 20, 'promo')
    mock_billing_repo.add_credits.assert_awaited_once()
    mock_user_repo.add_credits.assert_called_once_with(str(user_id), 20, 'promo')
    mock_audit_repo.log_event.assert_awaited_once_with(str(user_id), 'promotional_credits_added', {'credits': 20})
    assert res == txn


@pytest.mark.asyncio
async def test_add_promotional_credits_invalid(service):
    with pytest.raises(ValidationError):
        await service.add_promotional_credits(uuid4(), 0, 'promo')


@pytest.mark.asyncio
async def test_deduct_manual_credits(service, mock_user_repo, mock_billing_repo, mock_audit_repo):
    user_id = uuid4()
    mock_user_repo.get_user_profile.return_value = {'credits_remaining': 50}
    txn = {'transaction_type': 'adjustment', 'credit_amount': -10}
    mock_billing_repo.deduct_credits.return_value = txn
    mock_user_repo.deduct_credits.return_value = None

    res = await service.deduct_manual_credits(user_id, 10, 'adj')
    mock_billing_repo.deduct_credits.assert_awaited_once()
    mock_user_repo.deduct_credits.assert_called_once_with(str(user_id), 10, 'adj')
    mock_audit_repo.log_event.assert_awaited_once_with(str(user_id), 'manual_credits_deducted', {'credits': 10})
    assert res == txn


@pytest.mark.asyncio
async def test_deduct_manual_credits_insufficient(service, mock_user_repo):
    user_id = uuid4()
    mock_user_repo.get_user_profile.return_value = {'credits_remaining': 5}
    with pytest.raises(ValidationError):
        await service.deduct_manual_credits(user_id, 10, 'adj')


@pytest.mark.asyncio
async def test_handle_webhook_other_event(service, mock_billing_repo):
    event = {'type': 'customer.created', 'data': {'object': {}}}
    service.gateway.construct_event = MagicMock(return_value=event)
    res = await service.handle_webhook('p', 's')
    assert res == {'status': 'ignored', 'event_type': 'customer.created'}
