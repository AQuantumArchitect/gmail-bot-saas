# app/api/routes/billing.py
"""
Billing routes for credit purchases and Stripe integration.
Handles credit packages, checkout sessions, and payment processing.
"""
import logging
from typing import Dict, Any, Optional, List
from fastapi import APIRouter, Depends, HTTPException, Request, Header
from pydantic import BaseModel, Field, EmailStr
from datetime import datetime, timedelta

from app.api.dependencies import (
    get_user_context,
    require_credit_purchase_permission,
    UserContext,
    no_auth_required
)
from app.services.billing_service import BillingService
from app.services.user_service import UserService
from app.data.repositories.user_repository import UserRepository
from app.data.repositories.billing_repository import BillingRepository
from app.data.repositories.audit_repository import AuditRepository
from app.core.config import settings
from app.core.exceptions import ValidationError, NotFoundError, APIError

logger = logging.getLogger(__name__)

# Initialize services
user_repository = UserRepository()
billing_repository = BillingRepository()
audit_repository = AuditRepository()

billing_service = BillingService(
    user_repository=user_repository,
    billing_repository=billing_repository,
    audit_repository=audit_repository
)

user_service = UserService(
    user_repository=user_repository,
    billing_service=billing_service,
    billing_repository=billing_repository,
    email_repository=None,
    gmail_repository=None
)

router = APIRouter(
    prefix="/billing",
    tags=["billing"],
    responses={
        402: {"description": "Payment required"},
        403: {"description": "Billing access denied"}
    }
)


# --- Request/Response Models ---

class CreditPackage(BaseModel):
    """Credit package information"""
    key: str
    name: str
    credits: int
    price_cents: int
    price_usd: float
    per_credit_cost: float
    savings_percent: Optional[float] = None
    popular: bool = False


class CreditBalanceResponse(BaseModel):
    """Credit balance response"""
    user_id: str
    credits_remaining: int
    last_updated: str


class PurchaseRequest(BaseModel):
    """Credit purchase request"""
    package_key: str = Field(..., description="Package to purchase (starter, pro, enterprise)")
    user_email: EmailStr = Field(..., description="User email for purchase")
    return_url: Optional[str] = Field(None, description="Custom return URL after purchase")


class CheckoutSessionResponse(BaseModel):
    """Checkout session response"""
    success: bool
    session_id: str
    checkout_url: str
    package_info: CreditPackage
    expires_at: str


class TransactionResponse(BaseModel):
    """Transaction history response"""
    id: str
    transaction_type: str
    credit_amount: int
    credit_balance_after: int
    description: str
    usd_amount: Optional[float] = None
    created_at: str
    metadata: Dict[str, Any]


class BillingHistoryResponse(BaseModel):
    """Billing history response"""
    user_id: str
    transactions: List[TransactionResponse]
    total_transactions: int
    total_purchased: int
    total_used: int
    current_balance: int


# --- Credit Package Endpoints ---

@router.get("/packages")
async def get_credit_packages(
    _: bool = Depends(no_auth_required)
) -> Dict[str, Any]:
    """
    Get available credit packages.
    Public endpoint - no authentication required.
    """
    try:
        packages = billing_service.get_credit_packages()
        
        # Calculate savings and format packages
        starter_price_per_credit = packages["starter"]["price_cents"] / packages["starter"]["credits"]
        
        formatted_packages = []
        for key, package in packages.items():
            price_per_credit = package["price_cents"] / package["credits"]
            savings_percent = ((starter_price_per_credit - price_per_credit) / starter_price_per_credit) * 100 if key != "starter" else None
            
            formatted_packages.append(CreditPackage(
                key=key,
                name=package["name"],
                credits=package["credits"],
                price_cents=package["price_cents"],
                price_usd=package["price_cents"] / 100,
                per_credit_cost=price_per_credit / 100,
                savings_percent=round(savings_percent, 1) if savings_percent else None,
                popular=(key == "pro")  # Mark pro as popular
            ))
        
        return {
            "packages": [pkg.dict() for pkg in formatted_packages],
            "currency": "USD",
            "billing_enabled": settings.enable_stripe
        }
    
    except Exception as e:
        logger.error(f"Get packages error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to get credit packages"
        )


@router.get("/packages/{package_key}")
async def get_package_details(
    package_key: str,
    _: bool = Depends(no_auth_required)
) -> CreditPackage:
    """
    Get details for a specific credit package.
    """
    try:
        packages = billing_service.get_credit_packages()
        
        if package_key not in packages:
            raise HTTPException(
                status_code=404,
                detail=f"Package '{package_key}' not found"
            )
        
        package = packages[package_key]
        price_per_credit = package["price_cents"] / package["credits"]
        
        return CreditPackage(
            key=package_key,
            name=package["name"],
            credits=package["credits"],
            price_cents=package["price_cents"],
            price_usd=package["price_cents"] / 100,
            per_credit_cost=price_per_credit / 100,
            popular=(package_key == "pro")
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get package details error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to get package details"
        )


# --- Credit Balance Endpoints ---

@router.get("/balance", response_model=CreditBalanceResponse)
async def get_credit_balance(
    context: UserContext = Depends(get_user_context)
) -> CreditBalanceResponse:
    """
    Get current credit balance for user.
    """
    try:
        balance = await user_service.get_credit_balance(context.user_id)
        
        return CreditBalanceResponse(
            user_id=context.user_id,
            credits_remaining=balance["credits_remaining"],
            last_updated=balance["last_updated"]
        )
    
    except Exception as e:
        logger.error(f"Get credit balance error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to get credit balance"
        )


@router.get("/history", response_model=BillingHistoryResponse)
async def get_billing_history(
    context: UserContext = Depends(get_user_context),
    limit: int = 50
) -> BillingHistoryResponse:
    """
    Get billing history for user.
    """
    try:
        if limit > 100:
            limit = 100  # Cap at 100 transactions
        
        # Get transaction history
        history = await user_service.get_credit_history(context.user_id, limit=limit)
        
        # Format transactions
        formatted_transactions = []
        for txn in history["transactions"]:
            formatted_transactions.append(TransactionResponse(
                id=txn["id"],
                transaction_type=txn["transaction_type"],
                credit_amount=txn["credit_amount"],
                credit_balance_after=txn["credit_balance_after"],
                description=txn["description"],
                usd_amount=txn.get("usd_amount"),
                created_at=txn["created_at"],
                metadata=txn.get("metadata", {})
            ))
        
        # Calculate totals
        # FIXED: Changed attribute access (txn.credit_amount) to dictionary access (txn['credit_amount'])
        total_purchased = sum(txn['credit_amount'] for txn in history["transactions"] if txn['transaction_type'] == "purchase")
        total_used = sum(abs(txn['credit_amount']) for txn in history["transactions"] if txn['transaction_type'] == "usage")
        
        return BillingHistoryResponse(
            user_id=context.user_id,
            transactions=formatted_transactions,
            total_transactions=history["total_transactions"],
            total_purchased=total_purchased,
            total_used=total_used,
            current_balance=context.credits_remaining
        )
    
    except Exception as e:
        logger.error(f"Get billing history error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to get billing history"
        )


# --- Purchase Endpoints ---

@router.post("/create-checkout", response_model=CheckoutSessionResponse)
async def create_checkout_session(
    request: PurchaseRequest,
    context: UserContext = Depends(require_credit_purchase_permission)
) -> CheckoutSessionResponse:
    """
    Create Stripe checkout session for credit purchase.
    """
    try:
        if not settings.enable_stripe:
            raise HTTPException(
                status_code=503,
                detail="Billing is currently disabled"
            )
        
        # Validate package
        packages = billing_service.get_credit_packages()
        if request.package_key not in packages:
            raise HTTPException(
                status_code=404,
                detail=f"Package '{request.package_key}' not found"
            )
        
        # Verify email matches user
        if request.user_email != context.email:
            raise HTTPException(
                status_code=403,
                detail="Email must match authenticated user"
            )
        
        # Create checkout session
        session_data = await billing_service.create_checkout_session(
            user_id=context.user_id,
            package_key=request.package_key
        )
        
        # Get package info
        package = packages[request.package_key]
        package_info = CreditPackage(
            key=request.package_key,
            name=package["name"],
            credits=package["credits"],
            price_cents=package["price_cents"],
            price_usd=package["price_cents"] / 100,
            per_credit_cost=(package["price_cents"] / package["credits"]) / 100
        )
        
        logger.info(f"Checkout session created for user: {context.user_id}")
        
        return CheckoutSessionResponse(
            success=True,
            session_id=session_data["session_id"],
            checkout_url=session_data["checkout_url"],
            package_info=package_info,
            expires_at=(datetime.now() + timedelta(hours=1)).isoformat()
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Create checkout error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to create checkout session"
        )


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(..., alias="stripe-signature")
) -> Dict[str, Any]:
    """
    Handle Stripe webhook events.
    Processes payment confirmations and credit additions.
    """
    try:
        if not settings.enable_stripe:
            raise HTTPException(
                status_code=503,
                detail="Billing webhooks are disabled"
            )
        
        # Get request body
        payload = await request.body()
        
        # Process webhook
        result = await billing_service.handle_webhook(
            payload.decode(),
            stripe_signature
        )
        
        logger.info(f"Webhook processed: {result['event_type']} - {result['status']}")
        
        return {
            "success": True,
            "event_processed": result["event_type"],
            "status": result["status"]
        }
    
    except ValidationError as e:
        logger.warning(f"Webhook validation error: {e}")
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )
    
    except Exception as e:
        logger.error(f"Webhook processing error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Webhook processing failed"
        )


# --- Admin/Management Endpoints ---

@router.post("/add-credits")
async def add_promotional_credits(
    user_id: str,
    credits: int,
    note: str = "Promotional credits",
    context: UserContext = Depends(get_user_context)
) -> Dict[str, Any]:
    """
    Add promotional credits to a user account.
    For now, users can only add credits to their own account.
    """
    try:
        # For security, only allow users to add credits to their own account
        # In a real admin system, this would check for admin permissions
        if user_id != context.user_id:
            raise HTTPException(
                status_code=403,
                detail="Can only add credits to your own account"
            )
        
        if credits <= 0 or credits > 100:
            raise HTTPException(
                status_code=422,
                detail="Credits must be between 1 and 100"
            )
        
        # Add promotional credits
        result = await billing_service.add_promotional_credits(
            user_id=user_id,
            credits=credits,
            note=note
        )
        
        logger.info(f"Promotional credits added: {credits} to user {user_id}")
        
        return {
            "success": True,
            "credits_added": credits,
            "new_balance": result["credit_balance_after"],
            "transaction_id": result["id"]
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Add promotional credits error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to add promotional credits"
        )


# --- Billing Status & Health ---

@router.get("/status")
async def get_billing_status(
    _: bool = Depends(no_auth_required)
) -> Dict[str, Any]:
    """
    Get billing system status.
    Public endpoint for status page.
    """
    try:
        status = billing_service.get_billing_status()
        
        return {
            "billing_enabled": status["stripe_enabled"],
            "status": status["status"],
            "available_packages": len(billing_service.get_credit_packages()),
            "currency": "USD"
        }
    
    except Exception as e:
        logger.error(f"Get billing status error: {e}")
        return {
            "billing_enabled": False,
            "status": "unhealthy",
            "error": str(e)
        }


@router.get("/health")
async def billing_health_check(
    _: bool = Depends(no_auth_required)
) -> Dict[str, Any]:
    """
    Health check for billing system.
    """
    try:
        status = billing_service.get_billing_status()
        
        # Test basic functionality
        packages = billing_service.get_credit_packages()
        
        return {
            "status": "healthy" if status["stripe_enabled"] else "disabled",
            "billing_enabled": status["stripe_enabled"],
            "packages_available": len(packages),
            "stripe_status": status["status"]
        }
    
    except Exception as e:
        logger.error(f"Billing health check error: {e}")
        return {
            "status": "unhealthy",
            "error": str(e)
        }


# --- User Purchase Portal ---

@router.get("/portal")
async def create_customer_portal_session(
    context: UserContext = Depends(get_user_context)
) -> Dict[str, Any]:
    """
    Create Stripe customer portal session.
    Allows users to manage their billing and view invoices.
    """
    try:
        if not settings.enable_stripe:
            raise HTTPException(
                status_code=503,
                detail="Billing portal is currently disabled"
            )
        
        # Create portal session
        portal_data = await billing_service.create_portal_session(context.user_id)
        
        logger.info(f"Customer portal session created for user: {context.user_id}")
        
        return {
            "success": True,
            "portal_url": portal_data["portal_url"],
            "expires_at": (datetime.now() + timedelta(hours=1)).isoformat()
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Create portal session error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to create customer portal session"
        )
