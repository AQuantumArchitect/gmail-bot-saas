import pytest
import time
import hmac
import hashlib
import json
import asyncio
from unittest.mock import patch, AsyncMock, Mock
import httpx

# Import the client to be tested and its exceptions
from app.external.stripe_client import StripeClient
from app.core.billing_exceptions import WebhookValidationError, StripeError

# Test secrets
TEST_SECRET_KEY = "sk_test_12345"
TEST_WEBHOOK_SECRET = "whsec_test_secret_abcde"


@pytest.fixture
def stripe_client():
    """Provides a fresh instance of the StripeClient for each test."""
    return StripeClient(secret_key=TEST_SECRET_KEY, webhook_secret=TEST_WEBHOOK_SECRET)


class TestStripeClientHelpers:
    """Tests for the synchronous helper methods in the StripeClient."""

    @pytest.mark.parametrize(
        "input_dict, expected_output",
        [
            ({"email": "test@example.com"}, "email=test@example.com"),
            ({"metadata": {"user_id": "usr_123"}}, "metadata[user_id]=usr_123"),
        ]
    )
    def test_encode_form_data(self, stripe_client, input_dict, expected_output):
        encoded_data = stripe_client._encode_form_data(input_dict)
        assert sorted(encoded_data.split('&')) == sorted(expected_output.split('&'))

    def test_construct_webhook_event_success(self, stripe_client):
        payload = '{"id": "evt_123", "object": "event"}'
        timestamp = int(time.time())
        signed_payload = f"{timestamp}.{payload}"
        expected_signature = hmac.new(
            stripe_client.webhook_secret.encode(), signed_payload.encode(), hashlib.sha256
        ).hexdigest()
        signature_header = f"t={timestamp},v1={expected_signature}"
        event = stripe_client.construct_webhook_event(payload, signature_header)
        assert event["id"] == "evt_123"


@pytest.mark.asyncio
class TestStripeClientApi:
    """Tests for the async API methods of the StripeClient."""

    async def test_create_customer_success(self, stripe_client):
        """Tests a successful creation of a Stripe customer."""
        expected_response = {"id": "cus_123", "object": "customer"}
        with patch.object(stripe_client, "_make_request", new_callable=AsyncMock) as mock_make_request:
            mock_make_request.return_value = expected_response
            await stripe_client.create_customer(email="test@example.com")
            mock_make_request.assert_awaited_once()

    async def test_get_customer_success(self, stripe_client):
        """Tests successfully retrieving a customer by their ID."""
        customer_id = "cus_12345"
        expected_response = {"id": customer_id, "object": "customer"}
        with patch.object(stripe_client, "_make_request", new_callable=AsyncMock) as mock_make_request:
            mock_make_request.return_value = expected_response
            await stripe_client.get_customer(customer_id)
            mock_make_request.assert_awaited_once_with("GET", f"/v1/customers/{customer_id}")

    async def test_list_customers_success(self, stripe_client):
        """Tests successfully listing customers."""
        expected_response = {"object": "list", "data": [{"id": "cus_123"}]}
        with patch.object(stripe_client, "_make_request", new_callable=AsyncMock) as mock_make_request:
            mock_make_request.return_value = expected_response
            customers = await stripe_client.list_customers(limit=5)
            assert customers == expected_response
            mock_make_request.assert_awaited_once_with("GET", "/v1/customers", params={"limit": 5})

    async def test_create_checkout_session_success(self, stripe_client):
        """Tests successfully creating a Stripe Checkout Session."""
        session_data = {
            "customer_id": "cus_123", "line_items": [{"price": "price_abc", "quantity": 1}],
            "success_url": "https://example.com/success", "cancel_url": "https://example.com/cancel"
        }
        expected_response = {"id": "cs_test_123", "url": "https://checkout.stripe.com/..."}
        with patch.object(stripe_client, "_make_request", new_callable=AsyncMock) as mock_make_request:
            mock_make_request.return_value = expected_response
            session = await stripe_client.create_checkout_session(**session_data)
            assert session == expected_response
            sent_data = mock_make_request.call_args.kwargs['data']
            assert sent_data['customer'] == session_data['customer_id']

    async def test_expire_checkout_session_success(self, stripe_client):
        """Tests successfully expiring a checkout session."""
        session_id = "cs_test_123"
        expected_response = {"id": session_id, "status": "expired"}
        with patch.object(stripe_client, "_make_request", new_callable=AsyncMock) as mock_make_request:
            mock_make_request.return_value = expected_response
            await stripe_client.expire_checkout_session(session_id)
            mock_make_request.assert_awaited_once_with("POST", f"/v1/checkout/sessions/{session_id}/expire")
            
    async def test_create_billing_portal_session_success(self, stripe_client):
        """Tests successfully creating a customer billing portal session."""
        customer_id = "cus_123"
        return_url = "https://example.com/return"
        expected_response = {"id": "bps_123", "url": "https://billing.stripe.com/..."}
        with patch.object(stripe_client, "_make_request", new_callable=AsyncMock) as mock_make_request:
            mock_make_request.return_value = expected_response
            await stripe_client.create_billing_portal_session(customer_id, return_url)
            mock_make_request.assert_awaited_once_with(
                "POST", "/v1/billing_portal/sessions", data={"customer": customer_id, "return_url": return_url}
            )

    async def test_create_payment_intent_success(self, stripe_client):
        """Tests successfully creating a Payment Intent."""
        expected_response = {"id": "pi_123", "status": "requires_payment_method"}
        with patch.object(stripe_client, "_make_request", new_callable=AsyncMock) as mock_make_request:
            mock_make_request.return_value = expected_response
            await stripe_client.create_payment_intent(amount=2000, currency="usd")
            sent_data = mock_make_request.call_args.kwargs['data']
            assert sent_data['amount'] == 2000

    async def test_get_account_success(self, stripe_client):
        """Tests successfully retrieving account information."""
        expected_response = {"id": "acct_123", "email": "admin@example.com"}
        with patch.object(stripe_client, "_make_request", new_callable=AsyncMock) as mock_make_request:
            mock_make_request.return_value = expected_response
            account = await stripe_client.get_account()
            assert account == expected_response
            mock_make_request.assert_awaited_once_with("GET", "/v1/account")