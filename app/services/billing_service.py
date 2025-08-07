# app/services/billing_service.py
"""
Business logic layer for billing operations.
Orchestrates between repository, external services, and domain rules.
"""
import logging
from typing import Dict, Any, List, Optional
from uuid import UUID, uuid4
from datetime import datetime, timedelta

from app.core.config import settings, CreditPackage
from app.core.exceptions import (
    # Core exceptions
    NotFoundError,
    ValidationError,
    APIError,
    # Billing exceptions
    BillingError,
    InsufficientCreditsError,
    TransactionNotFoundError,
    DuplicateTransactionError,
    InvalidTransactionTypeError,
    PaymentError,
    StripeError,
    InvalidPackageError,          
    CreditBalanceError,          
    PaymentProcessingError,       
    WebhookValidationError,       
    # Configuration exceptions
    ConfigurationError,
    # External service exceptions
    ExternalServiceError
)
from app.data.repositories.billing_repository import BillingRepository
from app.data.repositories.user_repository import UserRepository
from app.external.stripe_client import StripeClient
from app.models.billing import (
    TransactionRecord, 
    CheckoutSession, 
    BillingHistory, 
    CreditBalance, 
    WebhookEvent,
    PaymentIntent,
    BillingSummary,
    CreditUsageAnalytics
)

logger = logging.getLogger(__name__)

class BillingService:
    """
    High-level billing operations with proper business logic separation.
    Handles credit management, payment processing, and billing history.
    """
    
    def __init__(
        self,
        billing_repo: BillingRepository,
        user_repo: UserRepository
    ):
        """Initialize billing service with required dependencies"""
        self.billing_repo = billing_repo
        self.user_repo = user_repo
        
        # ✅ CORRECTED: The service now handles its own Stripe client creation
        # and validation, making it more self-contained and robust.
        self.stripe_client: Optional[StripeClient] = None
        if settings.enable_stripe:
            if not settings.stripe_secret_key:
                raise ConfigurationError("Stripe secret key required but not found in settings.")
            self.stripe_client = StripeClient(
                secret_key=settings.stripe_secret_key,
                webhook_secret=settings.stripe_webhook_secret
            )

        self.available_packages = settings.get_credit_packages()

    # --- Credit Package Management ---
    
    def get_available_packages(self) -> List[CreditPackage]:
        """Get all available credit packages"""
        return list(self.available_packages.values())
        
    def get_package_by_key(self, package_key: str) -> CreditPackage:
        """Get specific credit package by key"""
        if package_key not in self.available_packages:
            raise InvalidPackageError(
                package_key=package_key,
                available_packages=list(self.available_packages.keys())
            )
        return self.available_packages[package_key]

    # --- Credit Balance Management ---
    
    async def get_credit_balance(self, user_id: UUID) -> CreditBalance:
        """Get current credit balance for user"""
        try:
            user_profile = self.user_repo.get_user_profile(str(user_id))
            if not user_profile:
                raise NotFoundError(f"User {user_id} not found")
            
            return CreditBalance(
                user_id=UUID(user_profile['user_id']),
                credits_remaining=user_profile.get('credits_remaining', 0),
                last_updated=datetime.utcnow()
            )
            
        except NotFoundError:
            raise
        except Exception as e:
            logger.error(f"Failed to get credit balance for user {user_id}: {e}")
            raise BillingError(f"Failed to get credit balance: {e}")

    async def check_credit_sufficiency(self, user_id: UUID, amount: int) -> bool:
        """Check if a user has enough credits for an operation."""
        balance = await self.get_credit_balance(user_id)
        return balance.can_afford(amount)

    async def add_credits(
        self,
        user_id: UUID,
        credit_amount: int,
        description: str,
        reference_id: Optional[str] = None,
        reference_type: str = "purchase",
        usd_amount: Optional[float] = None,
        usd_per_credit: Optional[float] = None
    ) -> TransactionRecord:
        """Add credits to user account"""
        if credit_amount <= 0:
            raise ValidationError("Credit amount must be positive")
        
        balance = await self.get_credit_balance(user_id)
        new_balance = balance.credits_remaining + credit_amount
        
        try:
            self.user_repo.update_credits(str(user_id), new_balance)
            
            transaction = await self.billing_repo.create_transaction(
                user_id=user_id,
                transaction_type=reference_type,
                credit_amount=credit_amount,
                credit_balance_after=new_balance,
                description=description,
                reference_id=reference_id,
                reference_type=reference_type,
                usd_amount=usd_amount,
                usd_per_credit=usd_per_credit
            )
            
            logger.info(f"Added {credit_amount} credits to user {user_id}. New balance: {new_balance}")
            return transaction
            
        except Exception as e:
            logger.error(f"Failed to add credits for user {user_id}: {e}")
            try:
                self.user_repo.update_credits(str(user_id), balance.credits_remaining)
            except:
                logger.error(f"Failed to rollback credit balance for user {user_id}")
            raise CreditBalanceError(f"Credit addition failed: {e}", user_id=str(user_id), operation="add_credits")

    async def deduct_credits(
        self,
        user_id: UUID,
        credit_amount: int,
        description: str,
        reference_id: Optional[str] = None,
        reference_type: str = "usage"
    ) -> TransactionRecord:
        """Deduct credits from user account with balance validation"""
        if credit_amount <= 0:
            raise ValidationError("Credit amount must be positive")
        
        balance = await self.get_credit_balance(user_id)
        if not balance.can_afford(credit_amount):
            raise InsufficientCreditsError(f"Insufficient credits: need {credit_amount}, have {balance.credits_remaining}", balance=balance.credits_remaining, requested=credit_amount)
        
        new_balance = balance.credits_remaining - credit_amount
        
        try:
            self.user_repo.update_credits(str(user_id), new_balance)
            
            transaction = await self.billing_repo.create_transaction(
                user_id=user_id,
                transaction_type="usage",
                credit_amount=-credit_amount,
                credit_balance_after=new_balance,
                description=description,
                reference_id=reference_id,
                reference_type=reference_type
            )
            
            logger.info(f"Deducted {credit_amount} credits from user {user_id}. New balance: {new_balance}")
            return transaction
            
        except Exception as e:
            logger.error(f"Failed to deduct credits for user {user_id}: {e}")
            try:
                self.user_repo.update_credits(str(user_id), balance.credits_remaining)
            except:
                logger.error(f"Failed to rollback credit balance for user {user_id}")
            raise CreditBalanceError(f"Credit deduction failed: {e}", user_id=str(user_id), operation="deduct_credits")

    async def deduct_manual_credits(
        self, 
        user_id: str, 
        credit_amount: int, 
        description: str
    ) -> Dict[str, Any]:
        """Convenience method for manual credit deduction (used by email service)"""
        try:
            user_uuid = UUID(user_id)
            transaction = await self.deduct_credits(
                user_id=user_uuid,
                credit_amount=credit_amount,
                description=description,
                reference_type="manual_usage"
            )
            
            return {
                "success": True,
                "credits_deducted": credit_amount,
                "remaining_balance": transaction.credit_balance_after,
                "transaction_id": str(transaction.id)
            }
            
        except Exception as e:
            logger.error(f"Manual credit deduction failed for user {user_id}: {e}")
            return {
                "success": False,
                "error": str(e),
                "credits_deducted": 0,
                "remaining_balance": 0
            }

    # --- Payment Processing ---
    
    async def create_checkout_session(
        self, 
        user_id: UUID, 
        package_key: str,
        success_url: Optional[str] = None,
        cancel_url: Optional[str] = None
    ) -> CheckoutSession:
        """Create Stripe checkout session for credit purchase"""
        if not settings.enable_stripe:
            raise PaymentProcessingError("Billing is currently disabled")
        
        if not self.stripe_client:
            raise PaymentProcessingError("Stripe client not initialized")
        
        # Validate package
        package = self.get_package_by_key(package_key)
        
        # Get user profile
        user_profile = self.user_repo.get_user_profile(str(user_id))
        if not user_profile:
            raise NotFoundError(f"User {user_id} not found")
        
        try:
            # Create/get Stripe customer
            customer_id = user_profile.get("stripe_customer_id")
            if not customer_id:
                customer = await self.stripe_client.create_customer(
                    email=user_profile["email"],
                    name=user_profile.get("display_name"),
                    metadata={"user_id": str(user_id)}
                )
                customer_id = customer["id"]
                
                # Save customer ID to user profile
                self.user_repo.update_user_profile(str(user_id), {"stripe_customer_id": customer_id})
            
            # Prepare line items
            line_items = [{
                "price_data": {
                    "currency": "usd",
                    "unit_amount": package.price_cents,
                    "product_data": {
                        "name": package.name,
                        "description": f"{package.credits} credits for email processing"
                    }
                },
                "quantity": 1
            }]
            
            # Create checkout session
            session = await self.stripe_client.create_checkout_session(
                customer_id=customer_id,
                line_items=line_items,
                success_url=success_url or f"{settings.portal_return_url}?session_id={{CHECKOUT_SESSION_ID}}",
                cancel_url=cancel_url or settings.portal_return_url,
                metadata={
                    "user_id": str(user_id),
                    "package_key": package_key,
                    "credits": str(package.credits)
                }
            )
            
            checkout_session = CheckoutSession(
                session_id=session["id"],
                checkout_url=session["url"],
                package=package,
                expires_at=datetime.utcnow() + timedelta(hours=24),
                customer_id=customer_id,
                metadata=session.get("metadata", {})
            )
            
            logger.info(f"Created checkout session {session['id']} for user {user_id}, package {package_key}")
            return checkout_session
            
        except Exception as e:
            logger.error(f"Failed to create checkout session for user {user_id}: {e}")
            raise PaymentProcessingError(f"Failed to create checkout session: {e}")

    async def handle_payment_success(self, session_id: str) -> TransactionRecord:
        """Handle successful payment from Stripe webhook"""
        try:
            # Get session details from Stripe
            session = await self.stripe_client.get_checkout_session(session_id)
            
            user_id = UUID(session["metadata"]["user_id"])
            package_key = session["metadata"]["package_key"]
            credits = int(session["metadata"]["credits"])
            
            # Check if already processed (idempotency)
            existing = await self.billing_repo.find_transaction_by_reference(
                session_id, "stripe_checkout"
            )
            if existing:
                logger.info(f"Payment {session_id} already processed, returning existing transaction")
                return existing
            
            # Get package for pricing info
            package = self.get_package_by_key(package_key)
            
            # Add credits to account
            transaction = await self.add_credits(
                user_id=user_id,
                credit_amount=credits,
                description=f"Credit purchase: {package.name}",
                reference_id=session_id,
                reference_type="stripe_checkout",
                usd_amount=package.price_usd,
                usd_per_credit=package.price_per_credit_usd
            )
            
            logger.info(f"Successfully processed payment {session_id} for user {user_id}: {credits} credits")
            return transaction
            
        except (InvalidPackageError, NotFoundError) as e:
            logger.error(f"Payment processing failed for session {session_id}: {e}")
            raise PaymentProcessingError(f"Payment processing failed: {e}")
        except Exception as e:
            logger.error(f"Failed to process payment success for session {session_id}: {e}")
            raise PaymentProcessingError(f"Payment processing failed: {e}")
    
    async def handle_payment_failure(
        self, 
        session_id: str, 
        error_message: str
    ) -> TransactionRecord:
        """Handle failed payment - create audit record"""
        try:
            # Get session details from Stripe
            session = await self.stripe_client.get_checkout_session(session_id)
            user_id = UUID(session["metadata"]["user_id"])
            
            # Create audit transaction for the failure
            balance = await self.get_credit_balance(user_id)
            transaction = await self.billing_repo.create_transaction(
                user_id=user_id,
                transaction_type="adjustment",
                credit_amount=0,
                credit_balance_after=balance.credits_remaining,
                description="Payment failed",
                reference_id=session_id,
                reference_type="stripe_checkout_failed",
                metadata={"error_message": error_message}
            )
            
            logger.info(f"Created failure audit for session {session_id}")
            return transaction
            
        except Exception as e:
            logger.error(f"Failed to handle payment failure for session {session_id}: {e}")
            raise PaymentProcessingError(f"Payment failure handling failed: {e}")

    # --- Billing History & Analytics ---
    
    async def get_billing_history(self, user_id: UUID, limit: int = 50) -> BillingHistory:
        """Get comprehensive billing history for user"""
        try:
            transactions = await self.billing_repo.list_transactions_for_user(user_id, limit)
            balance = await self.get_credit_balance(user_id)
            
            return BillingHistory.from_transactions(
                user_id=user_id,
                transactions=transactions,
                current_balance=balance.credits_remaining
            )
            
        except Exception as e:
            logger.error(f"Failed to get billing history for user {user_id}: {e}")
            raise BillingError(f"Failed to get billing history: {e}")
    
    async def get_transaction_by_id(self, transaction_id: UUID) -> TransactionRecord:
        """Get specific transaction by ID"""
        transaction = await self.billing_repo.get_transaction_by_id(transaction_id)
        if not transaction:
            raise TransactionNotFoundError(str(transaction_id))
        return transaction
    
    async def get_user_spending_summary(self, user_id: UUID) -> Dict[str, Any]:
        """Get spending analytics for user"""
        try:
            summary = await self.billing_repo.get_user_transaction_summary(user_id)
            balance = await self.get_credit_balance(user_id)
            
            # Calculate additional metrics
            total_spent_usd = 0.0
            recent_transactions = await self.billing_repo.list_transactions_for_user(user_id, limit=100)
            
            for txn in recent_transactions:
                if txn.transaction_type == "purchase" and txn.usd_amount:
                    total_spent_usd += txn.usd_amount
            
            return {
                "user_id": str(user_id),
                "current_balance": balance.credits_remaining,
                "total_purchased": summary.total_purchased,
                "total_used": summary.total_used,
                "total_spent_usd": round(total_spent_usd, 2),
                "total_transactions": summary.total_transactions,
                "average_per_credit": round(
                    total_spent_usd / summary.total_purchased, 4
                ) if summary.total_purchased > 0 else 0,
                "transaction_breakdown": summary.transaction_breakdown,
                "last_purchase_date": summary.last_purchase_date.isoformat() if summary.last_purchase_date else None,
                "last_usage_date": summary.last_usage_date.isoformat() if summary.last_usage_date else None
            }
            
        except Exception as e:
            logger.error(f"Failed to get spending summary for user {user_id}: {e}")
            raise BillingError(f"Failed to get spending summary: {e}")

    # --- Webhook Processing ---
    
    async def process_stripe_webhook(self, payload: str, signature: str) -> WebhookEvent:
        """Process Stripe webhook events"""
        try:
            if not self.stripe_client:
                raise WebhookValidationError("Stripe client not initialized")
            
            event = self.stripe_client.construct_webhook_event(payload, signature)
            event_id = event["id"]
            event_type = event["type"]
            
            logger.info(f"Processing webhook event {event_id}: {event_type}")
            
            result = {"processed": False, "reason": "unhandled_event_type"}
            
            if event_type == "checkout.session.completed":
                session = event["data"]["object"]
                if session.get("payment_status") == "paid":
                    transaction = await self.handle_payment_success(session["id"])
                    result = {
                        "processed": True, 
                        "transaction_id": str(transaction.id),
                        "credits_added": transaction.credit_amount
                    }
            
            elif event_type == "checkout.session.expired":
                session = event["data"]["object"]
                logger.info(f"Checkout session expired: {session['id']}")
                result = {"processed": True, "reason": "session_expired"}
            
            return WebhookEvent(
                event_id=event_id,
                event_type=event_type,
                processed_at=datetime.utcnow(),
                success=result.get("processed", False),
                result=result,
                error=None
            )
            
        except WebhookValidationError:
            raise
        except Exception as e:
            logger.error(f"Webhook processing failed: {e}")
            return WebhookEvent(
                event_id="unknown",
                event_type="unknown", 
                processed_at=datetime.utcnow(),
                success=False,
                result=None,
                error=str(e)
            )

    # --- Administrative Methods ---
    
    async def create_bonus_credits(
        self,
        user_id: UUID,
        credit_amount: int,
        description: str = "Bonus credits",
        admin_reference: Optional[str] = None
    ) -> TransactionRecord:
        """Add bonus credits to user account (admin function)"""
        return await self.add_credits(
            user_id=user_id,
            credit_amount=credit_amount,
            description=description,
            reference_id=admin_reference,
            reference_type="bonus"
        )
    
    async def create_refund(
        self,
        user_id: UUID,
        original_transaction_id: UUID,
        refund_amount: int,
        description: str = "Credit refund"
    ) -> TransactionRecord:
        """Process a refund (admin function)"""
        # Verify original transaction exists
        original_txn = await self.get_transaction_by_id(original_transaction_id)
        
        # Add refunded credits
        return await self.add_credits(
            user_id=user_id,
            credit_amount=refund_amount,
            description=description,
            reference_id=str(original_transaction_id),
            reference_type="refund"
        )
    
    def get_billing_status(self) -> Dict[str, Any]:
        """Get the operational status of the billing system."""
        return {
            "stripe_enabled": settings.enable_stripe,
            "status": "healthy" if settings.enable_stripe else "disabled"
        }

    async def get_system_billing_stats(self) -> Dict[str, Any]:
        """Get system-wide billing statistics (admin function)"""
        # This would require system-wide queries - simplified implementation
        try:
            return {
                "total_revenue_estimate": "Not implemented",
                "active_customers_estimate": "Not implemented", 
                "average_purchase_size": "Not implemented",
                "timestamp": datetime.utcnow().isoformat(),
                "note": "System stats require aggregation queries across all users"
            }
        except Exception as e:
            logger.error(f"Failed to get system billing stats: {e}")
            raise BillingError(f"Failed to get system stats: {e}")

    # --- Health Check ---
    
    async def health_check(self) -> Dict[str, Any]:
        """Perform health check on billing service"""
        health = {
            "service_healthy": True,
            "timestamp": datetime.utcnow().isoformat(),
            "overall_status": "healthy",
            "components": {}
        }
        
        # Check repository health
        try:
            repo_health = await self.billing_repo.health_check()
            health["components"]["repository"] = repo_health
        except Exception as e:
            health["components"]["repository"] = {"healthy": False, "error": str(e)}
            health["overall_status"] = "unhealthy"
        
        # Check Stripe connectivity
        if settings.enable_stripe and self.stripe_client:
            try:
                account = await self.stripe_client.get_account()
                health["components"]["stripe"] = {
                    "healthy": True,
                    "account_id": account["id"],
                    "charges_enabled": account.get("charges_enabled", False)
                }
            except Exception as e:
                health["components"]["stripe"] = {"healthy": False, "error": str(e)}
                health["overall_status"] = "degraded"
        else:
            health["components"]["stripe"] = {"healthy": True, "note": "disabled"}
        
        # Check configuration
        try:
            settings.validate_billing_configuration()
            health["components"]["configuration"] = {"healthy": True}
        except Exception as e:
            health["components"]["configuration"] = {"healthy": False, "error": str(e)}
            health["overall_status"] = "unhealthy"
        
        return health
