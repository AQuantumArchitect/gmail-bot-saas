# app/models/billing.py
"""
Billing domain models and data structures.
Complete set of models for billing operations, credit management, and payment processing.
"""
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from uuid import UUID
from pydantic import BaseModel, Field, validator

from app.core.config import CreditPackage


class TransactionRecord(BaseModel):
    """
    Represents a credit transaction record from the database.
    Immutable record of all credit-related activities.
    """
    id: UUID
    user_id: UUID
    transaction_type: str
    credit_amount: int
    credit_balance_after: int
    description: str
    reference_id: Optional[str] = None  # ✅ Changed from UUID to str
    reference_type: Optional[str] = None
    usd_amount: Optional[float] = None
    usd_per_credit: Optional[float] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    
    @validator('transaction_type')
    def validate_transaction_type(cls, v):
        valid_types = {"purchase", "usage", "refund", "bonus", "adjustment"}
        if v not in valid_types:
            raise ValueError(f"Invalid transaction type. Must be one of: {valid_types}")
        return v
    
    @validator('credit_amount')
    def validate_credit_amount(cls, v, values):
        # Usage transactions should have negative amounts
        if values.get('transaction_type') == 'usage' and v >= 0:
            raise ValueError("Usage transactions must have negative credit amounts")
        # Purchase, bonus, refund should have positive amounts
        elif values.get('transaction_type') in ['purchase', 'bonus', 'refund'] and v <= 0:
            raise ValueError("Purchase/bonus/refund transactions must have positive credit amounts")
        return v
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TransactionRecord":
        """Create TransactionRecord from dictionary (e.g., from database)"""
        # Make a copy to avoid modifying the original
        data = data.copy()
        
        # Handle UUID conversion
        if isinstance(data.get('id'), str):
            data['id'] = UUID(data['id'])
        if isinstance(data.get('user_id'), str):
            data['user_id'] = UUID(data['user_id'])
        # ✅ reference_id is now a string, no conversion needed
        
        # Handle datetime conversion
        if 'created_at' in data:
            if isinstance(data['created_at'], str):
                # Handle both ISO format with and without Z suffix
                created_at_str = data['created_at']
                if created_at_str.endswith('Z'):
                    created_at_str = created_at_str[:-1] + '+00:00'
                try:
                    data['created_at'] = datetime.fromisoformat(created_at_str)
                except ValueError:
                    # Fallback for any other datetime format issues
                    data['created_at'] = datetime.utcnow()
            elif not isinstance(data['created_at'], datetime):
                data['created_at'] = datetime.utcnow()
        else:
            data['created_at'] = datetime.utcnow()
        
        # Ensure metadata is a dict
        if not isinstance(data.get('metadata'), dict):
            data['metadata'] = {}
        
        return cls(**data)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for database storage"""
        data = self.dict()
        
        # Convert UUIDs to strings for database storage
        data['id'] = str(data['id'])
        data['user_id'] = str(data['user_id'])
        # ✅ reference_id is already a string, no conversion needed
        
        # Convert datetime to ISO string
        data['created_at'] = data['created_at'].isoformat()
        
        return data
    
    @property
    def is_credit_adding(self) -> bool:
        """Check if this transaction adds credits"""
        return self.credit_amount > 0
    
    @property
    def is_credit_deducting(self) -> bool:
        """Check if this transaction deducts credits"""
        return self.credit_amount < 0
    
    @property
    def effective_amount(self) -> int:
        """Get the absolute amount of credits affected"""
        return abs(self.credit_amount)


class CreditBalance(BaseModel):
    """Current credit balance information"""
    user_id: UUID
    credits_remaining: int
    last_updated: datetime
    last_transaction_id: Optional[UUID] = None
    
    def can_afford(self, cost: int) -> bool:
        """Check if user can afford a given cost"""
        return self.credits_remaining >= cost
    
    def after_deduction(self, amount: int) -> int:
        """Calculate balance after deduction"""
        return max(0, self.credits_remaining - amount)
    
    def after_addition(self, amount: int) -> int:
        """Calculate balance after addition"""
        return self.credits_remaining + amount
    
    @classmethod
    def from_user_profile(cls, user_profile: Dict[str, Any]) -> "CreditBalance":
        """Create CreditBalance from user profile data"""
        return cls(
            user_id=UUID(user_profile["id"]),
            credits_remaining=user_profile.get("credits_remaining", 0),
            last_updated=datetime.utcnow(),
            last_transaction_id=None
        )


class CheckoutSession(BaseModel):
    """Represents a Stripe checkout session for credit purchases"""
    session_id: str
    checkout_url: str
    package: CreditPackage
    expires_at: datetime
    customer_id: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    @property
    def is_expired(self) -> bool:
        """Check if the checkout session has expired"""
        return datetime.utcnow() > self.expires_at
    
    @property
    def time_remaining(self) -> timedelta:
        """Get time remaining before expiration"""
        return self.expires_at - datetime.utcnow()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses"""
        return {
            "session_id": self.session_id,
            "checkout_url": self.checkout_url,
            "package": {
                "key": self.package.key,
                "name": self.package.name,
                "credits": self.package.credits,
                "price_cents": self.package.price_cents,
                "price_usd": self.package.price_usd
            },
            "expires_at": self.expires_at.isoformat(),
            "customer_id": self.customer_id,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat()
        }


class PaymentIntent(BaseModel):
    """Represents a payment intent for credit purchases"""
    id: UUID
    user_id: UUID
    package_key: str
    credit_amount: int
    usd_amount: float
    usd_per_credit: float
    stripe_session_id: Optional[str] = None
    stripe_payment_intent_id: Optional[str] = None
    status: str  # pending, completed, failed, cancelled
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    @validator('status')
    def validate_status(cls, v):
        valid_statuses = {"pending", "completed", "failed", "cancelled"}
        if v not in valid_statuses:
            raise ValueError(f"Invalid status. Must be one of: {valid_statuses}")
        return v
    
    def is_completed(self) -> bool:
        return self.status == "completed"
    
    def is_pending(self) -> bool:
        return self.status == "pending"
    
    def is_failed(self) -> bool:
        return self.status == "failed"
    
    def is_cancelled(self) -> bool:
        return self.status == "cancelled"


class BillingSummary(BaseModel):
    """Summary of billing information for a user"""
    user_id: UUID
    current_balance: int
    total_purchased: int
    total_used: int
    total_refunded: int
    total_bonus: int
    total_transactions: int
    transaction_breakdown: Dict[str, int] = Field(default_factory=dict)
    last_purchase_date: Optional[datetime] = None
    last_usage_date: Optional[datetime] = None
    
    @classmethod
    def from_transactions(
        cls, 
        user_id: UUID, 
        transactions: List[TransactionRecord], 
        current_balance: int
    ) -> "BillingSummary":
        """Create summary from list of transactions"""
        summary = cls(
            user_id=user_id,
            current_balance=current_balance,
            total_purchased=0,
            total_used=0,
            total_refunded=0,
            total_bonus=0,
            total_transactions=len(transactions),
            transaction_breakdown={}
        )
        
        for txn in transactions:
            # Count by type
            summary.transaction_breakdown[txn.transaction_type] = (
                summary.transaction_breakdown.get(txn.transaction_type, 0) + 1
            )
            
            # Sum amounts by type
            if txn.transaction_type == "purchase":
                summary.total_purchased += txn.credit_amount
                if not summary.last_purchase_date or txn.created_at > summary.last_purchase_date:
                    summary.last_purchase_date = txn.created_at
            elif txn.transaction_type == "usage":
                summary.total_used += abs(txn.credit_amount)  # Usage amounts are negative
                if not summary.last_usage_date or txn.created_at > summary.last_usage_date:
                    summary.last_usage_date = txn.created_at
            elif txn.transaction_type == "refund":
                summary.total_refunded += txn.credit_amount
            elif txn.transaction_type == "bonus":
                summary.total_bonus += txn.credit_amount
        
        return summary


class CreditUsageAnalytics(BaseModel):
    """Analytics for credit usage patterns"""
    user_id: UUID
    analysis_period_days: int
    total_credits_used: int
    total_usage_transactions: int
    average_daily_usage: float
    usage_by_day: Dict[str, int] = Field(default_factory=dict)
    peak_usage_day: Optional[str] = None
    peak_usage_amount: int = 0
    
    @classmethod
    def from_transactions(
        cls,
        user_id: UUID,
        usage_transactions: List[TransactionRecord],
        analysis_days: int = 30
    ) -> "CreditUsageAnalytics":
        """Create analytics from usage transactions"""
        if not usage_transactions:
            return cls(
                user_id=user_id,
                analysis_period_days=analysis_days,
                total_credits_used=0,
                total_usage_transactions=0,
                average_daily_usage=0.0
            )
        
        # Calculate usage by day
        usage_by_day = {}
        total_used = 0
        
        for txn in usage_transactions:
            day_key = txn.created_at.strftime('%Y-%m-%d')
            amount = abs(txn.credit_amount)  # Usage amounts are negative
            usage_by_day[day_key] = usage_by_day.get(day_key, 0) + amount
            total_used += amount
        
        # Find peak usage day
        peak_day = None
        peak_amount = 0
        if usage_by_day:
            peak_day = max(usage_by_day.keys(), key=lambda k: usage_by_day[k])
            peak_amount = usage_by_day[peak_day]
        
        # Calculate average daily usage
        avg_daily = total_used / analysis_days if analysis_days > 0 else 0.0
        
        return cls(
            user_id=user_id,
            analysis_period_days=analysis_days,
            total_credits_used=total_used,
            total_usage_transactions=len(usage_transactions),
            average_daily_usage=round(avg_daily, 2),
            usage_by_day=usage_by_day,
            peak_usage_day=peak_day,
            peak_usage_amount=peak_amount
        )


class BillingHistory(BaseModel):
    """Complete billing history for a user"""
    user_id: UUID
    transactions: List[TransactionRecord]
    current_balance: int
    total_spent_usd: float = 0.0
    total_credits_purchased: int = 0
    total_credits_used: int = 0
    summary: Optional[BillingSummary] = None
    analytics: Optional[CreditUsageAnalytics] = None
    
    @classmethod
    def from_transactions(
        cls,
        user_id: UUID,
        transactions: List[TransactionRecord],
        current_balance: int
    ) -> "BillingHistory":
        """Create billing history from transactions"""
        # Calculate totals
        total_spent = sum(
            txn.usd_amount for txn in transactions 
            if txn.transaction_type == "purchase" and txn.usd_amount
        )
        total_purchased = sum(
            txn.credit_amount for txn in transactions 
            if txn.transaction_type == "purchase"
        )
        total_used = sum(
            abs(txn.credit_amount) for txn in transactions 
            if txn.transaction_type == "usage"
        )
        
        # Create summary and analytics
        summary = BillingSummary.from_transactions(user_id, transactions, current_balance)
        
        usage_transactions = [txn for txn in transactions if txn.transaction_type == "usage"]
        analytics = CreditUsageAnalytics.from_transactions(user_id, usage_transactions)
        
        return cls(
            user_id=user_id,
            transactions=transactions,
            current_balance=current_balance,
            total_spent_usd=round(total_spent, 2),
            total_credits_purchased=total_purchased,
            total_credits_used=total_used,
            summary=summary,
            analytics=analytics
        )
    
    def get_recent_transactions(self, limit: int = 10) -> List[TransactionRecord]:
        """Get most recent transactions"""
        return sorted(self.transactions, key=lambda x: x.created_at, reverse=True)[:limit]
    
    def get_transactions_by_type(self, transaction_type: str) -> List[TransactionRecord]:
        """Get transactions of a specific type"""
        return [txn for txn in self.transactions if txn.transaction_type == transaction_type]
    
    def get_spending_by_month(self) -> Dict[str, float]:
        """Get spending grouped by month"""
        monthly_spending = {}
        for txn in self.transactions:
            if txn.transaction_type == "purchase" and txn.usd_amount:
                month_key = txn.created_at.strftime('%Y-%m')
                monthly_spending[month_key] = monthly_spending.get(month_key, 0.0) + txn.usd_amount
        return monthly_spending


class WebhookEvent(BaseModel):
    """Represents a processed webhook event"""
    event_id: str
    event_type: str
    processed_at: datetime
    success: bool
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    retry_count: int = 0
    
    @property
    def is_successful(self) -> bool:
        """Check if the webhook was processed successfully"""
        return self.success and self.error is None
    
    @property
    def is_failed(self) -> bool:
        """Check if the webhook processing failed"""
        return not self.success or self.error is not None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/storage"""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "processed_at": self.processed_at.isoformat(),
            "success": self.success,
            "result": self.result,
            "error": self.error,
            "retry_count": self.retry_count
        }


# Utility models for API responses
class CreditBalanceResponse(BaseModel):
    """API response for credit balance queries"""
    user_id: UUID
    credits_remaining: int
    last_updated: str
    can_afford: Optional[Dict[str, bool]] = None
    
    @classmethod
    def from_balance(cls, balance: CreditBalance, check_costs: Dict[str, int] = None) -> "CreditBalanceResponse":
        """Create response from CreditBalance model"""
        affordability = {}
        if check_costs:
            affordability = {
                operation: balance.can_afford(cost)
                for operation, cost in check_costs.items()
            }
        
        return cls(
            user_id=balance.user_id,
            credits_remaining=balance.credits_remaining,
            last_updated=balance.last_updated.isoformat(),
            can_afford=affordability if affordability else None
        )


class TransactionResponse(BaseModel):
    """API response for transaction operations"""
    transaction_id: UUID
    user_id: UUID
    transaction_type: str
    credit_amount: int
    new_balance: int
    description: str
    created_at: str
    
    @classmethod
    def from_transaction(cls, transaction: TransactionRecord) -> "TransactionResponse":
        """Create response from TransactionRecord"""
        return cls(
            transaction_id=transaction.id,
            user_id=transaction.user_id,
            transaction_type=transaction.transaction_type,
            credit_amount=transaction.credit_amount,
            new_balance=transaction.credit_balance_after,
            description=transaction.description,
            created_at=transaction.created_at.isoformat()
        )


class CheckoutSessionResponse(BaseModel):
    """API response for checkout session creation"""
    session_id: str
    checkout_url: str
    expires_at: str
    package_info: Dict[str, Any]
    
    @classmethod
    def from_checkout_session(cls, session: CheckoutSession) -> "CheckoutSessionResponse":
        """Create response from CheckoutSession"""
        return cls(
            session_id=session.session_id,
            checkout_url=session.checkout_url,
            expires_at=session.expires_at.isoformat(),
            package_info={
                "key": session.package.key,
                "name": session.package.name,
                "credits": session.package.credits,
                "price_usd": session.package.price_usd
            }
        )