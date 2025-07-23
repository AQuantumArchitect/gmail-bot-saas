"""
Custom exception classes for the application
"""


class ValidationError(Exception):
    """Raised when validation fails"""
    pass


class NotFoundError(Exception):
    """Raised when a resource is not found"""
    pass


class InsufficientCreditsError(Exception):
    """Raised when user has insufficient credits"""
    def __init__(self, message, balance=None, requested=None):
        super().__init__(message)
        self.balance = balance
        self.requested = requested


class AuthenticationError(Exception):
    """Raised when authentication fails"""
    pass


class RateLimitError(Exception):
    """Raised when rate limit is exceeded"""
    pass


class APIError(Exception):
    """Raised when API calls fail"""
    pass