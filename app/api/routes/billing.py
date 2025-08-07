# app/api/routes/billing.py
"""
Fixed billing API routes with proper dependency injection and error handling.
Handles credit packages, checkout sessions, billing history, and webhooks.
"""
import logging
from typing import Dict, Any, List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request, Header
from fastapi.security import HTTPBearer
from pydantic import BaseModel, Field
import time
from collections import defaultdict
from threading import Lock

from app.api.dependencies import get_user_context, UserContext, no_auth_required
from app.core.container import get_billing_service
from app.core.exceptions import (
    # Core exceptions
    NotFoundError,
    ValidationError,
    # Billing exceptions
    BillingError,
    InsufficientCreditsError,
    TransactionNotFoundError,
    DuplicateTransactionError,
    InvalidTransactionTypeError,
    PaymentError,
    StripeError,
    WebhookValidationError,
    # Service-specific exceptions from billing_service
    InvalidPackageError,
    CreditBalanceError,
    PaymentProcessingError
)
from app.services.billing_service import BillingService
from app.models.billing import (
    TransactionRecord,
    CheckoutSession,
    BillingHistory,
    CreditBalance,
    WebhookEvent,
    CreditBalanceResponse,
    TransactionResponse,
    CheckoutSessionResponse
)

logger = logging.getLogger(__name__)

# --- Rate Limiting ---

class SimpleRateLimiter:
    """Simple in-memory rate limiter for billing endpoints"""
    def __init__(self):
        self._requests = defaultdict(list)
        self._lock = Lock()
    
    def is_allowed(self, key: str, max_requests: int = 100, window_seconds: int = 3600) -> bool:
        """Check if request is allowed under rate limit"""
        current_time = time.time()
        
        with self._lock:
            # Clean old requests
            self._requests[key] = [
                req_time for req_time in self._requests[key] 
                if current_time - req_time < window_seconds
            ]
            
            # Check if under limit
            if len(self._requests[key]) >= max_requests:
                return False
            
            # Add current request
            self._requests[key].append(current_time)
            return True

rate_limiter = SimpleRateLimiter()

def check_rate_limit(key: str, max_requests: int = 100, window_seconds: int = 3600):
    """Rate limiting dependency"""
    if not rate_limiter.is_allowed(key, max_requests, window_seconds):
        raise HTTPException(
            status_code=429, 
            detail="Rate limit exceeded. Too many requests.",
            headers={"Retry-After": str(window_seconds)}
        )

async def billing_rate_limit(request: Request):
    """Standard billing rate limit"""
    client_ip = request.client.host
    check_rate_limit(f"billing:{client_ip}", max_requests=100, window_seconds=3600)

async def webhook_rate_limit(request: Request):
    """More permissive rate limit for webhooks"""
    client_ip = request.client.host
    check_rate_limit(f"webhook:{client_ip}", max_requests=1000, window_seconds=3600)

router = APIRouter(
    prefix="/billing",
    tags=["billing"],
    responses={
        402: {"description": "Payment required"},
        403: {"description": "Billing access denied"},
        404: {"description": "Resource not found"},
        409: {"description": "Conflict - duplicate transaction"},
        429: {"description": "Too many requests"}
    }
)

# --- Request Models ---

class PurchaseRequest(BaseModel):
    """Request model for credit purchase"""
    package_key: str = Field(..., min_length=1, max_length=50, description="Package to purchase")
    success_url: str | None = Field(None, max_length=500, description="Custom success URL")
    cancel_url: str | None = Field(None, max_length=500, description="Custom cancel URL")
    
    class Config:
        extra = "ignore"

class ManualAdjustmentRequest(BaseModel):
    """Request model for manual credit adjustment (admin placeholder - not implemented)"""
    user_id: str = Field(..., description="User ID to adjust")
    credit_amount: int = Field(..., description="Credits to add/subtract")
    description: str = Field(..., max_length=500, description="Reason for adjustment")
    adjustment_type: str = Field("bonus", description="Type of adjustment")
    
    class Config:
        extra = "ignore"

# --- Response Models ---

class CreditPackageResponse(BaseModel):
    """Response model for credit package"""
    key: str
    name: str
    credits: int
    price_cents: int
    price_usd: float
    price_per_credit: float
    popular: bool
    savings_percent: float | None

class BillingHistoryResponse(BaseModel):
    """Response model for billing history"""
    user_id: str
    transactions: List[TransactionResponse]
    total_transactions: int
    total_purchased: int
    total_used: int
    current_balance: int

class BillingStatusResponse(BaseModel):
    """Response model for billing system status"""
    stripe_enabled: bool
    packages_available: int
    supported_currencies: List[str]
    status: str

# --- Utility Functions ---

def _handle_billing_exception(e: Exception) -> HTTPException:
    """Convert billing exceptions to HTTP exceptions with proper status codes"""
    # Map specific exceptions to HTTP status codes
    status_code_map = {
        InsufficientCreditsError: 402,
        TransactionNotFoundError: 404,
        DuplicateTransactionError: 409,
        InvalidTransactionTypeError: 400,
        InvalidPackageError: 400,
        PaymentError: 402,
        StripeError: 502,
        WebhookValidationError: 400,
        CreditBalanceError: 400,
        PaymentProcessingError: 402,
        ValidationError: 400,
        NotFoundError: 404,
        BillingError: 500,
    }
    
    status_code = status_code_map.get(type(e), 500)
    
    return HTTPException(
        status_code=status_code,
        detail={
            "error": type(e).__name__,
            "message": str(e),
            "details": getattr(e, 'details', {})
        }
    )

def _package_to_response(pkg_data: Dict[str, Any]) -> CreditPackageResponse:
    """Convert package data to response model"""
    return CreditPackageResponse(
        key=pkg_data["key"],
        name=pkg_data["name"],
        credits=pkg_data["credits"],
        price_cents=pkg_data["price_cents"],
        price_usd=pkg_data["price_usd"],
        price_per_credit=pkg_data["price_per_credit"],
        popular=pkg_data["popular"],
        savings_percent=pkg_data.get("savings_percent")
    )

# --- Public Endpoints ---

@router.get("/status")
async def get_billing_status(
    request: Request,
    billing_service: BillingService = Depends(get_billing_service),
    _: bool = Depends(no_auth_required),
    __: None = Depends(billing_rate_limit)
) -> BillingStatusResponse:
    """Get billing system status (public endpoint)"""
    try:
        status = billing_service.get_billing_status()
        return BillingStatusResponse(**status)
    except Exception as e:
        logger.error(f"Failed to get billing status: {e}")
        raise HTTPException(status_code=500, detail="Failed to get billing status")

@router.get("/packages")
async def get_credit_packages(
    request: Request,
    billing_service: BillingService = Depends(get_billing_service),
    _: bool = Depends(no_auth_required),
    __: None = Depends(billing_rate_limit)
) -> Dict[str, Any]:
    """Get available credit packages (public endpoint)"""
    try:
        packages = billing_service.get_packages_with_savings()
        status = billing_service.get_billing_status()
        
        return {
            "packages": [_package_to_response(pkg).dict() for pkg in packages],
            "billing_enabled": status["stripe_enabled"],
            "currency": "USD"
        }
    except Exception as e:
        logger.error(f"Failed to get credit packages: {e}")
        raise HTTPException(status_code=500, detail="Failed to get credit packages")

@router.get("/packages/{package_key}")
async def get_package_details(
    package_key: str,
    request: Request,
    billing_service: BillingService = Depends(get_billing_service),
    _: bool = Depends(no_auth_required),
    __: None = Depends(billing_rate_limit)
) -> CreditPackageResponse:
    """Get details for a specific credit package (public endpoint)"""
    try:
        packages = billing_service.get_packages_with_savings()
        package_data = next((pkg for pkg in packages if pkg["key"] == package_key), None)
        
        if not package_data:
            raise HTTPException(status_code=404, detail=f"Package '{package_key}' not found")
        
        return _package_to_response(package_data)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get package details for {package_key}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get package details")

# --- User Endpoints ---

@router.get("/balance")
async def get_credit_balance(
    request: Request,
    context: UserContext = Depends(get_user_context),
    billing_service: BillingService = Depends(get_billing_service),
    _: None = Depends(billing_rate_limit)
) -> CreditBalanceResponse:
    """Get current credit balance for authenticated user"""
    try:
        user_id = UUID(context.user_id)
        balance = await billing_service.get_credit_balance(user_id)
        return CreditBalanceResponse.from_balance(balance)
    except Exception as e:
        logger.error(f"Failed to get credit balance for user {context.user_id}: {e}")
        raise _handle_billing_exception(e)

@router.get("/history")
async def get_billing_history(
    request: Request,
    context: UserContext = Depends(get_user_context),
    billing_service: BillingService = Depends(get_billing_service),
    limit: int = 50,
    _: None = Depends(billing_rate_limit)
) -> BillingHistoryResponse:
    """Get billing history for authenticated user"""
    try:
        # Limit bounds
        limit = max(1, min(limit, 100))
        
        user_id = UUID(context.user_id)
        history = await billing_service.get_billing_history(user_id, limit)
        
        return BillingHistoryResponse(
            user_id=context.user_id,  # Keep as string for API response
            transactions=[TransactionResponse.from_transaction(txn) for txn in history.transactions],
            total_transactions=len(history.transactions),
            total_purchased=history.total_credits_purchased,
            total_used=history.total_credits_used,
            current_balance=history.current_balance
        )
    except Exception as e:
        logger.error(f"Failed to get billing history for user {context.user_id}: {e}")
        raise _handle_billing_exception(e)

@router.get("/spending-summary")
async def get_spending_summary(
    request: Request,
    context: UserContext = Depends(get_user_context),
    billing_service: BillingService = Depends(get_billing_service),
    _: None = Depends(billing_rate_limit)
) -> Dict[str, Any]:
    """Get spending analytics for authenticated user"""
    try:
        user_id = UUID(context.user_id)
        summary = await billing_service.get_user_spending_summary(user_id)
        return summary
    except Exception as e:
        logger.error(f"Failed to get spending summary for user {context.user_id}: {e}")
        raise _handle_billing_exception(e)

# --- Purchase Endpoints ---

@router.post("/create-checkout")
async def create_checkout_session(
    request: PurchaseRequest,
    http_request: Request,
    context: UserContext = Depends(get_user_context),
    billing_service: BillingService = Depends(get_billing_service),
    _: None = Depends(billing_rate_limit)
) -> CheckoutSessionResponse:
    """Create checkout session for credit purchase"""
    try:
        user_id = UUID(context.user_id)
        session = await billing_service.create_checkout_session(
            user_id=user_id,
            package_key=request.package_key,
            success_url=request.success_url,
            cancel_url=request.cancel_url
        )
        
        return CheckoutSessionResponse.from_checkout_session(session)
    except Exception as e:
        logger.error(f"Failed to create checkout session for user {context.user_id}: {e}")
        raise _handle_billing_exception(e)

@router.post("/create-portal-session")
async def create_portal_session(
    http_request: Request,
    context: UserContext = Depends(get_user_context),
    billing_service: BillingService = Depends(get_billing_service),
    _: None = Depends(billing_rate_limit)
) -> Dict[str, Any]:
    """Create billing portal session for customer management"""
    try:
        user_id = UUID(context.user_id)
        portal_session = await billing_service.create_billing_portal_session(user_id)
        return portal_session
    except Exception as e:
        logger.error(f"Failed to create portal session for user {context.user_id}: {e}")
        raise _handle_billing_exception(e)

# --- Transaction Endpoints ---

@router.get("/transactions/{transaction_id}")
async def get_transaction(
    transaction_id: str,
    http_request: Request,
    context: UserContext = Depends(get_user_context),
    billing_service: BillingService = Depends(get_billing_service),
    _: None = Depends(billing_rate_limit)
) -> TransactionResponse:
    """Get specific transaction by ID"""
    try:
        transaction_uuid = UUID(transaction_id)
        transaction = await billing_service.get_transaction_by_id(transaction_uuid)
        
        # Verify transaction belongs to user
        if str(transaction.user_id) != context.user_id:
            raise HTTPException(status_code=403, detail="Transaction not accessible")
        
        return TransactionResponse.from_transaction(transaction)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid transaction ID")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get transaction {transaction_id}: {e}")
        raise _handle_billing_exception(e)

# --- Webhook Endpoints ---

@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(..., alias="Stripe-Signature"),
    billing_service: BillingService = Depends(get_billing_service),
    _: None = Depends(webhook_rate_limit)
) -> Dict[str, Any]:
    """Handle Stripe webhook events"""
    try:
        payload = await request.body()
        webhook_event = await billing_service.process_stripe_webhook(
            payload.decode(), stripe_signature
        )
        
        return {
            "event_id": webhook_event.event_id,
            "event_type": webhook_event.event_type,
            "processed": webhook_event.success,
            "result": webhook_event.result,
            "error": webhook_event.error
        }
    except WebhookValidationError as e:
        logger.error(f"Webhook validation failed: {e}")
        # Return 200 for webhook validation failures to prevent Stripe retries
        return {
            "event_id": "unknown",
            "event_type": "unknown",
            "processed": False,
            "error": "Webhook validation failed"
        }
    except Exception as e:
        logger.error(f"Webhook processing failed: {e}")
        # Return 200 for processing failures to prevent endless retries
        return {
            "event_id": "unknown", 
            "event_type": "unknown",
            "processed": False,
            "error": "Webhook processing failed"
        }

# --- Admin Endpoints (would require admin authentication) ---

@router.post("/admin/manual-adjustment")
async def create_manual_adjustment(
    request: ManualAdjustmentRequest,
    http_request: Request,
    context: UserContext = Depends(get_user_context),
    billing_service: BillingService = Depends(get_billing_service),
    _: None = Depends(billing_rate_limit)
) -> Dict[str, str]:
    """Create manual credit adjustment (PLACEHOLDER - not implemented for v1)"""
    # Admin functionality placeholder - not implemented in v1
    logger.warning(f"Admin adjustment attempt by user {context.user_id} - not implemented")
    raise HTTPException(
        status_code=501, 
        detail="Admin functionality not implemented in v1. Use Supabase dashboard for manual adjustments."
    )

# --- Health Check ---

@router.get("/health")
async def get_service_health(
    request: Request,
    billing_service: BillingService = Depends(get_billing_service),
    _: bool = Depends(no_auth_required),
    __: None = Depends(billing_rate_limit)
) -> Dict[str, Any]:
    """Get billing service health status"""
    try:
        health = await billing_service.get_service_health()
        
        # Return appropriate HTTP status based on health
        if health.get("overall_status") == "unhealthy":
            raise HTTPException(status_code=503, detail=health)
        elif health.get("overall_status") == "degraded":
            # Still return 200 but with degraded status
            pass
        
        return health
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        # Provide a fallback health response structure
        health_response = {
            "overall_status": "unhealthy",
            "error": str(e),
            "timestamp": "2025-01-30T00:00:00Z"
        }
        raise HTTPException(status_code=503, detail=health_response)