# tests/conftest.py
"""
Test configuration and shared fixtures.
Extended to support comprehensive testing while maintaining backward compatibility.
"""
import pytest
import asyncio
from typing import Dict, Any, Optional, List
from unittest.mock import MagicMock, AsyncMock
from uuid import uuid4, UUID
from datetime import datetime, timedelta

from app.core.config import Settings

# === EXISTING FIXTURES (PRESERVED) ===

@pytest.fixture(scope="session")
def test_settings() -> Settings:
    """
    Provides a Settings object configured specifically for the test suite.

    This is the single source of truth for all test configurations. It
    explicitly loads from `.env.test` to ensure tests are isolated from
    development and production environments.
    """
    return Settings(_env_file=".env.test")

@pytest.fixture(scope="session")
def db_client(test_settings: Settings):
    """
    Provide a singleton Database instance for repository tests, configured
    with the test settings.
    """
    # This assumes your database client can be configured with a URL and key.
    # The actual implementation might vary based on your database.py file.
    from app.data.database import db
    
    # Re-initialize the db client with test-specific settings if necessary
    # For now, we assume it implicitly uses the loaded env vars.
    return db

# === NEW FIXTURES (ADDITIVE) ===

@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

# --- Enhanced Data Fixtures ---

@pytest.fixture
def sample_user_id() -> str:
    """Provides a consistent user ID for testing."""
    return str(uuid4())

@pytest.fixture
def sample_user_uuid() -> UUID:
    """Provides a consistent user UUID for testing."""
    return uuid4()

@pytest.fixture
def sample_user_data() -> Dict[str, Any]:
    """Provides comprehensive sample user data."""
    user_id = str(uuid4())
    return {
        "user_id": user_id,
        "email": "test@example.com",
        "display_name": "Test User",
        "credits_remaining": 100,
        "bot_enabled": True,
        "timezone": "UTC",
        "created_at": "2025-01-01T00:00:00Z",
        "last_login": "2025-01-30T10:00:00Z",
        "email_verified": True,
        "subscription_tier": "basic"
    }

@pytest.fixture
def sample_user_context(sample_user_data: Dict[str, Any]):
    """Provides a comprehensive UserContext for testing."""
    # Only import if needed to avoid circular imports
    try:
        from app.api.dependencies import UserContext
        
        permissions = {
            "can_process_emails": True,
            "can_access_dashboard": True,
            "can_connect_gmail": True,
            "can_purchase_credits": True,
            "can_manage_account": True
        }
        
        context = UserContext(user_data=sample_user_data, permissions=permissions)
        context._raw_user_data = sample_user_data  # For logout functionality
        return context
    except ImportError:
        # Fallback if UserContext not available
        return sample_user_data

# --- Billing-Specific Fixtures ---

@pytest.fixture
def sample_credit_packages() -> List[Dict[str, Any]]:
    """Provides sample credit packages for testing."""
    return [
        {
            "key": "starter",
            "name": "Starter Pack",
            "credits": 10,
            "price_cents": 500,
            "price_usd": 5.00,
            "price_per_credit": 0.50,
            "popular": False,
            "savings_percent": None
        },
        {
            "key": "popular",
            "name": "Popular Pack",
            "credits": 50,
            "price_cents": 2000,
            "price_usd": 20.00,
            "price_per_credit": 0.40,
            "popular": True,
            "savings_percent": 20.0
        },
        {
            "key": "enterprise",
            "name": "Enterprise Pack",
            "credits": 200,
            "price_cents": 6000,
            "price_usd": 60.00,
            "price_per_credit": 0.30,
            "popular": False,
            "savings_percent": 40.0
        }
    ]

@pytest.fixture
def sample_credit_package():
    """Provides a sample CreditPackage object."""
    try:
        from app.core.config import CreditPackage
        return CreditPackage(
            key="popular",
            name="Popular Pack",
            credits=50,
            price_cents=2000,
            popular=True
        )
    except ImportError:
        # Fallback dict if CreditPackage not available
        return {
            "key": "popular",
            "name": "Popular Pack",
            "credits": 50,
            "price_cents": 2000,
            "popular": True
        }

# --- Mock Service Fixtures (Optional - only if models exist) ---

@pytest.fixture
def mock_billing_service() -> MagicMock:
    """Provides a comprehensive mock BillingService."""
    service = MagicMock()
    
    # Status methods
    service.get_billing_status = MagicMock(return_value={
        "stripe_enabled": True,
        "status": "healthy",
        "packages_available": 3,
        "supported_currencies": ["USD"]
    })
    service.get_service_health = AsyncMock(return_value={
        "overall_status": "healthy",
        "stripe_connection": "active",
        "database_connection": "active"
    })
    
    # Package methods
    service.get_packages_with_savings = MagicMock()
    
    # Balance and transaction methods
    service.get_credit_balance = AsyncMock()
    service.get_billing_history = AsyncMock()
    service.get_user_spending_summary = AsyncMock()
    service.get_transaction_by_id = AsyncMock()
    
    # Purchase methods
    service.create_checkout_session = AsyncMock()
    service.create_billing_portal_session = AsyncMock()
    
    # Webhook methods
    service.process_stripe_webhook = AsyncMock()
    
    return service

@pytest.fixture
def mock_auth_service() -> MagicMock:
    """Provides a comprehensive mock AuthService."""
    service = MagicMock()
    
    # Token methods
    service.validate_jwt_token = MagicMock()
    service._decode_jwt_token = MagicMock()
    service.refresh_jwt_token = MagicMock()
    
    # User profile methods
    service.get_or_create_user_profile = MagicMock()
    service.create_user_profile = MagicMock()
    service.update_user_profile = MagicMock()
    
    # Session methods
    service.create_user_session = MagicMock()
    service.get_user_sessions = MagicMock()
    service.invalidate_user_session = MagicMock()
    service.invalidate_all_user_sessions = AsyncMock()
    
    # Audit methods
    service.audit_log_authentication = MagicMock()
    service.get_user_audit_logs = MagicMock()
    service.get_auth_statistics = MagicMock()
    
    return service

@pytest.fixture
def mock_user_service() -> MagicMock:
    """Provides a comprehensive mock UserService."""
    service = MagicMock()
    
    service.get_user_profile = AsyncMock()
    service.create_user_profile = AsyncMock()
    service.update_user_profile = AsyncMock()
    service.delete_user_profile = AsyncMock()
    service.get_user_preferences = AsyncMock()
    service.update_user_preferences = AsyncMock()
    service.get_user_email_statistics = AsyncMock()
    service.get_user_recent_activity = AsyncMock()
    service.get_user_credit_statistics = AsyncMock()
    service.get_user_usage_statistics = AsyncMock()
    
    return service

@pytest.fixture
def mock_gmail_service() -> MagicMock:
    """Provides a comprehensive mock GmailService."""
    service = MagicMock()
    
    service.get_connection_status = AsyncMock()
    service.get_user_gmail_statistics = AsyncMock()
    service.get_user_processed_emails = AsyncMock()
    service.get_email_by_message_id = AsyncMock()
    service.check_service_health = AsyncMock()
    
    return service

@pytest.fixture
def mock_gmail_oauth_service() -> MagicMock:
    """Provides a comprehensive mock GmailOAuthService."""
    service = MagicMock()
    
    service.generate_oauth_url = AsyncMock()
    service.complete_oauth_flow = AsyncMock()
    service.revoke_connection = AsyncMock()
    service.refresh_access_token = AsyncMock()
    
    return service

@pytest.fixture
def mock_email_service() -> MagicMock:
    """Provides a comprehensive mock EmailService."""
    service = MagicMock()
    
    service.process_user_emails = AsyncMock()
    service.process_single_email = AsyncMock()
    
    return service

# --- Billing Model Fixtures (Safe imports) ---

@pytest.fixture
def sample_credit_balance(sample_user_uuid: UUID):
    """Provides a sample CreditBalance object."""
    try:
        from app.models.billing import CreditBalance
        return CreditBalance(
            user_id=sample_user_uuid,
            credits_remaining=100,
            last_updated=datetime.utcnow()
        )
    except ImportError:
        # Fallback dict if model not available
        return {
            "user_id": sample_user_uuid,
            "credits_remaining": 100,
            "last_updated": datetime.utcnow().isoformat()
        }

@pytest.fixture
def sample_transaction_record(sample_user_uuid: UUID):
    """Provides a sample TransactionRecord object."""
    try:
        from app.models.billing import TransactionRecord
        return TransactionRecord(
            id=uuid4(),
            user_id=sample_user_uuid,
            transaction_type="purchase",
            credit_amount=50,
            credit_balance_after=100,
            description="Credit purchase",
            usd_amount=20.00,
            usd_per_credit=0.40,
            created_at=datetime.utcnow()
        )
    except ImportError:
        # Fallback dict if model not available
        return {
            "id": str(uuid4()),
            "user_id": str(sample_user_uuid),
            "transaction_type": "purchase",
            "credit_amount": 50,
            "credit_balance_after": 100,
            "description": "Credit purchase",
            "usd_amount": 20.00,
            "usd_per_credit": 0.40,
            "created_at": datetime.utcnow().isoformat()
        }

@pytest.fixture
def sample_checkout_session(sample_user_uuid: UUID, sample_credit_package):
    """Provides a sample CheckoutSession object."""
    try:
        from app.models.billing import CheckoutSession
        return CheckoutSession(
            session_id="cs_test_123",
            checkout_url="https://checkout.stripe.com/pay/cs_test_123",
            package=sample_credit_package,
            user_id=sample_user_uuid,
            customer_id="cus_test_123",
            expires_at=datetime.utcnow() + timedelta(hours=1),
            created_at=datetime.utcnow()
        )
    except ImportError:
        # Fallback dict if model not available
        return {
            "session_id": "cs_test_123",
            "checkout_url": "https://checkout.stripe.com/pay/cs_test_123",
            "package_key": "popular",
            "user_id": str(sample_user_uuid),
            "customer_id": "cus_test_123",
            "expires_at": (datetime.utcnow() + timedelta(hours=1)).isoformat(),
            "created_at": datetime.utcnow().isoformat()
        }

@pytest.fixture
def sample_billing_history(sample_user_uuid: UUID, sample_transaction_record):
    """Provides a sample BillingHistory object."""
    try:
        from app.models.billing import BillingHistory
        transactions = [sample_transaction_record] if hasattr(sample_transaction_record, 'id') else []
        return BillingHistory(
            user_id=sample_user_uuid,
            transactions=transactions,
            current_balance=100,
            total_credits_purchased=50,
            total_credits_used=0,
            total_spent_usd=20.00
        )
    except ImportError:
        # Fallback dict if model not available
        return {
            "user_id": str(sample_user_uuid),
            "transactions": [sample_transaction_record],
            "current_balance": 100,
            "total_credits_purchased": 50,
            "total_credits_used": 0,
            "total_spent_usd": 20.00
        }

@pytest.fixture
def sample_webhook_event():
    """Provides a sample WebhookEvent object."""
    try:
        from app.models.billing import WebhookEvent
        return WebhookEvent(
            event_id="evt_test_123",
            event_type="checkout.session.completed",
            processed_at=datetime.utcnow(),
            success=True,
            result={"credits_added": 50},
            error=None
        )
    except ImportError:
        # Fallback dict if model not available
        return {
            "event_id": "evt_test_123",
            "event_type": "checkout.session.completed",
            "processed_at": datetime.utcnow().isoformat(),
            "success": True,
            "result": {"credits_added": 50},
            "error": None
        }

# --- Utility Functions ---

def assert_api_error_response(response, expected_status: int, expected_error_type: Optional[str] = None):
    """Helper function to assert API error response structure."""
    assert response.status_code == expected_status
    
    if expected_status >= 400:
        data = response.json()
        if isinstance(data.get("detail"), dict):
            # Structured error response
            assert "error" in data["detail"]
            assert "message" in data["detail"]
            if expected_error_type:
                assert data["detail"]["error"] == expected_error_type
        else:
            # Simple error response
            assert "detail" in data

def assert_successful_api_response(response, expected_fields: Optional[List[str]] = None):
    """Helper function to assert successful API response structure."""
    assert response.status_code == 200
    data = response.json()
    
    if expected_fields:
        for field in expected_fields:
            assert field in data, f"Expected field '{field}' not found in response"

# --- Environment Setup ---

@pytest.fixture
def test_environment_vars(monkeypatch):
    """Sets up test environment variables."""
    env_vars = {
        "ENVIRONMENT": "testing",
        "DATABASE_URL": "sqlite:///:memory:",
        "GOOGLE_CLIENT_ID": "test_google_client_id",
        "GOOGLE_CLIENT_SECRET": "test_google_client_secret",
        "ANTHROPIC_API_KEY": "test_anthropic_key",
        "STRIPE_SECRET_KEY": "sk_test_123",
        "WEBAPP_URL": "http://localhost:3000",
        "JWT_SECRET": "test_jwt_secret",
        "ENABLE_STRIPE": "false",
        "DEBUG_MODE": "true"
    }
    
    for key, value in env_vars.items():
        monkeypatch.setenv(key, value)
    
    return env_vars

# --- Cleanup ---

@pytest.fixture(autouse=True)
def cleanup_after_test():
    """Automatic cleanup after each test."""
    yield
    # Add any cleanup logic here if needed
    pass

# === PYTEST CONFIGURATION ===

def pytest_configure(config):
    """Configure pytest with custom markers and settings."""
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line(
        "markers", "integration: marks tests as integration tests"
    )
    config.addinivalue_line(
        "markers", "unit: marks tests as unit tests"
    )
    config.addinivalue_line(
        "markers", "billing: marks tests as billing-related"
    )
    config.addinivalue_line(
        "markers", "auth: marks tests as authentication-related"
    )