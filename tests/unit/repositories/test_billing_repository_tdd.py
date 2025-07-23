# tests/unit/repositories/test_billing_repository.py
"""
Test-first driver for BillingRepository implementation.
These tests define the credit transaction interface before the repository exists.
"""
import pytest
from uuid import uuid4
from datetime import datetime, timedelta
from decimal import Decimal
from app.data.repositories.billing_repository import BillingRepository
from app.core.exceptions import ValidationError, InsufficientCreditsError

class TestBillingRepository:
    """Test-driven development for BillingRepository"""
    
    @pytest.fixture
    def billing_repo(self):
        """Create BillingRepository instance - this doesn't exist yet!"""
        return BillingRepository()
    
    def test_create_purchase_transaction(self, billing_repo):
        """Test creating a credit purchase transaction"""
        user_id = uuid4()
        transaction_data = {
            "user_id": str(user_id),
            "amount": 100,
            "transaction_type": "purchase",
            "description": "Credit purchase - Starter Pack",
            "stripe_payment_intent_id": "pi_1ABC123",
            "metadata": {
                "package": "starter",
                "price_paid": 9.99,
                "currency": "USD"
            }
        }
        
        result = billing_repo.create_credit_transaction(transaction_data)
        
        assert result["user_id"] == str(user_id)
        assert result["amount"] == 100
        assert result["transaction_type"] == "purchase"
        assert result["description"] == "Credit purchase - Starter Pack"
        assert result["stripe_payment_intent_id"] == "pi_1ABC123"
        assert result["metadata"]["package"] == "starter"
        assert result["status"] == "completed"
        assert "id" in result
        assert "created_at" in result
    
    def test_create_usage_transaction(self, billing_repo):
        """Test creating a credit usage transaction"""
        user_id = uuid4()
        transaction_data = {
            "user_id": str(user_id),
            "amount": -10,  # Negative for usage
            "transaction_type": "usage",
            "description": "Email processing - AI summary",
            "metadata": {
                "email_id": "email-123",
                "tokens_used": 1500,
                "processing_time": 2.3
            }
        }
        
        result = billing_repo.create_credit_transaction(transaction_data)
        
        assert result["amount"] == -10
        assert result["transaction_type"] == "usage"
        assert result["metadata"]["email_id"] == "email-123"
        assert result["metadata"]["tokens_used"] == 1500
    
    def test_create_transaction_validation(self, billing_repo):
        """Test transaction validation"""
        # Missing required fields
        with pytest.raises(ValidationError) as exc_info:
            billing_repo.create_credit_transaction({
                "amount": 100,
                "transaction_type": "purchase"
                # Missing user_id and description
            })
        
        assert "user_id is required" in str(exc_info.value)
        
        # Invalid transaction type
        with pytest.raises(ValidationError) as exc_info:
            billing_repo.create_credit_transaction({
                "user_id": str(uuid4()),
                "amount": 100,
                "transaction_type": "invalid_type",
                "description": "Test"
            })
        
        assert "invalid transaction type" in str(exc_info.value).lower()
        
        # Invalid amount for purchase (should be positive)
        with pytest.raises(ValidationError) as exc_info:
            billing_repo.create_credit_transaction({
                "user_id": str(uuid4()),
                "amount": -100,
                "transaction_type": "purchase",
                "description": "Test"
            })
        
        assert "purchase amount must be positive" in str(exc_info.value).lower()
        
        # Invalid amount for usage (should be negative)
        with pytest.raises(ValidationError) as exc_info:
            billing_repo.create_credit_transaction({
                "user_id": str(uuid4()),
                "amount": 100,
                "transaction_type": "usage",
                "description": "Test"
            })
        
        assert "usage amount must be negative" in str(exc_info.value).lower()
    
    def test_get_user_balance(self, billing_repo):
        """Test getting user's current credit balance"""
        user_id = uuid4()
        
        # Initial balance should be 0
        balance = billing_repo.get_user_balance(user_id)
        assert balance == 0
        
        # Add some credits
        billing_repo.create_credit_transaction({
            "user_id": str(user_id),
            "amount": 100,
            "transaction_type": "purchase",
            "description": "Initial purchase"
        })
        
        # Balance should be 100
        balance = billing_repo.get_user_balance(user_id)
        assert balance == 100
        
        # Use some credits
        billing_repo.create_credit_transaction({
            "user_id": str(user_id),
            "amount": -25,
            "transaction_type": "usage",
            "description": "Email processing"
        })
        
        # Balance should be 75
        balance = billing_repo.get_user_balance(user_id)
        assert balance == 75
    
    def test_deduct_credits_success(self, billing_repo):
        """Test successful credit deduction"""
        user_id = uuid4()
        
        # First add some credits
        billing_repo.create_credit_transaction({
            "user_id": str(user_id),
            "amount": 100,
            "transaction_type": "purchase",
            "description": "Initial purchase"
        })
        
        # Deduct credits
        success = billing_repo.deduct_credits(user_id, 25, "Email processing")
        assert success == True
        
        # Verify balance
        balance = billing_repo.get_user_balance(user_id)
        assert balance == 75
    
    def test_deduct_credits_insufficient_balance(self, billing_repo):
        """Test credit deduction with insufficient balance"""
        user_id = uuid4()
        
        # Add only 10 credits
        billing_repo.create_credit_transaction({
            "user_id": str(user_id),
            "amount": 10,
            "transaction_type": "purchase",
            "description": "Small purchase"
        })
        
        # Try to deduct more than available
        with pytest.raises(InsufficientCreditsError) as exc_info:
            billing_repo.deduct_credits(user_id, 50, "Email processing")
        
        assert "insufficient credits" in str(exc_info.value).lower()
        assert "balance: 10" in str(exc_info.value)
        assert "requested: 50" in str(exc_info.value)
        
        # Balance should remain unchanged
        balance = billing_repo.get_user_balance(user_id)
        assert balance == 10
    
    def test_deduct_credits_atomic_operation(self, billing_repo):
        """Test that credit deduction is atomic"""
        user_id = uuid4()
        
        # Add credits
        billing_repo.create_credit_transaction({
            "user_id": str(user_id),
            "amount": 50,
            "transaction_type": "purchase",
            "description": "Purchase"
        })
        
        # Deduct exactly the balance
        success = billing_repo.deduct_credits(user_id, 50, "Use all credits")
        assert success == True
        
        # Balance should be exactly 0
        balance = billing_repo.get_user_balance(user_id)
        assert balance == 0
        
        # Any further deduction should fail
        with pytest.raises(InsufficientCreditsError):
            billing_repo.deduct_credits(user_id, 1, "Should fail")
    
    def test_add_credits_success(self, billing_repo):
        """Test adding credits to user account"""
        user_id = uuid4()
        
        # Add credits
        success = billing_repo.add_credits(user_id, 200, "Credit purchase")
        assert success == True
        
        # Verify balance
        balance = billing_repo.get_user_balance(user_id)
        assert balance == 200
        
        # Add more credits
        success = billing_repo.add_credits(user_id, 100, "Bonus credits")
        assert success == True
        
        # Verify updated balance
        balance = billing_repo.get_user_balance(user_id)
        assert balance == 300
    
    def test_add_credits_with_metadata(self, billing_repo):
        """Test adding credits with metadata"""
        user_id = uuid4()
        metadata = {
            "stripe_payment_intent_id": "pi_1ABC123",
            "package": "premium",
            "price_paid": 29.99,
            "currency": "USD"
        }
        
        success = billing_repo.add_credits(user_id, 500, "Premium package", metadata)
        assert success == True
        
        # Verify balance
        balance = billing_repo.get_user_balance(user_id)
        assert balance == 500
    
    def test_add_credits_validation(self, billing_repo):
        """Test validation for adding credits"""
        user_id = uuid4()
        
        # Zero amount should fail
        with pytest.raises(ValidationError) as exc_info:
            billing_repo.add_credits(user_id, 0, "Zero credits")
        
        assert "amount must be positive" in str(exc_info.value).lower()
        
        # Negative amount should fail
        with pytest.raises(ValidationError) as exc_info:
            billing_repo.add_credits(user_id, -100, "Negative credits")
        
        assert "amount must be positive" in str(exc_info.value).lower()
        
        # Missing description should fail
        with pytest.raises(ValidationError) as exc_info:
            billing_repo.add_credits(user_id, 100, "")
        
        assert "description is required" in str(exc_info.value).lower()
    
    def test_get_transaction_history(self, billing_repo):
        """Test getting user's transaction history"""
        user_id = uuid4()
        
        # Create several transactions
        billing_repo.create_credit_transaction({
            "user_id": str(user_id),
            "amount": 100,
            "transaction_type": "purchase",
            "description": "First purchase"
        })
        
        billing_repo.create_credit_transaction({
            "user_id": str(user_id),
            "amount": -10,
            "transaction_type": "usage",
            "description": "Email processing"
        })
        
        billing_repo.create_credit_transaction({
            "user_id": str(user_id),
            "amount": 50,
            "transaction_type": "bonus",
            "description": "Referral bonus"
        })
        
        # Get history
        history = billing_repo.get_transaction_history(user_id)
        
        assert len(history) == 3
        # Should be ordered by created_at descending (newest first)
        assert history[0]["description"] == "Referral bonus"
        assert history[1]["description"] == "Email processing"
        assert history[2]["description"] == "First purchase"
    
    def test_get_transaction_history_with_filters(self, billing_repo):
        """Test getting transaction history with filters"""
        user_id = uuid4()
        
        # Create transactions of different types
        billing_repo.create_credit_transaction({
            "user_id": str(user_id),
            "amount": 100,
            "transaction_type": "purchase",
            "description": "Purchase 1"
        })
        
        billing_repo.create_credit_transaction({
            "user_id": str(user_id),
            "amount": -10,
            "transaction_type": "usage",
            "description": "Usage 1"
        })
        
        billing_repo.create_credit_transaction({
            "user_id": str(user_id),
            "amount": 200,
            "transaction_type": "purchase",
            "description": "Purchase 2"
        })
        
        # Get only purchase transactions
        purchases = billing_repo.get_transaction_history(user_id, transaction_type="purchase")
        assert len(purchases) == 2
        assert all(t["transaction_type"] == "purchase" for t in purchases)
        
        # Get only usage transactions
        usage = billing_repo.get_transaction_history(user_id, transaction_type="usage")
        assert len(usage) == 1
        assert usage[0]["transaction_type"] == "usage"
        
        # Get with limit
        limited = billing_repo.get_transaction_history(user_id, limit=2)
        assert len(limited) == 2
    
    def test_get_transaction_history_date_range(self, billing_repo):
        """Test getting transaction history within date range"""
        user_id = uuid4()
        
        # Create transaction
        billing_repo.create_credit_transaction({
            "user_id": str(user_id),
            "amount": 100,
            "transaction_type": "purchase",
            "description": "Test purchase"
        })
        
        # Get history for today
        today = datetime.now().date()
        start_date = datetime.combine(today, datetime.min.time())
        end_date = datetime.combine(today, datetime.max.time())
        
        history = billing_repo.get_transaction_history(
            user_id, 
            start_date=start_date,
            end_date=end_date
        )
        
        assert len(history) == 1
        assert history[0]["description"] == "Test purchase"
        
        # Get history for yesterday (should be empty)
        yesterday = today - timedelta(days=1)
        start_date = datetime.combine(yesterday, datetime.min.time())
        end_date = datetime.combine(yesterday, datetime.max.time())
        
        history = billing_repo.get_transaction_history(
            user_id,
            start_date=start_date,
            end_date=end_date
        )
        
        assert len(history) == 0
    
    def test_get_billing_summary(self, billing_repo):
        """Test getting billing summary for user"""
        user_id = uuid4()
        
        # Create various transactions
        billing_repo.create_credit_transaction({
            "user_id": str(user_id),
            "amount": 100,
            "transaction_type": "purchase",
            "description": "Purchase 1"
        })
        
        billing_repo.create_credit_transaction({
            "user_id": str(user_id),
            "amount": 200,
            "transaction_type": "purchase",
            "description": "Purchase 2"
        })
        
        billing_repo.create_credit_transaction({
            "user_id": str(user_id),
            "amount": -50,
            "transaction_type": "usage",
            "description": "Usage 1"
        })
        
        # Get summary
        summary = billing_repo.get_billing_summary(user_id)
        
        assert summary["user_id"] == str(user_id)
        assert summary["current_balance"] == 250  # 100 + 200 - 50
        assert summary["total_purchased"] == 300  # 100 + 200
        assert summary["total_used"] == 50       # 50
        assert summary["total_transactions"] == 3
        assert "last_purchase_date" in summary
        assert "last_usage_date" in summary
    
    def test_get_usage_analytics(self, billing_repo):
        """Test getting usage analytics"""
        user_id = uuid4()
        
        # Create usage transactions
        billing_repo.create_credit_transaction({
            "user_id": str(user_id),
            "amount": -10,
            "transaction_type": "usage",
            "description": "Email processing"
        })
        
        billing_repo.create_credit_transaction({
            "user_id": str(user_id),
            "amount": -15,
            "transaction_type": "usage",
            "description": "API call"
        })
        
        # Get analytics for last 30 days
        analytics = billing_repo.get_usage_analytics(user_id, days=30)
        
        assert analytics["user_id"] == str(user_id)
        assert analytics["period_days"] == 30
        assert analytics["total_credits_used"] == 25  # 10 + 15
        assert analytics["total_usage_transactions"] == 2
        assert "average_daily_usage" in analytics
        assert "usage_by_day" in analytics
    
    def test_process_stripe_payment(self, billing_repo):
        """Test processing Stripe payment"""
        user_id = uuid4()
        payment_data = {
            "user_id": str(user_id),
            "stripe_payment_intent_id": "pi_1ABC123",
            "amount_paid": 19.99,
            "currency": "USD",
            "credits_purchased": 250,
            "package": "standard"
        }
        
        result = billing_repo.process_stripe_payment(payment_data)
        
        assert result["success"] == True
        assert result["credits_added"] == 250
        assert result["transaction_id"] is not None
        
        # Verify balance
        balance = billing_repo.get_user_balance(user_id)
        assert balance == 250
        
        # Verify transaction was created
        history = billing_repo.get_transaction_history(user_id)
        assert len(history) == 1
        assert history[0]["stripe_payment_intent_id"] == "pi_1ABC123"
        assert history[0]["amount"] == 250
    
    def test_get_pending_transactions(self, billing_repo):
        """Test getting pending transactions"""
        user_id = uuid4()
        
        # Create a pending transaction
        billing_repo.create_credit_transaction({
            "user_id": str(user_id),
            "amount": 100,
            "transaction_type": "purchase",
            "description": "Pending purchase",
            "status": "pending",
            "stripe_payment_intent_id": "pi_pending"
        })
        
        # Create a completed transaction
        billing_repo.create_credit_transaction({
            "user_id": str(user_id),
            "amount": 50,
            "transaction_type": "purchase",
            "description": "Completed purchase",
            "status": "completed"
        })
        
        # Get pending transactions
        pending = billing_repo.get_pending_transactions()
        
        assert len(pending) == 1
        assert pending[0]["status"] == "pending"
        assert pending[0]["description"] == "Pending purchase"
    
    def test_update_transaction_status(self, billing_repo):
        """Test updating transaction status"""
        user_id = uuid4()
        
        # Create pending transaction
        transaction = billing_repo.create_credit_transaction({
            "user_id": str(user_id),
            "amount": 100,
            "transaction_type": "purchase",
            "description": "Test purchase",
            "status": "pending"
        })
        
        # Update status
        success = billing_repo.update_transaction_status(transaction["id"], "completed")
        assert success == True
        
        # Verify status was updated
        history = billing_repo.get_transaction_history(user_id)
        assert history[0]["status"] == "completed"
    
    def test_get_low_balance_users(self, billing_repo):
        """Test getting users with low credit balance"""
        # Create users with different balances
        user1 = uuid4()
        user2 = uuid4()
        user3 = uuid4()
        
        # User 1: High balance
        billing_repo.add_credits(user1, 200, "High balance")
        
        # User 2: Low balance
        billing_repo.add_credits(user2, 15, "Low balance")
        
        # User 3: Very low balance
        billing_repo.add_credits(user3, 5, "Very low balance")
        
        # Get users with balance below 20
        low_balance_users = billing_repo.get_low_balance_users(threshold=20)
        
        assert len(low_balance_users) == 2
        user_ids = [user["user_id"] for user in low_balance_users]
        assert str(user2) in user_ids
        assert str(user3) in user_ids
        assert str(user1) not in user_ids
    
    def test_bulk_credit_operations(self, billing_repo):
        """Test bulk credit operations"""
        user1 = uuid4()
        user2 = uuid4()
        
        # Add initial credits
        billing_repo.add_credits(user1, 100, "Initial")
        billing_repo.add_credits(user2, 150, "Initial")
        
        # Bulk operations
        operations = [
            {"user_id": str(user1), "amount": -10, "description": "Bulk usage 1"},
            {"user_id": str(user2), "amount": -20, "description": "Bulk usage 2"},
            {"user_id": str(user1), "amount": 50, "description": "Bulk bonus"}
        ]
        
        results = billing_repo.bulk_credit_operations(operations)
        
        assert len(results) == 3
        assert all(result["success"] for result in results)
        
        # Verify balances
        assert billing_repo.get_user_balance(user1) == 140  # 100 - 10 + 50
        assert billing_repo.get_user_balance(user2) == 130  # 150 - 20
    
    @pytest.mark.parametrize("transaction_type", ["purchase", "usage", "bonus", "refund", "adjustment"])
    def test_valid_transaction_types(self, billing_repo, transaction_type):
        """Test all valid transaction types"""
        user_id = uuid4()
        
        # Determine amount based on type
        if transaction_type in ["purchase", "bonus", "adjustment"]:
            amount = 100
        else:  # usage, refund
            amount = -50
        
        result = billing_repo.create_credit_transaction({
            "user_id": str(user_id),
            "amount": amount,
            "transaction_type": transaction_type,
            "description": f"Test {transaction_type}"
        })
        
        assert result["transaction_type"] == transaction_type
    
    def test_concurrent_credit_operations(self, billing_repo):
        """Test concurrent credit operations don't cause race conditions"""
        user_id = uuid4()
        
        # Add initial credits
        billing_repo.add_credits(user_id, 100, "Initial")
        
        # Simulate concurrent deductions
        # In real implementation, this would test database-level atomicity
        success1 = billing_repo.deduct_credits(user_id, 30, "Concurrent 1")
        success2 = billing_repo.deduct_credits(user_id, 40, "Concurrent 2")
        
        assert success1 == True
        assert success2 == True
        
        # Balance should be exactly 30 (100 - 30 - 40)
        balance = billing_repo.get_user_balance(user_id)
        assert balance == 30
        
        # Third operation should fail
        with pytest.raises(InsufficientCreditsError):
            billing_repo.deduct_credits(user_id, 50, "Should fail")
    
    def test_transaction_audit_trail(self, billing_repo):
        """Test that all transactions create proper audit trail"""
        user_id = uuid4()
        
        # Create transaction
        result = billing_repo.create_credit_transaction({
            "user_id": str(user_id),
            "amount": 100,
            "transaction_type": "purchase",
            "description": "Audit test"
        })
        
        # Should have audit fields
        assert "id" in result
        assert "created_at" in result
        assert "updated_at" in result
        assert result["status"] == "completed"
        
        # Should be retrievable in history
        history = billing_repo.get_transaction_history(user_id)
        assert len(history) == 1
        assert history[0]["id"] == result["id"]