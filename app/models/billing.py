# app/models/billing.py
"""
Billing domain models for transaction records, checkout sessions, and billing history.
Provides strongly-typed models for billing operations.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID
from app.core.billing_config import CreditPackage

@dataclass
class TransactionRecord:
    """Represents a billing transaction record from the database"""
    id: UUID
    user_id: UUID
    transaction_type: str
    credit_amount: int
    credit_balance_after: int
    description: str
    reference_id: Optional[UUID]
    reference_type: Optional[str]
    usd_amount: Optional[float]
    usd_per_credit: Optional[float]
    metadata: Dict[str, Any]
    created_at: datetime
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TransactionRecord":
        """Create TransactionRecord from database row dict"""
        return cls(
            id=UUID(data["id"]),
            user_id=UUID(data["user_id"]),
            transaction_type=data["transaction_type"],
            credit_amount=data["credit_amount"],
            credit_balance_after=data["credit_balance_after"],
            description=data["description"],
            reference_id=UUID(data["reference_id"]) if data.get("reference_id") else None,
            reference_type=data.get("reference_type"),
            usd_amount=float(data["usd_amount"]) if data.get("usd_amount") else None,
            usd_per_credit=float(data["usd_per_credit"]) if data.get("usd_per_credit") else None,
            metadata=data.get("metadata", {}),
            created_at=cls._parse_datetime(data["created_at"])
        )
    
    @staticmethod
    def _parse_datetime(dt_str: str) -> datetime:
        """Parse datetime string from database"""
        if dt_str.endswith('Z'):
            dt_str = dt_str[:-1] + '+00:00'
        elif '+' not in dt_str and dt_str.count(':') == 2:
            dt_str += '+00:00'
        return datetime.fromisoformat(dt_str)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "id": str(self.id),
            "user_id": str(self.user_id),
            "transaction_type": self.transaction_type,
            "credit_amount": self.credit_amount,
            "credit_balance_after": self.credit_balance_after,
            "description": self.description,
            "reference_id": str(self.reference_id) if self.reference_id else None,
            "reference_type": self.reference_type,
            "usd_amount": self.usd_amount,
            "usd_per_credit": self.usd_per_credit,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat()
        }
    
    @property
    def is_credit_addition(self) -> bool:
        """Check if this transaction adds credits"""
        return self.credit_amount > 0
    
    @property
    def is_credit_deduction(self) -> bool:
        """Check if this transaction deducts credits"""
        return self.credit_amount < 0
    
    @property
    def absolute_credit_amount(self) -> int:
        """Get absolute value of credit amount"""
        return abs(self.credit_amount)

@dataclass
class CheckoutSession:
    """Represents a Stripe checkout session"""
    session_id: str
    checkout_url: str
    package: CreditPackage
    expires_at: datetime
    customer_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    
    @property
    def is_expired(self) -> bool:
        """Check if checkout session has expired"""
        return datetime.utcnow() > self.expires_at
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "session_id": self.session_id,
            "checkout_url": self.checkout_url,
            "package": {
                "key": self.package.key,
                "name": self.package.name,
                "credits": self.package.credits,
                "price_cents": self.package.price_cents,
                "price_usd": self.package.price_usd,
                "popular": self.package.popular
            },
            "expires_at": self.expires_at.isoformat(),
            "customer_id": self.customer_id,
            "metadata": self.metadata or {}
        }

@dataclass
class BillingHistory:
    """Represents a user's complete billing history"""
    user_id: UUID
    transactions: List[TransactionRecord]
    total_transactions: int
    total_purchased: int
    total_used: int
    current_balance: int
    
    @classmethod
    def from_transactions(
        cls, 
        user_id: UUID, 
        transactions: List[TransactionRecord],
        current_balance: int
    ) -> "BillingHistory":
        """Create BillingHistory from list of transactions"""
        total_purchased = sum(
            txn.credit_amount for txn in transactions
            if txn.transaction_type in ["purchase", "bonus"] and txn.credit_amount > 0
        )
        
        total_used = sum(
            abs(txn.credit_amount) for txn in transactions
            if txn.transaction_type == "usage" and txn.credit_amount < 0
        )
        
        return cls(
            user_id=user_id,
            transactions=transactions,
            total_transactions=len(transactions),
            total_purchased=total_purchased,
            total_used=total_used,
            current_balance=current_balance
        )
    
    def get_transactions_by_type(self, transaction_type: str) -> List[TransactionRecord]:
        """Get transactions filtered by type"""
        return [txn for txn in self.transactions if txn.transaction_type == transaction_type]
    
    def get_recent_transactions(self, limit: int = 10) -> List[TransactionRecord]:
        """Get most recent transactions"""
        return sorted(self.transactions, key=lambda t: t.created_at, reverse=True)[:limit]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "user_id": str(self.user_id),
            "transactions": [txn.to_dict() for txn in self.transactions],
            "total_transactions": self.total_transactions,
            "total_purchased": self.total_purchased,
            "total_used": self.total_used,
            "current_balance": self.current_balance
        }

@dataclass
class CreditBalance:
    """Represents a user's current credit balance"""
    user_id: UUID
    credits_remaining: int
    last_transaction_at: Optional[datetime]
    last_updated: datetime
    
    @classmethod
    def from_user_profile(cls, user_profile: Dict[str, Any]) -> "CreditBalance":
        """Create CreditBalance from user profile data"""
        return cls(
            user_id=UUID(user_profile["user_id"]),
            credits_remaining=user_profile.get("credits_remaining", 0),
            last_transaction_at=None,  # Would need to be fetched separately
            last_updated=datetime.utcnow()
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "user_id": str(self.user_id),
            "credits_remaining": self.credits_remaining,
            "last_transaction_at": self.last_transaction_at.isoformat() if self.last_transaction_at else None,
            "last_updated": self.last_updated.isoformat()
        }
    
    @property
    def has_credits(self) -> bool:
        """Check if user has any credits remaining"""
        return self.credits_remaining > 0
    
    def can_afford(self, credit_cost: int) -> bool:
        """Check if user can afford a given credit cost"""
        return self.credits_remaining >= credit_cost

@dataclass
class WebhookEvent:
    """Represents a processed webhook event"""
    event_id: str
    event_type: str
    processed_at: datetime
    success: bool
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "processed_at": self.processed_at.isoformat(),
            "success": self.success,
            "result": self.result,
            "error": self.error
        }