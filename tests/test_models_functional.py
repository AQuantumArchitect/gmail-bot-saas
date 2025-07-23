# tests/test_models_functional.py
"""
Functional tests for app/data/models.py
Tests Pydantic models for validation and structure
"""
import pytest
from uuid import uuid4, UUID
from datetime import datetime
from pydantic import ValidationError as PydanticValidationError

from app.data.models import (
    UserCreate, UserInDB, UserStats,
    GmailOAuthTokens, GmailConnectionInfo,
    CreditTransactionCreate, CreditTransaction,
    BillingSummary, UsageAnalytics
)


class TestUserModels:
    """Test user-related models"""
    
    def test_user_create_minimal(self):
        """Test UserCreate with minimal required fields"""
        user_data = {
            "auth_id": "auth-123",
            "email": "test@example.com"
        }
        
        user = UserCreate(**user_data)
        assert user.auth_id == "auth-123"
        assert user.email == "test@example.com"
        assert user.credits_remaining == 100  # Default value
        assert user.bot_enabled is False  # Default value
        assert user.processing_frequency == "daily"  # Default value
        assert user.timezone == "UTC"  # Default value
        assert user.metadata == {}  # Default value
    
    def test_user_create_full(self):
        """Test UserCreate with all fields"""
        user_data = {
            "auth_id": "auth-456",
            "email": "full@example.com",
            "full_name": "Full Name",
            "credits_remaining": 500,
            "bot_enabled": True,
            "processing_frequency": "hourly",
            "timezone": "America/New_York",
            "metadata": {"plan": "premium", "source": "referral"}
        }
        
        user = UserCreate(**user_data)
        assert user.auth_id == "auth-456"
        assert user.email == "full@example.com"
        assert user.full_name == "Full Name"
        assert user.credits_remaining == 500
        assert user.bot_enabled is True
        assert user.processing_frequency == "hourly"
        assert user.timezone == "America/New_York"
        assert user.metadata == {"plan": "premium", "source": "referral"}
    
    def test_user_create_email_validation(self):
        """Test UserCreate email validation"""
        # Valid email
        user_data = {
            "auth_id": "auth-123",
            "email": "valid@example.com"
        }
        user = UserCreate(**user_data)
        assert user.email == "valid@example.com"
        
        # Invalid email should raise ValidationError
        with pytest.raises(PydanticValidationError):
            UserCreate(auth_id="auth-123", email="invalid-email")
    
    def test_user_create_missing_required_fields(self):
        """Test UserCreate with missing required fields"""
        # Missing auth_id
        with pytest.raises(PydanticValidationError):
            UserCreate(email="test@example.com")
        
        # Missing email
        with pytest.raises(PydanticValidationError):
            UserCreate(auth_id="auth-123")
    
    def test_user_in_db_model(self):
        """Test UserInDB model extends UserCreate"""
        user_id = uuid4()
        now = datetime.now()
        
        user_data = {
            "auth_id": "auth-123",
            "email": "test@example.com",
            "id": user_id,
            "created_at": now,
            "updated_at": now
        }
        
        user = UserInDB(**user_data)
        assert user.auth_id == "auth-123"
        assert user.email == "test@example.com"
        assert user.id == user_id
        assert user.created_at == now
        assert user.updated_at == now
        assert user.credits_remaining == 100  # Default from UserCreate
    
    def test_user_stats_model(self):
        """Test UserStats model"""
        user_id = uuid4()
        now = datetime.now()
        
        stats_data = {
            "user_id": user_id,
            "credits_remaining": 75,
            "emails_processed": 25,
            "last_activity": now,
            "bot_enabled": True,
            "processing_frequency": "daily"
        }
        
        stats = UserStats(**stats_data)
        assert stats.user_id == user_id
        assert stats.credits_remaining == 75
        assert stats.emails_processed == 25
        assert stats.last_activity == now
        assert stats.bot_enabled is True
        assert stats.processing_frequency == "daily"
    
    def test_user_stats_optional_fields(self):
        """Test UserStats with optional fields"""
        user_id = uuid4()
        
        stats_data = {
            "user_id": user_id,
            "credits_remaining": 50,
            "emails_processed": 10,
            "last_activity": None,  # Optional field
            "bot_enabled": False,
            "processing_frequency": "weekly"
        }
        
        stats = UserStats(**stats_data)
        assert stats.last_activity is None


class TestGmailModels:
    """Test Gmail-related models"""
    
    def test_gmail_oauth_tokens_model(self):
        """Test GmailOAuthTokens model"""
        token_data = {
            "access_token": "access_token_123",
            "refresh_token": "refresh_token_456",
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": "https://www.googleapis.com/auth/gmail.readonly"
        }
        
        tokens = GmailOAuthTokens(**token_data)
        assert tokens.access_token == "access_token_123"
        assert tokens.refresh_token == "refresh_token_456"
        assert tokens.token_type == "Bearer"
        assert tokens.expires_in == 3600
        assert tokens.scope == "https://www.googleapis.com/auth/gmail.readonly"
    
    def test_gmail_oauth_tokens_required_fields(self):
        """Test GmailOAuthTokens required fields"""
        # Missing access_token
        with pytest.raises(PydanticValidationError):
            GmailOAuthTokens(
                refresh_token="refresh_token",
                token_type="Bearer",
                expires_in=3600
            )
        
        # Missing refresh_token
        with pytest.raises(PydanticValidationError):
            GmailOAuthTokens(
                access_token="access_token",
                token_type="Bearer",
                expires_in=3600
            )
    
    def test_gmail_connection_info_model(self):
        """Test GmailConnectionInfo model"""
        user_id = uuid4()
        now = datetime.now()
        
        connection_data = {
            "user_id": user_id,
            "email_address": "user@gmail.com",
            "profile_info": {"name": "User Name", "picture": "profile.jpg"},
            "connection_status": "connected",
            "scopes": ["https://www.googleapis.com/auth/gmail.readonly"],
            "created_at": now,
            "updated_at": now
        }
        
        connection = GmailConnectionInfo(**connection_data)
        assert connection.user_id == user_id
        assert connection.email_address == "user@gmail.com"
        assert connection.profile_info == {"name": "User Name", "picture": "profile.jpg"}
        assert connection.connection_status == "connected"
        assert connection.scopes == ["https://www.googleapis.com/auth/gmail.readonly"]
        assert connection.created_at == now
        assert connection.updated_at == now
        assert connection.error_info is None  # Optional field
        assert connection.sync_metadata is None  # Optional field
    
    def test_gmail_connection_info_optional_fields(self):
        """Test GmailConnectionInfo with optional fields"""
        user_id = uuid4()
        now = datetime.now()
        
        connection_data = {
            "user_id": user_id,
            "email_address": "user@gmail.com",
            "profile_info": {"name": "User Name"},
            "connection_status": "error",
            "scopes": ["https://www.googleapis.com/auth/gmail.readonly"],
            "created_at": now,
            "updated_at": now,
            "error_info": {"error_type": "invalid_grant", "retry_count": 3},
            "sync_metadata": {"history_id": "12345", "last_sync": now.isoformat()}
        }
        
        connection = GmailConnectionInfo(**connection_data)
        assert connection.error_info == {"error_type": "invalid_grant", "retry_count": 3}
        assert connection.sync_metadata == {"history_id": "12345", "last_sync": now.isoformat()}


class TestBillingModels:
    """Test billing-related models"""
    
    def test_credit_transaction_create_model(self):
        """Test CreditTransactionCreate model"""
        user_id = uuid4()
        
        transaction_data = {
            "user_id": user_id,
            "amount": 100,
            "transaction_type": "purchase",
            "description": "Credit purchase",
            "stripe_payment_intent_id": "pi_123",
            "metadata": {"package": "starter", "price": 9.99}
        }
        
        transaction = CreditTransactionCreate(**transaction_data)
        assert transaction.user_id == user_id
        assert transaction.amount == 100
        assert transaction.transaction_type == "purchase"
        assert transaction.description == "Credit purchase"
        assert transaction.stripe_payment_intent_id == "pi_123"
        assert transaction.metadata == {"package": "starter", "price": 9.99}
    
    def test_credit_transaction_create_optional_fields(self):
        """Test CreditTransactionCreate with optional fields"""
        user_id = uuid4()
        
        transaction_data = {
            "user_id": user_id,
            "amount": -10,
            "transaction_type": "usage",
            "description": "Email processing"
            # stripe_payment_intent_id is optional
            # metadata has default value
        }
        
        transaction = CreditTransactionCreate(**transaction_data)
        assert transaction.stripe_payment_intent_id is None
        assert transaction.metadata == {}
    
    def test_credit_transaction_model(self):
        """Test CreditTransaction model"""
        transaction_id = uuid4()
        user_id = uuid4()
        now = datetime.now()
        
        transaction_data = {
            "id": transaction_id,
            "user_id": user_id,
            "transaction_type": "purchase",
            "credit_amount": 100,
            "credit_balance_after": 150,
            "description": "Credit purchase",
            "metadata": {"package": "starter"},
            "created_at": now
        }
        
        transaction = CreditTransaction(**transaction_data)
        assert transaction.id == transaction_id
        assert transaction.user_id == user_id
        assert transaction.transaction_type == "purchase"
        assert transaction.credit_amount == 100
        assert transaction.credit_balance_after == 150
        assert transaction.description == "Credit purchase"
        assert transaction.metadata == {"package": "starter"}
        assert transaction.created_at == now
        assert transaction.reference_id is None  # Optional field
    
    def test_billing_summary_model(self):
        """Test BillingSummary model"""
        user_id = uuid4()
        now = datetime.now()
        
        summary_data = {
            "user_id": user_id,
            "current_balance": 75,
            "total_purchased": 200,
            "total_used": 125,
            "total_transactions": 15,
            "last_purchase_date": now,
            "last_usage_date": now
        }
        
        summary = BillingSummary(**summary_data)
        assert summary.user_id == user_id
        assert summary.current_balance == 75
        assert summary.total_purchased == 200
        assert summary.total_used == 125
        assert summary.total_transactions == 15
        assert summary.last_purchase_date == now
        assert summary.last_usage_date == now
    
    def test_usage_analytics_model(self):
        """Test UsageAnalytics model"""
        user_id = uuid4()
        
        analytics_data = {
            "user_id": user_id,
            "period_days": 30,
            "total_credits_used": 50,
            "total_usage_transactions": 10,
            "average_daily_usage": 1.67,
            "usage_by_day": [
                {"date": "2024-01-01", "usage": 5},
                {"date": "2024-01-02", "usage": 3}
            ]
        }
        
        analytics = UsageAnalytics(**analytics_data)
        assert analytics.user_id == user_id
        assert analytics.period_days == 30
        assert analytics.total_credits_used == 50
        assert analytics.total_usage_transactions == 10
        assert analytics.average_daily_usage == 1.67
        assert len(analytics.usage_by_day) == 2


class TestModelValidation:
    """Test model validation features"""
    
    def test_uuid_validation(self):
        """Test UUID field validation"""
        # Valid UUID
        user_id = uuid4()
        stats_data = {
            "user_id": user_id,
            "credits_remaining": 50,
            "emails_processed": 10,
            "bot_enabled": True,
            "processing_frequency": "daily"
        }
        stats = UserStats(**stats_data)
        assert isinstance(stats.user_id, UUID)
        
        # Invalid UUID
        with pytest.raises(PydanticValidationError):
            UserStats(
                user_id="invalid-uuid",
                credits_remaining=50,
                emails_processed=10,
                bot_enabled=True,
                processing_frequency="daily"
            )
    
    def test_datetime_validation(self):
        """Test datetime field validation"""
        user_id = uuid4()
        now = datetime.now()
        
        # Valid datetime
        user_data = {
            "auth_id": "auth-123",
            "email": "test@example.com",
            "id": user_id,
            "created_at": now,
            "updated_at": now
        }
        user = UserInDB(**user_data)
        assert isinstance(user.created_at, datetime)
        assert isinstance(user.updated_at, datetime)
        
        # Invalid datetime
        with pytest.raises(PydanticValidationError):
            UserInDB(
                auth_id="auth-123",
                email="test@example.com",
                id=user_id,
                created_at="invalid-datetime",
                updated_at=now
            )
    
    def test_field_defaults(self):
        """Test default field values"""
        user = UserCreate(auth_id="auth-123", email="test@example.com")
        
        # Test defaults
        assert user.credits_remaining == 100
        assert user.bot_enabled is False
        assert user.processing_frequency == "daily"
        assert user.timezone == "UTC"
        assert user.metadata == {}
    
    def test_field_validation_errors(self):
        """Test various validation errors"""
        # Test required field missing
        with pytest.raises(PydanticValidationError) as exc_info:
            UserCreate(auth_id="auth-123")  # Missing email
        assert "email" in str(exc_info.value)
        
        # Test type validation
        with pytest.raises(PydanticValidationError) as exc_info:
            UserCreate(auth_id="auth-123", email="test@example.com", credits_remaining="not-a-number")
        assert "credits_remaining" in str(exc_info.value)
    
    def test_model_serialization(self):
        """Test model serialization"""
        user = UserCreate(
            auth_id="auth-123",
            email="test@example.com",
            full_name="Test User",
            credits_remaining=200
        )
        
        # Test dict conversion
        user_dict = user.model_dump()
        assert user_dict["auth_id"] == "auth-123"
        assert user_dict["email"] == "test@example.com"
        assert user_dict["full_name"] == "Test User"
        assert user_dict["credits_remaining"] == 200
        
        # Test JSON serialization
        user_json = user.model_dump_json()
        assert isinstance(user_json, str)
        assert "auth-123" in user_json