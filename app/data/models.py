# app/models.py
"""
Core domain models for the Email Bot SaaS application.
This file contains all Pydantic models used across the system, organized by domain.
Models are designed for validation, serialization, and business rule enforcement.
Follows best practices: UUID-first, enum usage, and comprehensive validation.
"""

from pydantic import BaseModel, Field, EmailStr, validator
from uuid import UUID, uuid4
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


# ========== SHARED ENUMS ==========

class JobStatus(Enum):
    """Job status enumeration"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRYING = "retrying"


class JobType(Enum):
    """Job type enumeration"""
    EMAIL_PROCESSING = "email_processing"
    TEXT_PROCESSING = "text_processing"  # Future expansion
    VOICE_PROCESSING = "voice_processing"  # Future expansion
    DATA_SYNC = "data_sync"
    BATCH_PROCESSING = "batch_processing"


class JobPriority(Enum):
    """Job priority enumeration"""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class EmailStatus(Enum):
    """Email processing status enumeration"""
    DISCOVERED = "discovered"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"


# ========== USER DOMAIN MODELS ==========

class EmailFilters(BaseModel):
    """User email filtering preferences"""
    exclude_senders: List[str] = Field(default_factory=list)
    exclude_domains: List[str] = Field(default_factory=lambda: ["noreply@", "no-reply@"])
    include_keywords: List[str] = Field(default_factory=list)
    exclude_keywords: List[str] = Field(default_factory=lambda: ["unsubscribe", "marketing"])
    min_email_length: int = Field(100, ge=0)
    max_emails_per_batch: int = Field(5, ge=1)


class AIPreferences(BaseModel):
    """User AI processing preferences"""
    summary_style: str = Field("concise", pattern="^(concise|detailed|bullet_points)$")
    summary_length: str = Field("medium", pattern="^(short|medium|long)$")
    include_action_items: bool = True
    include_sentiment: bool = False
    language: str = Field("en", pattern="^[a-z]{2}$")


class UserSettings(BaseModel):
    """User settings and preferences"""
    user_id: UUID
    email: EmailStr
    display_name: Optional[str] = None
    timezone: str = Field("UTC", pattern="^(UTC|[A-Z][a-z]+/[A-Z][a-z]+)$")
    bot_enabled: bool = False
    processing_frequency_minutes: int = Field(1440, ge=60)  # Daily default
    last_processed_at: Optional[datetime] = None
    email_filters: EmailFilters = Field(default_factory=EmailFilters)
    ai_preferences: AIPreferences = Field(default_factory=AIPreferences)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @validator('timezone')
    def validate_timezone(cls, v):
        # Add more validation if needed, but pattern covers basics
        return v


# ========== BILLING DOMAIN MODELS ==========

class TransactionType(Enum):
    """Transaction type enumeration"""
    PURCHASE = "purchase"
    USAGE = "usage"
    REFUND = "refund"
    BONUS = "bonus"
    ADJUSTMENT = "adjustment"


class TransactionRecord(BaseModel):
    """Credit transaction record"""
    id: UUID = Field(default_factory=uuid4)
    user_id: UUID
    transaction_type: TransactionType
    credit_amount: int
    credit_balance_after: int = Field(..., ge=0)
    description: str
    reference_id: Optional[str] = None
    reference_type: Optional[str] = None
    usd_amount: Optional[float] = None
    usd_per_credit: Optional[float] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @validator('credit_amount')
    def validate_credit_amount(cls, v, values):
        t_type = values.get('transaction_type')
        if t_type == TransactionType.USAGE and v >= 0:
            raise ValueError("Usage transactions must have negative credit amounts")
        if t_type in [TransactionType.PURCHASE, TransactionType.BONUS, TransactionType.REFUND] and v <= 0:
            raise ValueError(f"{t_type.value} transactions must have positive credit amounts")
        return v


class BillingSummary(BaseModel):
    """User billing summary"""
    user_id: UUID
    current_balance: int = Field(..., ge=0)
    total_purchased: int
    total_used: int
    total_transactions: int
    last_purchase_date: Optional[datetime] = None
    last_usage_date: Optional[datetime] = None


# ========== EMAIL DOMAIN MODELS ==========

class EmailRecord(BaseModel):
    """Email processing record"""
    id: UUID = Field(default_factory=uuid4)
    user_id: UUID
    message_id: str = Field(..., min_length=1)
    subject: str
    sender: EmailStr
    received_at: datetime
    status: EmailStatus = EmailStatus.DISCOVERED
    processing_attempts: int = Field(0, ge=0)
    processing_result: Dict[str, Any] = Field(default_factory=dict)
    credits_used: int = Field(0, ge=0)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ProcessingStats(BaseModel):
    """Email processing statistics"""
    user_id: UUID
    total_discovered: int
    total_processed: int
    total_successful: int
    total_failed: int
    success_rate: float = Field(..., ge=0.0, le=1.0)
    total_credits_used: int
    average_processing_time: float


# ========== GMAIL DOMAIN MODELS ==========

class GmailConnectionStatus(Enum):
    """Gmail connection status"""
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    EXPIRED = "expired"
    REVOKED = "revoked"
    ERROR = "error"


class GmailConnection(BaseModel):
    """Gmail OAuth connection"""
    id: UUID = Field(default_factory=uuid4)
    user_id: UUID
    email_address: EmailStr
    access_token: str  # Encrypted in repo
    refresh_token: str  # Encrypted in repo
    expires_at: datetime
    status: GmailConnectionStatus = GmailConnectionStatus.CONNECTED
    scopes: List[str] = Field(..., min_items=1)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ========== JOB DOMAIN MODELS ==========

class JobRecord(BaseModel):
    """Background job record"""
    id: UUID = Field(default_factory=uuid4)
    user_id: UUID
    job_type: JobType
    status: JobStatus = JobStatus.PENDING
    priority: JobPriority = JobPriority.NORMAL
    metadata: Dict[str, Any] = Field(default_factory=dict)
    scheduled_for: datetime = Field(default_factory=datetime.utcnow)
    attempts: int = Field(0, ge=0)
    max_retries: int = Field(3, ge=0)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    failed_at: Optional[datetime] = None
    result: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)