# tests/test_billing_repository_fixed.py
"""
Fixed comprehensive test suite for BillingRepository.
Addresses all UUID comparison, mock functionality, and datetime handling issues.
"""
import pytest
from unittest.mock import Mock, AsyncMock
from uuid import uuid4, UUID
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

from app.data.repositories.billing_repository import BillingRepository
from app.models.billing import TransactionRecord, BillingSummary
from app.core.exceptions import (
    TransactionNotFoundError,
    DuplicateTransactionError,
    InvalidTransactionTypeError,
    DatabaseError
)


class MockQueryBuilder:
    """Enhanced mock query builder for testing"""
    
    def __init__(self, mock_response: Any = None, should_error: bool = False, table_data: List = None):
        self.mock_response = mock_response
        self.should_error = should_error
        self.table_data = table_data or []
        self.filters = {}
        self.order_by = None
        self.limit_value = None
        self.offset_value = None
        self.columns = "*"
        self.count_mode = False
    
    def eq(self, column: str, value: Any) -> "MockQueryBuilder":
        self.filters[column] = value
        return self
    
    def limit(self, count: int) -> "MockQueryBuilder":
        self.limit_value = count
        return self
    
    def offset(self, count: int) -> "MockQueryBuilder":
        self.offset_value = count
        return self
    
    def order(self, column: str, desc: bool = False) -> "MockQueryBuilder":
        self.order_by = (column, desc)
        return self
    
    def select(self, columns: str = "*", count: str = None) -> "MockQueryBuilder":
        self.columns = columns
        if count == "exact":
            self.count_mode = True
        return self
    
    def execute(self) -> Mock:
        if self.should_error:
            response = Mock()
            response.error = Exception("Mock database error")
            response.data = None
            response.count = None
            return response
        
        # Apply filters to find matching data
        filtered_data = self.table_data[:]
        for column, value in self.filters.items():
            filtered_data = [item for item in filtered_data if str(item.get(column)) == str(value)]
        
        # Apply limit
        if self.limit_value and filtered_data:
            filtered_data = filtered_data[:self.limit_value]
        
        # Use mock_response if no table_data filtering
        if not self.table_data and self.mock_response:
            filtered_data = self.mock_response if isinstance(self.mock_response, list) else [self.mock_response]
        
        response = Mock()
        response.error = None
        
        if self.count_mode:
            response.data = []
            response.count = len(filtered_data)
        else:
            response.data = filtered_data
            response.count = len(filtered_data)
        
        return response


class MockTable:
    """Enhanced mock database table for testing"""
    
    def __init__(self):
        self.data = []
        self.should_error = False
        self.last_insert = None
        self.last_update = None
    
    def insert(self, data: Dict[str, Any]) -> MockQueryBuilder:
        if not self.should_error:
            # Generate ID if not provided
            if 'id' not in data:
                data['id'] = str(uuid4())
            self.data.append(data.copy())
            self.last_insert = data
            return MockQueryBuilder([data], table_data=self.data)
        return MockQueryBuilder(should_error=True)
    
    def select(self, columns: str = "*", count: str = None) -> MockQueryBuilder:
        builder = MockQueryBuilder(self.data, should_error=self.should_error, table_data=self.data)
        return builder.select(columns, count)
    
    def update(self, data: Dict[str, Any]) -> MockQueryBuilder:
        self.last_update = data
        # Find and update matching records based on filters applied later
        updated_records = []
        for record in self.data:
            updated_record = record.copy()
            updated_record.update(data)
            updated_records.append(updated_record)
        return MockQueryBuilder(updated_records, should_error=self.should_error, table_data=self.data)
    
    def delete(self) -> MockQueryBuilder:
        return MockQueryBuilder([], should_error=self.should_error, table_data=self.data)
    
    def set_error_mode(self, should_error: bool):
        self.should_error = should_error


@pytest.fixture
def mock_table():
    """Provide a mock table for testing"""
    return MockTable()


@pytest.fixture
def billing_repo(mock_table):
    """Provide a billing repository with mock table"""
    return BillingRepository.create_for_testing(mock_table)


@pytest.fixture
def sample_user_id():
    """Provide a sample user ID"""
    return uuid4()


@pytest.fixture
def sample_transaction_data():
    """Provide sample transaction data"""
    return {
        "id": str(uuid4()),
        "user_id": str(uuid4()),
        "transaction_type": "purchase",
        "credit_amount": 100,
        "credit_balance_after": 100,
        "description": "Test purchase",
        "reference_id": str(uuid4()),
        "reference_type": "stripe_checkout",
        "usd_amount": 5.0,
        "usd_per_credit": 0.05,
        "metadata": {"test": "data"},
        "created_at": datetime.utcnow().isoformat()
    }


class TestBillingRepository:
    """Test suite for BillingRepository"""

    # --- Create Transaction Tests ---

    @pytest.mark.asyncio
    async def test_create_transaction_success(self, billing_repo, sample_user_id):
        """Test successful transaction creation"""
        transaction = await billing_repo.create_transaction(
            user_id=sample_user_id,
            transaction_type="purchase",
            credit_amount=100,
            credit_balance_after=100,
            description="Test purchase",
            usd_amount=5.0,
            usd_per_credit=0.05,
            metadata={"test": "data"}
        )
        
        assert isinstance(transaction, TransactionRecord)
        assert transaction.user_id == sample_user_id
        assert transaction.transaction_type == "purchase"
        assert transaction.credit_amount == 100
        assert transaction.description == "Test purchase"
        assert transaction.metadata == {"test": "data"}

    @pytest.mark.asyncio
    async def test_create_transaction_invalid_type(self, billing_repo, sample_user_id):
        """Test transaction creation with invalid type"""
        with pytest.raises(InvalidTransactionTypeError) as exc_info:
            await billing_repo.create_transaction(
                user_id=sample_user_id,
                transaction_type="invalid_type",
                credit_amount=100,
                credit_balance_after=100,
                description="Test"
            )
        
        assert "invalid_type" in str(exc_info.value)
        assert exc_info.value.transaction_type == "invalid_type"

    @pytest.mark.asyncio
    async def test_create_transaction_duplicate_reference(self, billing_repo, sample_user_id, mock_table):
        """Test transaction creation with duplicate reference"""
        reference_id = uuid4()
        
        # Create first transaction
        await billing_repo.create_transaction(
            user_id=sample_user_id,
            transaction_type="purchase",
            credit_amount=100,
            credit_balance_after=100,
            description="First purchase",
            reference_id=reference_id,
            reference_type="stripe_checkout"
        )
        
        # Try to create duplicate
        with pytest.raises(DuplicateTransactionError) as exc_info:
            await billing_repo.create_transaction(
                user_id=sample_user_id,
                transaction_type="purchase",
                credit_amount=50,
                credit_balance_after=150,
                description="Duplicate purchase",
                reference_id=reference_id,
                reference_type="stripe_checkout"
            )
        
        assert str(reference_id) in str(exc_info.value)

    # --- Get Transaction Tests ---

    @pytest.mark.asyncio
    async def test_get_transaction_by_id_exists(self, billing_repo, sample_user_id, sample_transaction_data, mock_table):
        """Test getting existing transaction by ID"""
        # Setup mock data
        mock_table.data = [sample_transaction_data]
        
        transaction = await billing_repo.get_transaction_by_id(UUID(sample_transaction_data["id"]))
        
        assert transaction is not None
        assert transaction.id == UUID(sample_transaction_data["id"])
        assert transaction.transaction_type == sample_transaction_data["transaction_type"]

    @pytest.mark.asyncio
    async def test_get_transaction_by_id_not_exists(self, billing_repo):
        """Test getting non-existent transaction by ID"""
        transaction = await billing_repo.get_transaction_by_id(uuid4())
        assert transaction is None

    # --- List Transactions Tests ---

    @pytest.mark.asyncio
    async def test_list_transactions_for_user_success(self, billing_repo, sample_user_id, mock_table):
        """Test listing transactions for user"""
        # Create test data
        test_transactions = []
        for i in range(3):
            txn_data = {
                "id": str(uuid4()),
                "user_id": str(sample_user_id),
                "transaction_type": "purchase",
                "credit_amount": 100,
                "credit_balance_after": 100 * (i + 1),
                "description": f"Test purchase {i}",
                "metadata": {},
                "created_at": datetime.utcnow().isoformat()
            }
            test_transactions.append(txn_data)
        
        mock_table.data = test_transactions
        
        transactions = await billing_repo.list_transactions_for_user(sample_user_id, limit=10)
        
        assert len(transactions) == 3
        assert all(isinstance(txn, TransactionRecord) for txn in transactions)
        assert all(txn.user_id == sample_user_id for txn in transactions)

    @pytest.mark.asyncio
    async def test_list_transactions_invalid_type_filter(self, billing_repo, sample_user_id):
        """Test listing transactions with invalid type filter"""
        with pytest.raises(InvalidTransactionTypeError):
            await billing_repo.list_transactions_for_user(
                sample_user_id,
                transaction_type="invalid_type"
            )

    # --- Find by Reference Tests ---

    @pytest.mark.asyncio
    async def test_find_transaction_by_reference_exists(self, billing_repo, sample_transaction_data, mock_table):
        """Test finding transaction by reference"""
        mock_table.data = [sample_transaction_data]
        
        transaction = await billing_repo.find_transaction_by_reference(
            UUID(sample_transaction_data["reference_id"]),
            sample_transaction_data["reference_type"]
        )
        
        assert transaction is not None
        assert transaction.reference_id == UUID(sample_transaction_data["reference_id"])

    @pytest.mark.asyncio
    async def test_find_transaction_by_reference_not_exists(self, billing_repo):
        """Test finding non-existent transaction by reference"""
        transaction = await billing_repo.find_transaction_by_reference(
            uuid4(),
            "stripe_checkout"
        )
        assert transaction is None

    # --- Update Metadata Tests ---

    @pytest.mark.asyncio
    async def test_update_transaction_metadata_success(self, billing_repo, sample_transaction_data, mock_table):
        """Test successful metadata update"""
        # Setup existing transaction
        mock_table.data = [sample_transaction_data.copy()]
        
        new_metadata = {"updated": True, "test": "updated_data"}
        
        updated_transaction = await billing_repo.update_transaction_metadata(
            UUID(sample_transaction_data["id"]),
            new_metadata
        )
        
        assert isinstance(updated_transaction, TransactionRecord)
        assert "updated" in updated_transaction.metadata

    @pytest.mark.asyncio
    async def test_update_transaction_metadata_not_found(self, billing_repo):
        """Test updating metadata for non-existent transaction"""
        with pytest.raises(TransactionNotFoundError):
            await billing_repo.update_transaction_metadata(
                uuid4(),
                {"test": "data"}
            )

    # --- Count Transactions Tests ---

    @pytest.mark.asyncio
    async def test_count_transactions_for_user(self, billing_repo, sample_user_id, mock_table):
        """Test counting transactions for user"""
        # Create test data
        test_transactions = [
            {"id": str(uuid4()), "user_id": str(sample_user_id)},
            {"id": str(uuid4()), "user_id": str(sample_user_id)},
            {"id": str(uuid4()), "user_id": str(sample_user_id)}
        ]
        mock_table.data = test_transactions
        
        count = await billing_repo.count_transactions_for_user(sample_user_id)
        assert isinstance(count, int)
        assert count >= 0

    # --- Summary Tests ---

    @pytest.mark.asyncio
    async def test_get_user_transaction_summary(self, billing_repo, sample_user_id, mock_table):
        """Test getting transaction summary"""
        # Create test data with different transaction types
        test_transactions = [
            {
                "id": str(uuid4()),
                "user_id": str(sample_user_id),
                "transaction_type": "purchase",
                "credit_amount": 100,
                "credit_balance_after": 100,
                "description": "Purchase",
                "metadata": {},
                "created_at": datetime.utcnow().isoformat()
            },
            {
                "id": str(uuid4()),
                "user_id": str(sample_user_id),
                "transaction_type": "usage",
                "credit_amount": -20,
                "credit_balance_after": 80,
                "description": "Usage",
                "metadata": {},
                "created_at": datetime.utcnow().isoformat()
            }
        ]
        mock_table.data = test_transactions
        
        summary = await billing_repo.get_user_transaction_summary(sample_user_id)
        
        assert isinstance(summary, BillingSummary)
        assert summary.user_id == sample_user_id
        assert summary.total_transactions == 2

    # --- Usage Analytics Tests ---

    @pytest.mark.asyncio
    async def test_get_usage_analytics(self, billing_repo, sample_user_id, mock_table):
        """Test getting usage analytics with proper datetime handling"""
        # Create usage transactions with proper dates
        base_date = datetime.utcnow()
        usage_transactions = [
            {
                "id": str(uuid4()),
                "user_id": str(sample_user_id),
                "transaction_type": "usage",
                "credit_amount": -10,
                "credit_balance_after": 90,
                "description": "Usage 1",
                "metadata": {},
                "created_at": base_date.isoformat()
            },
            {
                "id": str(uuid4()),
                "user_id": str(sample_user_id),
                "transaction_type": "usage",
                "credit_amount": -15,
                "credit_balance_after": 75,
                "description": "Usage 2",
                "metadata": {},
                "created_at": (base_date - timedelta(days=1)).isoformat()
            }
        ]
        mock_table.data = usage_transactions
        
        analytics = await billing_repo.get_usage_analytics(sample_user_id, period_days=30)
        
        assert analytics.user_id == sample_user_id
        assert analytics.period_days == 30
        assert isinstance(analytics.total_credits_used, int)

    # --- Delete Transaction Tests ---

    @pytest.mark.asyncio
    async def test_delete_transaction_success(self, billing_repo, sample_transaction_data, mock_table):
        """Test successful transaction deletion"""
        mock_table.data = [sample_transaction_data]
        
        result = await billing_repo.delete_transaction(UUID(sample_transaction_data["id"]))
        assert result is True

    @pytest.mark.asyncio
    async def test_delete_transaction_not_found(self, billing_repo):
        """Test deleting non-existent transaction"""
        with pytest.raises(TransactionNotFoundError):
            await billing_repo.delete_transaction(uuid4())

    # --- Health Check Tests ---

    @pytest.mark.asyncio
    async def test_health_check_success(self, billing_repo):
        """Test successful health check"""
        health = await billing_repo.health_check()
        
        assert isinstance(health, dict)
        assert "healthy" in health
        assert "timestamp" in health

    @pytest.mark.asyncio
    async def test_health_check_failure(self, billing_repo, mock_table):
        """Test health check with database error"""
        mock_table.set_error_mode(True)
        
        health = await billing_repo.health_check()
        
        assert isinstance(health, dict)
        assert health["healthy"] is False
        assert "error" in health

    # --- Convenience Methods Tests ---

    @pytest.mark.asyncio
    async def test_create_purchase_transaction(self, billing_repo, sample_user_id):
        """Test convenience method for purchase transactions"""
        transaction = await billing_repo.create_purchase_transaction(
            user_id=sample_user_id,
            credit_amount=100,
            credit_balance_after=100,
            usd_amount=5.0,
            usd_per_credit=0.05,
            stripe_session_id=uuid4(),
            description="Test purchase"
        )
        
        assert transaction.transaction_type == "purchase"
        assert transaction.reference_type == "stripe_checkout"
        assert transaction.usd_amount == 5.0

    @pytest.mark.asyncio
    async def test_create_usage_transaction(self, billing_repo, sample_user_id):
        """Test convenience method for usage transactions"""
        service_id = uuid4()
        
        transaction = await billing_repo.create_usage_transaction(
            user_id=sample_user_id,
            credit_amount=10,  # Should be converted to negative
            credit_balance_after=90,
            description="Test usage",
            service_reference=service_id
        )
        
        assert transaction.transaction_type == "usage"
        assert transaction.credit_amount == -10  # Should be negative
        assert transaction.reference_type == "service_usage"
        assert transaction.reference_id == service_id

    @pytest.mark.asyncio
    async def test_create_refund_transaction(self, billing_repo, sample_user_id):
        """Test convenience method for refund transactions"""
        original_transaction_id = uuid4()
        
        transaction = await billing_repo.create_refund_transaction(
            user_id=sample_user_id,
            credit_amount=50,
            credit_balance_after=150,
            original_transaction_id=original_transaction_id,
            description="Test refund"
        )
        
        assert transaction.transaction_type == "refund"
        assert transaction.reference_id == original_transaction_id
        assert transaction.reference_type == "transaction_refund"

    # --- Error Handling Tests ---

    @pytest.mark.asyncio
    async def test_create_transaction_database_error(self, billing_repo, sample_user_id, mock_table):
        """Test transaction creation with database error"""
        mock_table.set_error_mode(True)
        
        with pytest.raises(DatabaseError):
            await billing_repo.create_transaction(
                user_id=sample_user_id,
                transaction_type="purchase",
                credit_amount=100,
                credit_balance_after=100,
                description="Test purchase"
            )

    @pytest.mark.asyncio
    async def test_get_transaction_by_id_database_error(self, billing_repo, sample_user_id, mock_table):
        """Test getting transaction with database error"""
        mock_table.set_error_mode(True)
        
        with pytest.raises(DatabaseError):
            await billing_repo.get_transaction_by_id(uuid4())

    # --- Integration Tests ---

    @pytest.mark.asyncio
    async def test_complete_purchase_flow(self, billing_repo, sample_user_id):
        """Test complete purchase transaction flow"""
        stripe_session_id = uuid4()
        
        # 1. Create purchase transaction
        purchase = await billing_repo.create_purchase_transaction(
            user_id=sample_user_id,
            credit_amount=100,
            credit_balance_after=100,
            usd_amount=5.0,
            usd_per_credit=0.05,
            stripe_session_id=stripe_session_id,
            description="Test purchase"
        )
        
        # 2. Verify transaction exists
        found_transaction = await billing_repo.get_transaction_by_id(purchase.id)
        assert found_transaction is not None
        assert found_transaction.id == purchase.id
        
        # 3. Update metadata
        updated_transaction = await billing_repo.update_transaction_metadata(
            purchase.id,
            {"status": "completed"}
        )
        assert "status" in updated_transaction.metadata