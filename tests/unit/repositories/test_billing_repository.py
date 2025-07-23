import pytest
from uuid import uuid4
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock


from app.data.repositories.billing_repository import BillingRepository
from app.core.exceptions import (
    DuplicateTransactionError,
    InvalidTransactionTypeError,
    TransactionNotFoundError,
)

from app.models.billing import TransactionRecord

@pytest.fixture
def mock_table():
    table = MagicMock()
    return table

@pytest.fixture
def repo(mock_table):
    return BillingRepository.create_for_testing(mock_table)

@pytest.mark.asyncio
async def test_create_transaction_success(repo):
    repo.find_transaction_by_reference = AsyncMock(return_value=None)
    repo.table.insert.return_value.select.return_value.execute.return_value = [
        {
            "id": str(uuid4()),
            "user_id": str(uuid4()),
            "transaction_type": "purchase",
            "credit_amount": 100,
            "credit_balance_after": 200,
            "description": "Test",
            "reference_id": None,
            "reference_type": None,
            "usd_amount": 10.0,
            "usd_per_credit": 0.1,
            "metadata": {},
            "created_at": datetime.utcnow().isoformat()
        }
    ]

    txn = await repo.create_transaction(
        user_id=uuid4(),
        transaction_type="purchase",
        credit_amount=100,
        credit_balance_after=200,
        description="Test"
    )

    assert isinstance(txn, TransactionRecord)
    assert txn.transaction_type == "purchase"
    assert txn.credit_amount == 100

@pytest.mark.asyncio
async def test_create_transaction_duplicate_reference(repo):
    repo.find_transaction_by_reference = AsyncMock(return_value=True)
    with pytest.raises(DuplicateTransactionError):
        await repo.create_transaction(
            user_id=uuid4(),
            transaction_type="purchase",
            credit_amount=100,
            credit_balance_after=200,
            description="Test",
            reference_id=uuid4(),
            reference_type="invoice"
        )

@pytest.mark.asyncio
async def test_create_transaction_invalid_type(repo):
    with pytest.raises(InvalidTransactionTypeError):
        await repo.create_transaction(
            user_id=uuid4(),
            transaction_type="badtype",
            credit_amount=20,
            credit_balance_after=40,
            description="Bad"
        )

@pytest.mark.asyncio
async def test_get_transaction_by_id_success(repo):
    txn_id = uuid4()
    user_id = uuid4()
    txn_data = {
        "id": str(txn_id),
        "user_id": str(user_id),
        "transaction_type": "usage",
        "credit_amount": -30,
        "credit_balance_after": 70,
        "description": "Test",
        "reference_id": None,
        "reference_type": None,
        "usd_amount": None,
        "usd_per_credit": None,
        "metadata": {},
        "created_at": datetime.utcnow().isoformat()
    }
    repo.table.select.return_value.eq.return_value.execute.return_value = [txn_data]

    result = await repo.get_transaction_by_id(txn_id)
    assert isinstance(result, TransactionRecord)
    assert result.id == txn_id

@pytest.mark.asyncio
async def test_list_transactions_for_user_basic(repo):
    user_id = uuid4()
    txn_data = [
        {
            "id": str(uuid4()),
            "user_id": str(user_id),
            "transaction_type": "bonus",
            "credit_amount": 25,
            "credit_balance_after": 125,
            "description": "Bonus test",
            "reference_id": None,
            "reference_type": None,
            "usd_amount": None,
            "usd_per_credit": None,
            "metadata": {},
            "created_at": datetime.utcnow().isoformat()
        }
    ]
    repo.table.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = txn_data

    results = await repo.list_transactions_for_user(user_id)
    assert len(results) == 1
    assert results[0].transaction_type == "bonus"

@pytest.mark.asyncio
async def test_update_transaction_metadata_merges_correctly(repo):
    txn_id = uuid4()
    base_data = {
        "id": str(txn_id),
        "user_id": str(uuid4()),
        "transaction_type": "purchase",
        "credit_amount": 100,
        "credit_balance_after": 200,
        "description": "Initial",
        "reference_id": None,
        "reference_type": None,
        "usd_amount": 10.0,
        "usd_per_credit": 0.1,
        "metadata": {"a": 1},
        "created_at": datetime.utcnow().isoformat()
    }
    updated_data = base_data.copy()
    updated_data["metadata"] = {"a": 1, "b": 2}

    repo.get_transaction_by_id = AsyncMock(return_value=TransactionRecord.from_dict(base_data))
    repo.table.update.return_value.eq.return_value.select.return_value.execute.return_value = [updated_data]

    result = await repo.update_transaction_metadata(txn_id, {"b": 2})
    assert result.metadata == {"a": 1, "b": 2}

@pytest.mark.asyncio
async def test_get_transaction_by_id_not_found(repo):
    mock_execute = AsyncMock(return_value=[])
    mock_eq = MagicMock()
    mock_eq.execute = mock_execute
    repo.table.select.return_value.eq.return_value = mock_eq

    with pytest.raises(TransactionNotFoundError):
        await repo.get_transaction_by_id(uuid4())

@pytest.mark.asyncio
async def test_list_transactions_for_user_empty_result(repo):
    user_id = uuid4()
    mock_execute = AsyncMock(return_value=[])
    mock_limit = MagicMock()
    mock_limit.execute = mock_execute
    repo.table.select.return_value.eq.return_value.order.return_value.limit.return_value = mock_limit

    results = await repo.list_transactions_for_user(user_id)
    assert results == []

@pytest.mark.asyncio
async def test_update_transaction_metadata_transaction_not_found(repo):
    txn_id = uuid4()
    repo.get_transaction_by_id = AsyncMock(side_effect=TransactionNotFoundError("Not found"))
    with pytest.raises(TransactionNotFoundError):
        await repo.update_transaction_metadata(txn_id, {"b": 2})

@pytest.mark.asyncio
async def test_update_transaction_metadata_invalid_metadata_type(repo):
    txn_id = uuid4()
    base_data = {
        "id": str(txn_id),
        "user_id": str(uuid4()),
        "transaction_type": "purchase",
        "credit_amount": 100,
        "credit_balance_after": 200,
        "description": "Initial",
        "reference_id": None,
        "reference_type": None,
        "usd_amount": 10.0,
        "usd_per_credit": 0.1,
        "metadata": {"a": 1},
        "created_at": datetime.utcnow().isoformat()
    }
    repo.get_transaction_by_id = AsyncMock(return_value=TransactionRecord.from_dict(base_data))

    mock_update = MagicMock()
    mock_select = MagicMock()
    mock_execute = AsyncMock(return_value=[base_data])
    mock_select.execute = mock_execute
    mock_update.eq.return_value.select.return_value = mock_select
    repo.table.update.return_value = mock_update

    with pytest.raises(TypeError):
        await repo.update_transaction_metadata(txn_id, ["invalid", "list"])
