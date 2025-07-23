import logging
import time
import stripe
from typing import Dict, Any, Optional, List
from uuid import UUID
from datetime import datetime

from app.config import settings
from app.data.repositories.billing_repository import BillingRepository
from app.data.repositories.user_repository import UserRepository
from app.data.repositories.audit_repository import AuditRepository
from app.core.exceptions import NotFoundError, ValidationError, APIError, AuthenticationError

logger = logging.getLogger(__name__)


class StripeGateway:
    """
    Encapsulates direct interactions with the Stripe API, with retry logic for resilience.
    """
    def __init__(self, secret_key: str):
        stripe.api_key = secret_key
        self.webhook_secret = settings.stripe_webhook_secret

    def _retry(self, func, *args, **kwargs):
        max_attempts = getattr(settings, 'stripe_max_retries', 3)
        delay = getattr(settings, 'stripe_retry_delay_seconds', 1)
        for attempt in range(1, max_attempts + 1):
            try:
                return func(*args, **kwargs)
            except stripe.error.RateLimitError as e:
                logger.warning("Stripe rate limit (attempt %s/%s): %s", attempt, max_attempts, e)
                time.sleep(delay)
                delay *= 2
            except stripe.error.APIConnectionError as e:
                logger.warning("Stripe connection error (attempt %s/%s): %s", attempt, max_attempts, e)
                time.sleep(delay)
                delay *= 2
            except stripe.error.StripeError:
                raise
        raise APIError("Max retries exceeded for Stripe API calls.")

    def create_customer(self, **kwargs) -> stripe.Customer:
        return self._retry(stripe.Customer.create, **kwargs)

    def create_checkout_session(self, **kwargs) -> stripe.checkout.Session:
        return self._retry(stripe.checkout.Session.create, **kwargs)

    def create_portal_session(self, **kwargs) -> stripe.billing_portal.Session:
        return self._retry(stripe.billing_portal.Session.create, **kwargs)

    def construct_event(self, payload: str, sig_header: str) -> Any:
        try:
            return stripe.Webhook.construct_event(payload, sig_header, self.webhook_secret)
        except stripe.error.SignatureVerificationError as e:
            logger.error("Invalid Stripe signature: %s", e)
            raise AuthenticationError("Invalid Stripe signature")


class BillingService:
    """
    Provides high-level billing operations, orchestrating between Stripe and repositories.
    """
    def __init__(
        self,
        user_repository: UserRepository,
        billing_repository: BillingRepository,
        audit_repository: Optional[AuditRepository] = None,
        stripe_gateway: Optional[StripeGateway] = None,
    ):
        self.user_repo = user_repository
        self.billing_repo = billing_repository
        self.audit_repo = audit_repository or AuditRepository()
        self.gateway = stripe_gateway or StripeGateway(settings.stripe_secret_key)

        self.stripe_enabled = settings.enable_stripe
        self.portal_return_url = f"{settings.webapp_url}/billing/return"
        self.credit_packages = getattr(settings, 'credit_packages', {
            "starter": {"credits": 100, "price_cents": 500, "name": "Starter Pack"},
            "pro": {"credits": 1000, "price_cents": 4000, "name": "Pro Pack"},
            "enterprise": {"credits": 5000, "price_cents": 20000, "name": "Enterprise Pack"},
        })

    def get_credit_packages(self) -> Dict[str, Dict[str, Any]]:
        return self.credit_packages

    def get_billing_status(self) -> Dict[str, Any]:
        # Read settings dynamically for better SaaS behavior
        current_stripe_enabled = settings.enable_stripe
        status = "healthy" if current_stripe_enabled else "disabled"
        return {"stripe_enabled": current_stripe_enabled, "status": status}

    async def create_checkout_session(self, user_id: UUID, package_key: str) -> Dict[str, Any]:
        # Read settings dynamically for better SaaS behavior
        if not settings.enable_stripe:
            raise APIError("Billing is currently disabled.")

        package = self.credit_packages.get(package_key)
        if not package:
            raise ValidationError("Invalid credit package selected.")

        user_profile = self.user_repo.get_user_profile(str(user_id))
        if not user_profile:
            raise NotFoundError("User not found.")

        customer_id = user_profile.get("stripe_customer_id")
        if not customer_id:
            cust = self.gateway.create_customer(
                email=user_profile["email"],
                metadata={"user_id": str(user_id)}
            )
            customer_id = cust.id
            self.user_repo.update_user_profile(str(user_id), {"stripe_customer_id": customer_id})
            await self.audit_repo.log_event(str(user_id), "stripe_customer_created", {"customer_id": customer_id})

        try:
            session = self.gateway.create_checkout_session(
                payment_method_types=["card"],
                customer=customer_id,
                line_items=[{
                    "price_data": {
                        "currency": "usd",
                        "product_data": {"name": package["name"]},
                        "unit_amount": package["price_cents"]
                    },
                    "quantity": 1
                }],
                mode="payment",
                metadata={"user_id": str(user_id), "package_key": package_key, "credits": str(package["credits"])},
                success_url=self.portal_return_url,
                cancel_url=self.portal_return_url,
            )
            await self.audit_repo.log_event(str(user_id), "checkout_session_created", {"session_id": session.id})
            return {"session_id": session.id, "checkout_url": session.url}
        except stripe.error.StripeError as e:
            logger.exception("Stripe API error during checkout session creation.")
            raise APIError(f"Stripe API error: {str(e)}")

    async def handle_webhook(self, payload: str, sig_header: str) -> Dict[str, Any]:
        event = self.gateway.construct_event(payload, sig_header)
        event_type = event.get("type")
        data = event["data"]["object"]

        if event_type == "checkout.session.completed":
            ref_id = data.get("id")
            meta = data.get("metadata", {})
            user_id_str = meta.get("user_id")
            credits = meta.get("credits")

            if not user_id_str or not credits:
                raise ValidationError("Missing required metadata from Stripe session")

            ref_uuid = UUID(ref_id)
            user_uuid = UUID(user_id_str)
            existing = await self.billing_repo.find_transaction_by_reference(ref_uuid)
            if existing:
                return {"status": "already_processed"}

            profile = self.user_repo.get_user_profile(str(user_uuid))
            if not profile:
                raise NotFoundError("User not found for webhook processing")

            txn = await self.billing_repo.create_credit_purchase_transaction(
                user_id=user_uuid,
                credit_amount=int(credits),
                credit_balance_after=profile["credits_remaining"] + int(credits),
                usd_amount=data.get("amount_total", 0) / 100.0,
                usd_per_credit=(data.get("amount_total", 0) / 100.0) / int(credits),
                stripe_session_id=ref_uuid,
                metadata=meta
            )
            self.user_repo.add_credits(str(user_uuid), int(credits), "Stripe purchase")
            await self.audit_repo.log_event(str(user_uuid), "purchase_completed", {"reference_id": str(ref_uuid)})
            return {"status": "processed", "event_type": event_type}

        # handle other event types as needed
        return {"status": "ignored", "event_type": event_type}

    async def create_portal_session(self, user_id: UUID) -> Dict[str, Any]:
        # Read settings dynamically for better SaaS behavior
        if not settings.enable_stripe:
            raise APIError("Billing is currently disabled.")

        profile = self.user_repo.get_user_profile(str(user_id))
        customer_id = profile.get("stripe_customer_id") if profile else None
        if not customer_id:
            raise NotFoundError("Stripe customer ID not found for user.")

        session = self.gateway.create_portal_session(
            customer=customer_id,
            return_url=self.portal_return_url
        )
        await self.audit_repo.log_event(str(user_id), "portal_session_created", {})
        return {"portal_url": session.url}

    async def get_user_billing_history(self, user_id: UUID, limit: int = 50) -> List[Dict[str, Any]]:
        return await self.billing_repo.get_transactions_for_user(user_id=user_id, limit=limit)

    async def add_promotional_credits(self, user_id: UUID, credits: int, note: str = "Promotional credits") -> Dict[str, Any]:
        if credits <= 0:
            raise ValidationError("Promotional credits must be positive.")
        profile = self.user_repo.get_user_profile(str(user_id))
        if not profile:
            raise NotFoundError("User not found.")
        txn = await self.billing_repo.add_credits(
            user_id=user_id,
            credit_amount=credits,
            credit_balance_after=profile["credits_remaining"] + credits,
            description=note,
            metadata={"source": "promotion", "note": note}
        )
        self.user_repo.add_credits(str(user_id), credits, note)
        await self.audit_repo.log_event(str(user_id), "promotional_credits_added", {"credits": credits})
        return txn

    async def deduct_manual_credits(self, user_id: UUID, credits: int, reason: str = "Manual adjustment") -> Dict[str, Any]:
        if credits <= 0:
            raise ValidationError("Credits to deduct must be positive.")
        profile = self.user_repo.get_user_profile(str(user_id))
        if not profile:
            raise NotFoundError("User not found.")
        if profile.get("credits_remaining", 0) < credits:
            raise ValidationError("Insufficient credits for manual deduction.")
        txn = await self.billing_repo.deduct_credits(
            user_id=user_id,
            credit_amount=credits,
            credit_balance_after=profile["credits_remaining"] - credits,
            description=reason,
            metadata={"source": "admin", "reason": reason}
        )
        self.user_repo.deduct_credits(str(user_id), credits, reason)
        await self.audit_repo.log_event(str(user_id), "manual_credits_deducted", {"credits": credits})
        return txn
