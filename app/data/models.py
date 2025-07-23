from pydantic import BaseModel, Field, EmailStr, ValidationError as PydanticError
from uuid import UUID
from typing import Optional, List, Dict, Any
from datetime import datetime


# ---- User Domain Models ----
class UserCreate(BaseModel):
    auth_id: str = Field(..., description="External auth provider ID")
    email: EmailStr
    full_name: Optional[str] = None
    credits_remaining: int = 100
    bot_enabled: bool = False
    processing_frequency: str = "daily"
    timezone: str = "UTC"
    metadata: Dict[str, Any] = Field(default_factory=dict)


class UserInDB(UserCreate):
    id: UUID
    created_at: datetime
    updated_at: datetime


class UserStats(BaseModel):
    user_id: UUID
    credits_remaining: int
    emails_processed: int
    last_activity: Optional[datetime] = None
    bot_enabled: bool
    processing_frequency: str


# ---- Gmail Domain Models ----
class GmailOAuthTokens(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int
    scope: Optional[str]


class GmailConnectionInfo(BaseModel):
    user_id: UUID
    email_address: str
    profile_info: Dict[str, Any]
    connection_status: str
    scopes: List[str]
    created_at: datetime
    updated_at: datetime
    error_info: Optional[Dict[str, Any]] = None
    sync_metadata: Optional[Dict[str, Any]] = None


# ---- Billing Domain Models ----
class CreditTransactionCreate(BaseModel):
    user_id: UUID
    amount: int
    transaction_type: str
    description: str
    stripe_payment_intent_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class CreditTransaction(BaseModel):
    id: UUID
    user_id: UUID
    transaction_type: str
    credit_amount: int
    credit_balance_after: int
    description: str
    reference_id: Optional[UUID] = None
    reference_type: Optional[str] = None
    usd_amount: Optional[float] = None
    usd_per_credit: Optional[float] = None
    metadata: Dict[str, Any]
    created_at: datetime


class BillingSummary(BaseModel):
    user_id: UUID
    current_balance: int
    total_purchased: int
    total_used: int
    total_transactions: int
    last_purchase_date: Optional[datetime]
    last_usage_date: Optional[datetime]


class UsageAnalytics(BaseModel):
    user_id: UUID
    period_days: int
    total_credits_used: int
    total_usage_transactions: int
    average_daily_usage: float
    usage_by_day: List[Dict[str, Any]]
