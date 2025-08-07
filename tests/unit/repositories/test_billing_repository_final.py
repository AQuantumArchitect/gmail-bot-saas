# tests/test_billing_repository_final.py
"""
Final fixed comprehensive test suite for BillingRepository.
"""
import pytest
from unittest.mock import Mock
from uuid import uuid4, UUID
from datetime import datetime, timedelta
from typing import Dict, Any, List

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
    
    def __init__(self, mock_response: Any = None, should_error: bool = False, table_ref=None):
        self.mock_response = mock_response
        self.should_error = should_error
        self.table_ref = table_ref
        self.filters = {}
        self.order_by = None
        self.limit_value = None
        self.offset_value = None
        self.columns = "*"
        self.count_mode = False
        self.update_data = None
    
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
        
        # Get data from table or use mock response
        data_to_filter = self.table_ref.data if self.table_ref else (self.mock_response or [])
        
        # Apply filters
        filtered_data = []
        for item in data_to_filter:
            matches = True
            for column, value in self.filters.items():
                if str(item.get(column)) != str(value):
                    matches = False
                    break
            if matches:
                filtered_data.append(item)
        
        # Handle updates
        if self.update_data and self.table_ref:
            for item in filtered_data:
                if 'metadata' in self.update_data and 'metadata' in item:
                    # Merge metadata
                    merged_metadata = item['metadata'].copy()
                    merged_metadata.update(self.update_data['metadata'])
                    item['metadata'] = merged_metadata
                else:
                    item.update(self.update_data)
        
        # Apply limit
        if self.limit_value and filtered_data:
            filtered_data = filtered_data[:self.limit_value]
        
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
    
    def insert(self, data: Dict[str, Any]) -> MockQueryBuilder:
        if not self.should_error:
            if 'id' not in data:
                data['id'] = str(uuid4())
            self.data.append(data.copy())
            return MockQueryBuilder([data], table_ref=self)
        return MockQueryBuilder(should_error=True)
    
    def select(self, columns: str = "*", count: str = None) -> MockQueryBuilder:
        builder = MockQueryBuilder(self.data, should_error=self.should_error, table_ref=self)
        return builder.select(columns, count)
    
    def update(self, data: Dict[str, Any]) -> MockQueryBuilder:
        builder = MockQueryBuilder(self.data, should_error=self.should_error, table_ref=self)
        builder.update_data = data
        return builder
    
    def delete(self) -> MockQueryBuilder:
        return MockQueryBuilder([], should_error=self.should_error, table_ref=self)
    
    def set_error_mode(self, should_error: bool):
        self.should_error = should_error


@pytest.fixture
def mock_table():
    return MockTable()


@pytest.fixture
def billing_repo(mock_table):
    return BillingRepository.create_for_testing(mock_table)


@pytest.fixture
def sample_user_id():
    return uuid4()


@pytest.fixture
def sample_transaction_data():
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

    @pytest.mark.asyncio
    async def test_create_transaction_invalid_type(self, billing_repo, sample_user_id):
        """Test transaction creation with invalid type"""
        with pytest.raises(InvalidTransactionTypeError):
            await billing_repo.create_transaction(
                user_id=sample_user_id,
                transaction_type="invalid_type",
                credit_amount=100,
                credit_balance_after=100,
                description="Test"
            )

    @pytest.mark.asyncio
    async def test_get_transaction_by_id_exists(self, billing_repo, sample_transaction_data, mock_table):
        """Test getting existing transaction by ID"""
        mock_table.data = [sample_transaction_data]
        
        transaction = await billing_repo.get_transaction_by_id(UUID(sample_transaction_data["id"]))
        
        assert transaction is not None
        assert transaction.id == UUID(sample_transaction_data["id"])

    @pytest.mark.asyncio
    async def test_get_transaction_by_id_not_exists(self, billing_repo):
        """Test getting non-existent transaction by ID"""
        transaction = await billing_repo.get_transaction_by_id(uuid4())
        assert transaction is None

    @pytest.mark.asyncio
    async def test_list_transactions_for_user_success(self, billing_repo, sample_user_id, mock_table):
        """Test listing transactions for user"""
        test_transactions = [
            {
                "id": str(uuid4()),
                "user_id": str(sample_user_id),
                "transaction_type": "purchase",
                "credit_amount": 100,
                "credit_balance_after": 100,
                "description": "Test purchase",
                "metadata": {},
                "created_at": datetime.utcnow().isoformat()
            }
        ]
        mock_table.data = test_transactions
        
        transactions = await billing_repo.list_transactions_for_user(sample_user_id)
        
        assert len(transactions) == 1
        assert isinstance(transactions[0], TransactionRecord)

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
    async def test_update_transaction_metadata_success(self, billing_repo, sample_transaction_data, mock_table):
        """Test successful metadata update"""
        mock_table.data = [sample_transaction_data.copy()]
        
        new_metadata = {"updated": True}
        
        updated_transaction = await billing_repo.update_transaction_metadata(
            UUID(sample_transaction_data["id"]),
            new_metadata
        )
        
        assert isinstance(updated_transaction, TransactionRecord)
        assert "updated" in updated_transaction.metadata
        assert updated_transaction.metadata["updated"] is True

    @pytest.mark.asyncio
    async def test_update_transaction_metadata_not_found(self, billing_repo):
        """Test updating metadata for non-existent transaction"""
        with pytest.raises(TransactionNotFoundError):
            await billing_repo.update_transaction_metadata(uuid4(), {"test": "data"})

    @pytest.mark.asyncio
    async def test_count_transactions_for_user(self, billing_repo, sample_user_id, mock_table):
        """Test counting transactions for user"""
        test_transactions = [
            {"id": str(uuid4()), "user_id": str(sample_user_id)},
            {"id": str(uuid4()), "user_id": str(sample_user_id)}
        ]
        mock_table.data = test_transactions
        
        count = await billing_repo.count_transactions_for_user(sample_user_id)
        assert isinstance(count, int)
        assert count == 2

    @pytest.mark.asyncio
    async def test_get_user_transaction_summary(self, billing_repo, sample_user_id, mock_table):
        """Test getting transaction summary"""
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
            }
        ]
        mock_table.data = test_transactions
        
        summary = await billing_repo.get_user_transaction_summary(sample_user_id)
        
        assert isinstance(summary, BillingSummary)
        assert summary.user_id == sample_user_id

    @pytest.mark.asyncio
    async def test_get_usage_analytics(self, billing_repo, sample_user_id, mock_table):
        """Test getting usage analytics"""
        usage_transactions = [
            {
                "id": str(uuid4()),
                "user_id": str(sample_user_id),
                "transaction_type": "usage",
                "credit_amount": -10,
                "credit_balance_after": 90,
                "description": "Usage",
                "metadata": {},
                "created_at": datetime.utcnow().isoformat()
            }
        ]
        mock_table.data = usage_transactions
        
        analytics = await billing_repo.get_usage_analytics(sample_user_id, period_days=30)
        
        assert analytics.user_id == sample_user_id
        assert analytics.period_days == 30

    @pytest.mark.asyncio
    async def test_delete_transaction_success(self, billing_repo, sample_transaction_data, mock_table):
        """Test successful transaction deletion"""
        mock_table.data = [sample_transaction_data]
        
        result = await billing_repo.delete_transaction(UUID(sample_transaction_data["id"]))
        assert result is True

    @pytest.mark.asyncio
    async def test_health_check_success(self, billing_repo):
        """Test successful health check"""
        health = await billing_repo.health_check()
        
        assert isinstance(health, dict)
        assert "healthy" in health

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

    @pytest.mark.asyncio
    async def test_create_usage_transaction(self, billing_repo, sample_user_id):
        """Test convenience method for usage transactions"""
        service_id = uuid4()
        
        transaction = await billing_repo.create_usage_transaction(
            user_id=sample_user_id,
            credit_amount=10,
            credit_balance_after=90,
            description="Test usage",
            service_reference=service_id
        )
        
        assert transaction.transaction_type == "usage"
        assert transaction.credit_amount == -10
        assert transaction.reference_id == service_id

    @pytest.mark.asyncio
    async def test_complete_purchase_flow(self, billing_repo, sample_user_id):
        """Test complete purchase transaction flow"""
        stripe_session_id = uuid4()
        
        # Create purchase transaction
        purchase = await billing_repo.create_purchase_transaction(
            user_id=sample_user_id,
            credit_amount=100,
            credit_balance_after=100,
            usd_amount=5.0,
            usd_per_credit=0.05,
            stripe_session_id=stripe_session_id,
            description="Test purchase"
        )
        
        # Update metadata
        updated_transaction = await billing_repo.update_transaction_metadata(
            purchase.id,
            {"status": "completed"}
        )
        assert "status" in updated_transaction.metadata
        assert updated_transaction.metadata["status"] == "completed"