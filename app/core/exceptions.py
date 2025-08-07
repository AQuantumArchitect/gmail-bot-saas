# app/core/exceptions.py
"""
Enterprise-grade exception classes for the application.
Organized by domain with comprehensive error handling and context.
This is the single source of truth for all custom exceptions.
"""
from typing import List, Optional, Any, Dict


# ========== BASE EXCEPTIONS ==========

class BaseAppException(Exception):
    """Base exception class for all application exceptions"""
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


# ========== CORE SYSTEM EXCEPTIONS ==========

class ValidationError(BaseAppException):
    """Raised when validation fails"""
    def __init__(self, message: str, field: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, details)
        self.field = field


class NotFoundError(BaseAppException):
    """Raised when a resource is not found"""
    def __init__(self, message: str, resource_type: Optional[str] = None, resource_id: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, details)
        self.resource_type = resource_type
        self.resource_id = resource_id


class DatabaseError(BaseAppException):
    """Raised when database operations fail"""
    def __init__(self, message: str, operation: Optional[str] = None, table: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, details)
        self.operation = operation
        self.table = table


class DuplicateRecordError(BaseAppException):
    """Raised when attempting to create a record that already exists"""
    def __init__(self, message: str, resource_type: Optional[str] = None, resource_id: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, details)
        self.resource_type = resource_type
        self.resource_id = resource_id


class ConfigurationError(BaseAppException):
    """Raised when configuration is invalid or missing"""
    pass


# ========== AUTHENTICATION & AUTHORIZATION ==========

class AuthenticationError(BaseAppException):
    """Raised when authentication fails"""
    pass


class AuthorizationError(BaseAppException):
    """Raised when authorization fails"""
    pass


class TokenError(AuthenticationError):
    """Raised when token operations fail"""
    def __init__(self, message: str, token_type: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, details)
        self.token_type = token_type


class OAuthError(AuthenticationError):
    """Raised when OAuth operations fail"""
    def __init__(self, message: str, provider: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, details)
        self.provider = provider


# ========== API & EXTERNAL SERVICES ==========

class APIError(BaseAppException):
    """Raised when API calls fail"""
    def __init__(self, message: str, status_code: Optional[int] = None, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, details)
        self.status_code = status_code


class RateLimitError(BaseAppException):
    """Raised when rate limit is exceeded"""
    def __init__(self, message: str, retry_after: Optional[int] = None, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, details)
        self.retry_after = retry_after


class ExternalServiceError(BaseAppException):
    """Base class for external service errors"""
    def __init__(self, message: str, service: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, details)
        self.service = service


# ========== USER MANAGEMENT EXCEPTIONS ==========

class UserProfileNotFoundError(NotFoundError):
    """Raised when a user profile cannot be found"""
    def __init__(self, user_id: str):
        self.user_id = user_id
        super().__init__(f"User profile not found: {user_id}", resource_type="user_profile", resource_id=user_id)


class UserProfileExistsError(ValidationError):
    """Raised when attempting to create a user profile that already exists"""
    def __init__(self, user_id: str):
        self.user_id = user_id
        super().__init__(f"User profile already exists: {user_id}", field="user_id")


class InsufficientCreditsError(ValidationError):
    """Raised when user has insufficient credits"""
    def __init__(self, user_id: str, current_balance: int, requested: int):
        message = f"Insufficient credits: balance {current_balance}, requested {requested}"
        super().__init__(message, field="credits")
        self.user_id = user_id
        self.current_balance = current_balance
        self.requested = requested


class InvalidTimezoneError(ValidationError):
    """Raised when an invalid timezone is provided"""
    def __init__(self, timezone: str):
        message = f"Invalid timezone: {timezone}"
        super().__init__(message, field="timezone")
        self.timezone = timezone


# ========== EMAIL PROCESSING EXCEPTIONS ==========

class EmailRecordNotFoundError(NotFoundError):
    """Raised when an email record cannot be found"""
    def __init__(self, message_id: str):
        self.message_id = message_id
        super().__init__(f"Email record not found: {message_id}", resource_type="email_record", resource_id=message_id)


class EmailRecordExistsError(ValidationError):
    """Raised when attempting to create an email record that already exists"""
    def __init__(self, message_id: str):
        self.message_id = message_id
        super().__init__(f"Email record already exists: {message_id}", field="message_id")


class InvalidEmailStatusError(ValidationError):
    """Raised when an invalid email status is provided"""
    def __init__(self, status: str, valid_statuses: List[str]):
        message = f"Invalid email status: {status}. Valid statuses: {valid_statuses}"
        super().__init__(message, field="status")
        self.status = status
        self.valid_statuses = valid_statuses


# ========== JOB PROCESSING EXCEPTIONS ==========

class JobNotFoundError(Exception):
    """Job not found exception"""
    def __init__(self, job_id: str):
        self.job_id = job_id
        super().__init__(f"Job not found: {job_id}")


class JobAlreadyClaimedError(ValidationError):
    """Job already claimed exception"""
    def __init__(self, job_id: str, current_status: str):
        self.job_id = job_id
        self.current_status = current_status
        super().__init__(f"Job {job_id} already claimed with status: {current_status}")


class InvalidJobTypeError(ValidationError):
    """Invalid job type exception"""
    def __init__(self, job_type: str, valid_types: List[str]):
        self.job_type = job_type
        self.valid_types = valid_types
        super().__init__(f"Invalid job type: {job_type}. Valid types: {valid_types}")


class InvalidJobStatusError(ValidationError):
    """Invalid job status exception"""
    def __init__(self, status: str, valid_statuses: List[str]):
        self.status = status
        self.valid_statuses = valid_statuses
        super().__init__(f"Invalid job status: {status}. Valid statuses: {valid_statuses}")


class MaxRetriesExceededError(ValidationError):
    """Maximum retries exceeded exception"""
    def __init__(self, job_id: str, attempts: int, max_retries: int):
        self.job_id = job_id
        self.attempts = attempts
        self.max_retries = max_retries
        super().__init__(f"Job {job_id} exceeded max retries: {attempts}/{max_retries}")

class InvalidJobPriorityError(ValidationError):
    """Invalid job priority exception"""
    def __init__(self, priority: str, valid_priorities: List[str]):
        self.priority = priority
        self.valid_priorities = valid_priorities
        super().__init__(f"Invalid job priority: {priority}. Valid priorities: {valid_priorities}")

# ========== GMAIL INTEGRATION EXCEPTIONS ==========


class GmailConnectionExistsError(ValidationError):
    """Raised when attempting to create a Gmail connection that already exists"""
    def __init__(self, user_id: str):
        self.user_id = user_id
        super().__init__(f"Gmail connection already exists for user: {user_id}", field="user_id")


class InvalidOAuthTokensError(ValidationError):
    """Raised when OAuth tokens are invalid"""
    def __init__(self, missing_fields: List[str]):
        message = f"Invalid OAuth tokens, missing fields: {missing_fields}"
        super().__init__(message, field="oauth_tokens")
        self.missing_fields = missing_fields


class InvalidScopesError(ValidationError):
    """Raised when OAuth scopes are invalid"""
    def __init__(self, invalid_scopes: List[str]):
        message = f"Invalid OAuth scopes: {invalid_scopes}"
        super().__init__(message, field="scopes")
        self.invalid_scopes = invalid_scopes


class GmailConnectionNotFoundError(NotFoundError):
    """Gmail connection not found exception"""
    def __init__(self, user_id: str):
        self.user_id = user_id
        super().__init__(f"Gmail connection not found for user: {user_id}")


class DuplicateGmailConnectionError(DuplicateRecordError):
    """Duplicate Gmail connection exception"""
    def __init__(self, user_id: str):
        self.user_id = user_id
        super().__init__(f"Gmail connection already exists for user: {user_id}")


class SyncRecordNotFoundError(NotFoundError):
    """Sync record not found exception"""
    def __init__(self, sync_id: str):
        self.sync_id = sync_id
        super().__init__(f"Sync record not found: {sync_id}")


class ActivityRecordNotFoundError(NotFoundError):
    """Activity record not found exception"""
    def __init__(self, activity_id: str):
        self.activity_id = activity_id
        super().__init__(f"Activity record not found: {activity_id}")


class InvalidConnectionStatusError(ValidationError):
    """Invalid connection status exception"""
    def __init__(self, status: str, valid_statuses: List[str]):
        self.status = status
        self.valid_statuses = valid_statuses
        super().__init__(f"Invalid connection status '{status}'. Valid statuses: {valid_statuses}")

# ========== AUDIT & COMPLIANCE EXCEPTIONS ==========

class AuditLogNotFoundError(NotFoundError):
    """Raised when an audit log cannot be found"""
    def __init__(self, audit_id: str):
        self.audit_id = audit_id
        super().__init__(f"Audit log not found: {audit_id}", resource_type="audit_log", resource_id=audit_id)


class InvalidEventTypeError(ValidationError):
    """Raised when an invalid event type is provided"""
    def __init__(self, event_type: str, valid_types: List[str]):
        message = f"Invalid event type: {event_type}. Valid types: {valid_types}"
        super().__init__(message, field="event_type")
        self.event_type = event_type
        self.valid_types = valid_types


class InvalidSeverityLevelError(ValidationError):
    """Raised when an invalid severity level is provided"""
    def __init__(self, severity: str, valid_levels: List[str]):
        message = f"Invalid severity level: {severity}. Valid levels: {valid_levels}"
        super().__init__(message, field="severity")
        self.severity = severity
        self.valid_levels = valid_levels


class InvalidComplianceCategoryError(ValidationError):
    """Raised when an invalid compliance category is provided"""
    def __init__(self, category: str, valid_categories: List[str]):
        message = f"Invalid compliance category: {category}. Valid categories: {valid_categories}"
        super().__init__(message, field="compliance_category")
        self.category = category
        self.valid_categories = valid_categories


class AuditRetentionViolationError(ValidationError):
    """Raised when audit retention policy is violated"""
    def __init__(self, retention_days: int, log_age_days: int):
        message = f"Cannot delete audit log: retention policy requires {retention_days} days, log is {log_age_days} days old"
        super().__init__(message)
        self.retention_days = retention_days
        self.log_age_days = log_age_days


# ========== BILLING EXCEPTIONS ==========

class TransactionNotFoundError(NotFoundError):
    """Raised when a transaction cannot be found"""
    def __init__(self, transaction_id: str):
        self.transaction_id = transaction_id
        super().__init__(f"Transaction not found: {transaction_id}", resource_type="transaction", resource_id=transaction_id)


class DuplicateTransactionError(ValidationError):
    """Raised when attempting to create a duplicate transaction"""
    def __init__(self, reference_id: str):
        self.reference_id = reference_id
        super().__init__(f"Transaction already exists with reference ID: {reference_id}", field="reference_id")


class InvalidTransactionTypeError(ValidationError):
    """Raised when an invalid transaction type is used"""
    def __init__(self, transaction_type: str, valid_types: List[str]):
        valid_types_str = ", ".join(valid_types) if valid_types else "unknown"
        message = f"Invalid transaction type '{transaction_type}'. Valid types: {valid_types_str}"
        super().__init__(message, field="transaction_type")
        self.transaction_type = transaction_type
        self.valid_types = valid_types


class PaymentError(BaseAppException):
    """Raised when payment processing fails"""
    def __init__(self, message: str, payment_id: Optional[str] = None, provider: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, details)
        self.payment_id = payment_id
        self.provider = provider


# ========== LEGACY ALIASES (PRESERVED) ==========

ConnectionError = DatabaseError
QueryError = DatabaseError
