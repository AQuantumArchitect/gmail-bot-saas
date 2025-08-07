import pytest
from uuid import uuid4, UUID
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

# Import the specific domain models and exceptions used by the repository.
from app.models.billing import TransactionRecord, BillingSummary, CreditUsageAnalytics
from app.data.repositories.billing_repository import BillingRepository
from app.core.exceptions import (
    ValidationError,
    TransactionNotFoundError,
    DuplicateTransactionError,
    InvalidTransactionTypeError
)

# --- Test Constants ---
USER_ID = uuid4()
OTHER_USER_ID = uuid4()

# --- Pytest Fixtures ---

@pytest.fixture
def sample_transaction_args() -> dict:
    """
    Provides a reusable dictionary of arguments for creating a single transaction.
    This fixture does NOT include 'id' because the repository now generates it.
    """
    return {
        "user_id": USER_ID,
        "transaction_type": "purchase",
        "credit_amount": 100,
        "credit_balance_after": 200,
        "description": "Test credit purchase",
        "reference_id": "pi_test_12345",
        "reference_type": "stripe_payment_intent",
        "usd_amount": 5.00,
        "usd_per_credit": 0.05,
        "metadata": {"package_key": "starter"},
    }

@pytest.fixture
def multiple_transactions_data() -> List[dict]:
    """
    Provides a list of complete transaction data for populating the repo.
    This data is enriched to pass validation for summary/analytics tests.
    """
    return [
        {
            "id": uuid4(), "user_id": USER_ID, "transaction_type": "purchase",
            "credit_amount": 100, "credit_balance_after": 100, "description": "Initial purchase",
            "created_at": datetime.utcnow() - timedelta(days=10), "metadata": {},
            "usd_amount": 10.0, "reference_id": "pi_1", "reference_type": "stripe_payment_intent"
        },
        {
            "id": uuid4(), "user_id": USER_ID, "transaction_type": "usage",
            "credit_amount": -20, "credit_balance_after": 80, "description": "Email processing",
            "created_at": datetime.utcnow() - timedelta(days=5), "metadata": {},
            "reference_id": "email_job_1", "reference_type": "service_usage"
        },
        {
            "id": uuid4(), "user_id": USER_ID, "transaction_type": "bonus",
            "credit_amount": 10, "credit_balance_after": 90, "description": "Referral bonus",
            "created_at": datetime.utcnow() - timedelta(days=2), "metadata": {}
        },
        {
            "id": uuid4(), "user_id": OTHER_USER_ID, "transaction_type": "purchase",
            "credit_amount": 50, "credit_balance_after": 50, "description": "Other user purchase",
            "created_at": datetime.utcnow() - timedelta(days=1), "metadata": {},
            "usd_amount": 5.0, "reference_id": "pi_2", "reference_type": "stripe_payment_intent"
        }
    ]

@pytest.fixture
def billing_repo() -> BillingRepository:
    """Creates a BillingRepository instance that uses the in-memory backend for testing."""
    # Instantiating with no client automatically enables the in-memory store.
    return BillingRepository()

@pytest.fixture
def populated_billing_repo(billing_repo: BillingRepository, multiple_transactions_data: List[dict]) -> BillingRepository:
    """
    Creates a repo instance and pre-populates its in-memory store.
    This is more efficient than calling `create_transaction` in every test.
    """
    repo = billing_repo
    for txn_data in multiple_transactions_data:
        txn_id = txn_data["id"]
        user_id = txn_data["user_id"]
        
        # Directly manipulate the internal state for test setup
        repo._transactions[txn_id] = txn_data
        
        if user_id not in repo._user_transactions:
            repo._user_transactions[user_id] = []
        repo._user_transactions[user_id].append(txn_id)
        
        if txn_data.get("reference_id") and txn_data.get("reference_type"):
            ref_tuple = (txn_data["reference_id"], txn_data["reference_type"])
            repo._reference_index[ref_tuple] = txn_id
            
    return repo

### Core Operation Tests ###

@pytest.mark.asyncio
async def test_create_transaction_success(billing_repo: BillingRepository):
    repo = billing_repo
    transaction = await repo.create_transaction(
        user_id=USER_ID, transaction_type="purchase", credit_amount=100,
        credit_balance_after=100, description="Test purchase", usd_amount=10.0
    )
    assert isinstance(transaction, TransactionRecord)
    assert len(repo._transactions) == 1
    assert transaction.user_id == USER_ID

@pytest.mark.asyncio
async def test_get_transaction_by_id_found(populated_billing_repo: BillingRepository, multiple_transactions_data: list):
    repo = populated_billing_repo
    # Get the ID of the first transaction created for USER_ID
    target_txn_id = multiple_transactions_data[0]['id']
    
    transaction = await repo.get_transaction_by_id(target_txn_id, user_id=USER_ID)
    
    assert transaction is not None
    assert transaction.id == target_txn_id

@pytest.mark.asyncio
async def test_get_transaction_by_id_not_found(billing_repo: BillingRepository):
    repo = billing_repo
    assert await repo.get_transaction_by_id(uuid4(), user_id=USER_ID) is None

@pytest.mark.asyncio
async def test_get_transaction_by_id_rls_fails_for_wrong_user(populated_billing_repo: BillingRepository, multiple_transactions_data: list):
    repo = populated_billing_repo
    # This transaction belongs to USER_ID
    target_txn_id = multiple_transactions_data[0]['id']
    
    # But we try to fetch it as OTHER_USER_ID
    transaction = await repo.get_transaction_by_id(target_txn_id, user_id=OTHER_USER_ID)
    
    assert transaction is None

@pytest.mark.asyncio
async def test_find_transaction_by_reference(billing_repo: BillingRepository, sample_transaction_args: dict):
    repo = billing_repo
    # The create_transaction method does not take 'id'
    await repo.create_transaction(**sample_transaction_args)

    found = await repo.find_transaction_by_reference(
        reference_id=sample_transaction_args["reference_id"],
        reference_type=sample_transaction_args["reference_type"]
    )
    assert found is not None
    assert found.reference_id == sample_transaction_args["reference_id"]

### Listing and Analytics Tests ###

@pytest.mark.asyncio
async def test_get_user_transactions(populated_billing_repo: BillingRepository):
    repo = populated_billing_repo
    transactions = await repo.get_user_transactions(USER_ID, limit=10)
    assert len(transactions) == 3
    assert all(t.user_id == USER_ID for t in transactions)

@pytest.mark.asyncio
async def test_get_user_transactions_with_type_filter(populated_billing_repo: BillingRepository):
    repo = populated_billing_repo
    transactions = await repo.get_user_transactions(USER_ID, transaction_type="purchase")
    assert len(transactions) == 1
    assert transactions[0].transaction_type == "purchase"

@pytest.mark.asyncio
async def test_get_billing_summary(populated_billing_repo: BillingRepository):
    repo = populated_billing_repo
    summary = await repo.get_billing_summary(USER_ID)
    
    assert isinstance(summary, BillingSummary)
    assert summary.current_balance == 90
    assert summary.total_purchased == 100
    assert summary.total_used == 20
    assert summary.total_bonus == 10
    assert summary.total_refunded == 0
    assert summary.total_transactions == 3
    assert summary.transaction_breakdown['purchase'] == 1
    assert summary.transaction_breakdown['usage'] == 1
    assert summary.transaction_breakdown['bonus'] == 1

@pytest.mark.asyncio
async def test_get_usage_analytics(populated_billing_repo: BillingRepository):
    repo = populated_billing_repo
    analytics = await repo.get_usage_analytics(USER_ID, days=30)
    
    assert isinstance(analytics, CreditUsageAnalytics)
    assert analytics.total_credits_used == 20
    assert analytics.total_usage_transactions == 1
    assert analytics.average_daily_usage == round(20/30, 2)
    day_key = (datetime.utcnow() - timedelta(days=5)).strftime('%Y-%m-%d')
    assert analytics.usage_by_day[day_key] == 20
    assert analytics.peak_usage_day == day_key


### Error and Validation Tests ###

@pytest.mark.asyncio
async def test_create_transaction_invalid_type_raises_error(billing_repo: BillingRepository):
    repo = billing_repo
    with pytest.raises(InvalidTransactionTypeError):
        await repo.create_transaction(
            user_id=USER_ID, transaction_type="invalid_type", credit_amount=100,
            credit_balance_after=100, description="This should fail"
        )

@pytest.mark.asyncio
async def test_create_usage_transaction_with_positive_amount_raises_error(billing_repo: BillingRepository):
    repo = billing_repo
    with pytest.raises(ValidationError, match="Usage transactions must have negative credit amounts"):
        await repo.create_transaction(
            user_id=USER_ID, transaction_type="usage", credit_amount=50, # Should be negative
            credit_balance_after=50, description="Positive usage"
        )
        
@pytest.mark.asyncio
async def test_create_purchase_transaction_with_negative_amount_raises_error(billing_repo: BillingRepository):
    repo = billing_repo
    with pytest.raises(ValidationError, match="Purchase transactions must have positive credit amounts"):
        await repo.create_transaction(
            user_id=USER_ID, transaction_type="purchase", credit_amount=-50, # Should be positive
            credit_balance_after=50, description="Negative purchase"
        )

@pytest.mark.asyncio
async def test_create_transaction_duplicate_reference_raises_error(billing_repo: BillingRepository, sample_transaction_args: dict):
    repo = billing_repo
    # Create the first transaction
    await repo.create_transaction(**sample_transaction_args)
    
    # Try to create another with the same reference
    with pytest.raises(DuplicateTransactionError):
        await repo.create_transaction(
            user_id=USER_ID, transaction_type="purchase", credit_amount=50,
            credit_balance_after=150, description="Duplicate",
            reference_id=str(sample_transaction_args["reference_id"]),
            reference_type=sample_transaction_args["reference_type"]
        )

### Convenience Method Tests ###

@pytest.mark.asyncio
async def test_create_purchase_transaction(billing_repo: BillingRepository):
    repo = billing_repo
    await repo.create_purchase_transaction(
        user_id=USER_ID, credit_amount=50, credit_balance_after=50,
        usd_amount=2.50, stripe_payment_intent_id="pi_test_new"
    )
    assert len(repo._transactions) == 1
    # Access the transaction from the internal dict to check its properties
    txn = list(repo._transactions.values())[0]
    assert txn['transaction_type'] == 'purchase'
    assert txn['reference_id'] == 'pi_test_new'
    assert txn['reference_type'] == 'stripe_payment_intent'
    assert txn['usd_per_credit'] == 0.05

@pytest.mark.asyncio
async def test_create_usage_transaction(billing_repo: BillingRepository):
    repo = billing_repo
    await repo.create_usage_transaction(
        user_id=USER_ID, credit_amount=15, # Should be converted to -15
        credit_balance_after=85, description="test usage"
    )
    assert len(repo._transactions) == 1
    txn = list(repo._transactions.values())[0]
    assert txn['transaction_type'] == 'usage'
    assert txn['credit_amount'] == -15 # Should be negative

@pytest.mark.asyncio
async def test_create_refund_transaction(billing_repo: BillingRepository):
    repo = billing_repo
    original_txn_id = uuid4()
    
    await repo.create_refund_transaction(
        user_id=USER_ID, credit_amount=50, credit_balance_after=250,
        description="Refund for purchase", original_transaction_id=original_txn_id
    )
    assert len(repo._transactions) == 1
    txn = list(repo._transactions.values())[0]
    assert txn['transaction_type'] == 'refund'
    assert txn['credit_amount'] == 50 # Must be positive
    assert txn['reference_id'] == str(original_txn_id)
    assert txn['reference_type'] == 'refund_for_transaction'
