"""
Unified exception module for the application and billing systems.
"""


class ApplicationError(Exception):
    """Base exception for all application-level errors."""

    def __init__(self, message: str, error_code: str = None):
        self.message = message
        self.error_code = error_code
        super().__init__(message)

    def __str__(self):
        if self.error_code:
            return f"[{self.error_code}] {self.message}"
        return self.message

    def __repr__(self):
        return f"{self.__class__.__name__}(message={self.message!r}, error_code={self.error_code!r})"


class ValidationError(ApplicationError):
    """Raised when validation fails."""
    pass


class NotFoundError(ApplicationError):
    """Raised when a resource is not found."""
    pass


class AuthenticationError(ApplicationError):
    """Raised when authentication fails."""
    pass


class RateLimitError(ApplicationError):
    """Raised when rate limits are exceeded."""

    def __init__(self, retry_after: int = None):
        self.retry_after = retry_after
        message = f"Rate limit exceeded{f', retry after {retry_after}s' if retry_after else ''}"
        super().__init__(message, error_code="rate_limit_exceeded")


class APIError(ApplicationError):
    """Raised when external API calls fail."""
    pass


class APIErrorResponse:
    """
    Standardized API error response format.
    """

    def __init__(self, message: str, error_code: str = None, status_code: int = 400):
        self.message = message
        self.error_code = error_code or "api_error"
        self.status_code = status_code

    def to_dict(self):
        return {
            "error": self.error_code,
            "message": self.message,
        }


# --- Billing Exceptions ---

class BillingError(ApplicationError):
    """Base exception for billing-related errors."""
    def __init__(self, message: str, error_code: str = None):
        super().__init__(message, error_code=error_code or "billing_error")


class InsufficientCreditsError(BillingError):
    """Raised when user doesn't have enough credits."""
    def __init__(self, required: int, available: int):
        self.required = required
        self.available = available
        message = f"Insufficient credits: need {required}, have {available}"
        super().__init__(message, error_code="insufficient_credits")


class PaymentProcessingError(BillingError):
    """Raised when payment processing fails."""
    def __init__(self, message: str, provider_error: str = None):
        self.provider_error = provider_error
        super().__init__(message, error_code="payment_processing_failed")


class InvalidPackageError(BillingError):
    """Raised when an invalid credit package is selected."""
    def __init__(self, package_key: str):
        self.package_key = package_key
        message = f"Invalid credit package: '{package_key}'"
        super().__init__(message, error_code="invalid_package")


class StripeError(BillingError):
    """Raised for Stripe API-related errors."""
    def __init__(self, message: str, stripe_code: str = None, status_code: int = None):
        self.stripe_code = stripe_code
        self.status_code = status_code
        super().__init__(message, error_code="stripe_error")


class WebhookValidationError(BillingError):
    """Raised when webhook signature validation fails."""
    def __init__(self, message: str = "Webhook signature validation failed"):
        super().__init__(message, error_code="webhook_validation_failed")


class DuplicateTransactionError(BillingError):
    """Raised when attempting to create a duplicate transaction."""
    def __init__(self, reference_id: str):
        self.reference_id = reference_id
        message = f"Duplicate transaction with reference ID: {reference_id}"
        super().__init__(message, error_code="duplicate_transaction")


class BillingConfigurationError(BillingError):
    """Raised when billing system is misconfigured."""
    def __init__(self, message: str):
        super().__init__(message, error_code="configuration_error")


class TransactionNotFoundError(BillingError):
    """Raised when a requested transaction cannot be found."""
    def __init__(self, transaction_id: str):
        self.transaction_id = transaction_id
        message = f"Transaction not found: {transaction_id}"
        super().__init__(message, error_code="transaction_not_found")


class InvalidTransactionTypeError(BillingError):
    """Raised when an invalid transaction type is used."""
    def __init__(self, transaction_type: str):
        self.transaction_type = transaction_type
        valid_types = ["purchase", "usage", "refund", "bonus", "adjustment"]
        message = f"Invalid transaction type '{transaction_type}'. Valid types: {valid_types}"
        super().__init__(message, error_code="invalid_transaction_type")


class CreditBalanceError(BillingError):
    """Raised when there's an error with credit balance operations."""
    def __init__(self, message: str, user_id: str = None):
        self.user_id = user_id
        super().__init__(message, error_code="credit_balance_error")


class BillingServiceUnavailableError(BillingError):
    """Raised when billing service is temporarily unavailable."""
    def __init__(self, message: str = "Billing service temporarily unavailable"):
        super().__init__(message, error_code="service_unavailable")


# Optional: HTTP status mapping if needed in REST layer
EXCEPTION_HTTP_STATUS_MAP = {
    ValidationError: 400,
    NotFoundError: 404,
    AuthenticationError: 401,
    RateLimitError: 429,
    APIError: 502,
    InsufficientCreditsError: 402,
    PaymentProcessingError: 402,
    InvalidPackageError: 404,
    StripeError: 500,
    WebhookValidationError: 400,
    DuplicateTransactionError: 409,
    BillingConfigurationError: 500,
    TransactionNotFoundError: 404,
    InvalidTransactionTypeError: 400,
    CreditBalanceError: 500,
    BillingServiceUnavailableError: 503,
    BillingError: 500,
    ApplicationError: 500,
}

def get_http_status_for_exception(exc: ApplicationError) -> int:
    return EXCEPTION_HTTP_STATUS_MAP.get(type(exc), 500)
