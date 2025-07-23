# app/data/repositories/billing_repository.py
"""
Pure CRUD operations for billing transactions.
Repository pattern implementation with clean separation of data access.
"""
import logging
from typing import Any, Dict, List, Optional, Protocol
from uuid import UUID
from datetime import datetime

from app.models.billing import TransactionRecord
from app.core.exceptions import (
    TransactionNotFoundError,
    DuplicateTransactionError,
    InvalidTransactionTypeError
)

logger = logging.getLogger(__name__)

class DatabaseTable(Protocol):
    """Protocol for database table operations to enable easy testing"""
    def insert(self, data: Dict[str, Any]) -> "QueryBuilder": ...
    def select(self, columns: str = "*") -> "QueryBuilder": ...
    def update(self, data: Dict[str, Any]) -> "QueryBuilder": ...
    def delete(self) -> "QueryBuilder": ...

class QueryBuilder(Protocol):
    """Protocol for query builder operations"""
    def eq(self, column: str, value: Any) -> "QueryBuilder": ...
    def limit(self, count: int) -> "QueryBuilder": ...
    def offset(self, count: int) -> "QueryBuilder": ...
    def order(self, column: str, desc: bool = False) -> "QueryBuilder": ...
    def select(self, columns: str = "*") -> "QueryBuilder": ...
    def execute(self) -> "QueryResponse": ...

class QueryResponse(Protocol):
    """Protocol for query response"""
    data: List[Dict[str, Any]]
    error: Optional[Exception]
    count: Optional[int]

class BillingRepository:
    """Pure CRUD operations for billing transactions - no business logic"""
    
    # Valid transaction types as defined in database schema
    VALID_TRANSACTION_TYPES = {"purchase", "usage", "refund", "bonus", "adjustment"}
    
    def __init__(self, table: Optional[DatabaseTable] = None):
        """
        Initialize repository with optional table dependency for testing.
        If no table provided, uses default database connection.
        """
        if table is not None:
            self.table = table
        else:
            # Import here to avoid circular imports and enable easier testing
            from app.data.database import db
            self.table = db.table("credit_transactions")

    async def create_transaction(
        self,
        user_id: UUID,
        transaction_type: str,
        credit_amount: int,
        credit_balance_after: int,
        description: str,
        reference_id: Optional[UUID] = None,
        reference_type: Optional[str] = None,
        usd_amount: Optional[float] = None,
        usd_per_credit: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TransactionRecord:
        """Create a new transaction record in the database"""
        
        # Validate transaction type
        if transaction_type not in self.VALID_TRANSACTION_TYPES:
            raise InvalidTransactionTypeError(transaction_type)
        
        # Check for duplicate if reference_id provided
        if reference_id and reference_type:
            existing = await self.find_transaction_by_reference(reference_id, reference_type)
            if existing:
                raise DuplicateTransactionError(str(reference_id))
        
        try:
            record_data = {
                "user_id": str(user_id),
                "transaction_type": transaction_type,
                "credit_amount": credit_amount,
                "credit_balance_after": credit_balance_after,
                "description": description,
                "reference_id": str(reference_id) if reference_id else None,
                "reference_type": reference_type,
                "usd_amount": usd_amount,
                "usd_per_credit": usd_per_credit,
                "metadata": metadata or {},
                "created_at": datetime.utcnow().isoformat(),
            }
            
            response = self.table.insert(record_data).select("*").execute()
            
            # Handle response based on type (real Supabase vs mock)
            if hasattr(response, 'error') and response.error:
                logger.error(f"Database error creating transaction: {response.error}")
                raise Exception(f"Database error: {response.error}")
            
            # Handle both real Supabase response and mock response
            data = response.data if hasattr(response, 'data') else response
            if not data:
                raise Exception("No data returned from insert operation")
            
            # Handle list vs single item response
            transaction_data = data[0] if isinstance(data, list) else data
            transaction = TransactionRecord.from_dict(transaction_data)
            
            logger.info(
                f"Created transaction {transaction.id} for user {user_id}: "
                f"{transaction_type} {credit_amount} credits"
            )
            return transaction
            
        except Exception as e:
            if isinstance(e, (DuplicateTransactionError, InvalidTransactionTypeError)):
                raise
            logger.error(f"Failed to create transaction for user {user_id}: {e}")
            raise Exception(f"Failed to create transaction: {e}")

    async def get_transaction_by_id(self, transaction_id: UUID) -> Optional[TransactionRecord]:
        """Get a transaction by its ID"""
        try:
            response = self.table.select("*").eq("id", str(transaction_id)).execute()
            
            # Handle response based on type (real Supabase vs mock)
            if hasattr(response, 'error') and response.error:
                logger.error(f"Database error getting transaction {transaction_id}: {response.error}")
                raise Exception(f"Database error: {response.error}")
            
            # Handle both real Supabase response and mock response
            data = response.data if hasattr(response, 'data') else response
            if not data:
                return None
            
            # Handle list vs single item response
            transaction_data = data[0] if isinstance(data, list) else data
            return TransactionRecord.from_dict(transaction_data)
            
        except Exception as e:
            logger.error(f"Failed to get transaction {transaction_id}: {e}")
            raise Exception(f"Failed to get transaction: {e}")

    async def list_transactions_for_user(
        self, 
        user_id: UUID, 
        limit: int = 50,
        transaction_type: Optional[str] = None,
        offset: int = 0
    ) -> List[TransactionRecord]:
        """List transactions for a user with optional filtering"""
        
        # Validate transaction type if provided
        if transaction_type and transaction_type not in self.VALID_TRANSACTION_TYPES:
            raise InvalidTransactionTypeError(transaction_type)
        
        # Limit bounds checking
        limit = max(1, min(limit, 1000))  # Between 1 and 1000
        offset = max(0, offset)
        
        try:
            query = (
                self.table.select("*")
                .eq("user_id", str(user_id))
                .order("created_at", desc=True)
                .limit(limit)
            )
            
            # Only add offset if supported (some mocks might not support it)
            if hasattr(query, 'offset') and offset > 0:
                query = query.offset(offset)
            
            if transaction_type:
                query = query.eq("transaction_type", transaction_type)
            
            response = query.execute()
            
            # Handle response based on type (real Supabase vs mock)
            if hasattr(response, 'error') and response.error:
                logger.error(f"Database error listing transactions for user {user_id}: {response.error}")
                raise Exception(f"Database error: {response.error}")
            
            # Handle both real Supabase response and mock response
            data = response.data if hasattr(response, 'data') else response
            data = data or []
            
            transactions = [TransactionRecord.from_dict(row) for row in data]
            logger.debug(f"Retrieved {len(transactions)} transactions for user {user_id}")
            return transactions
            
        except Exception as e:
            if isinstance(e, InvalidTransactionTypeError):
                raise
            logger.error(f"Failed to list transactions for user {user_id}: {e}")
            raise Exception(f"Failed to list transactions: {e}")

    async def find_transaction_by_reference(
        self, 
        reference_id: UUID, 
        reference_type: str
    ) -> Optional[TransactionRecord]:
        """Find transaction by reference ID and type"""
        try:
            response = (
                self.table.select("*")
                .eq("reference_id", str(reference_id))
                .eq("reference_type", reference_type)
                .limit(1)
                .execute()
            )
            
            # Handle response based on type (real Supabase vs mock)
            if hasattr(response, 'error') and response.error:
                logger.error(f"Database error finding transaction by reference {reference_id}: {response.error}")
                raise Exception(f"Database error: {response.error}")
            
            # Handle both real Supabase response and mock response
            data = response.data if hasattr(response, 'data') else response
            if not data:
                return None
            
            # Handle list vs single item response
            transaction_data = data[0] if isinstance(data, list) else data
            return TransactionRecord.from_dict(transaction_data)
            
        except Exception as e:
            logger.error(f"Failed to find transaction by reference {reference_id}: {e}")
            raise Exception(f"Failed to find transaction: {e}")

    async def update_transaction_metadata(
        self, 
        transaction_id: UUID, 
        metadata: Dict[str, Any]
    ) -> TransactionRecord:
        """Update transaction metadata (one of the few update operations allowed)"""
        try:
            # First verify transaction exists
            existing = await self.get_transaction_by_id(transaction_id)
            if not existing:
                raise TransactionNotFoundError(str(transaction_id))
            
            # Merge with existing metadata
            updated_metadata = {**existing.metadata, **metadata}
            
            response = (
                self.table
                .update({"metadata": updated_metadata})
                .eq("id", str(transaction_id))
                .select("*")
                .execute()
            )
            
            # Handle response based on type (real Supabase vs mock)
            if hasattr(response, 'error') and response.error:
                logger.error(f"Database error updating transaction {transaction_id}: {response.error}")
                raise Exception(f"Database error: {response.error}")
            
            # Handle both real Supabase response and mock response
            data = response.data if hasattr(response, 'data') else response
            if not data:
                raise Exception("No data returned from update operation")
            
            # Handle list vs single item response
            transaction_data = data[0] if isinstance(data, list) else data
            updated_transaction = TransactionRecord.from_dict(transaction_data)
            
            logger.info(f"Updated metadata for transaction {transaction_id}")
            return updated_transaction
            
        except Exception as e:
            if isinstance(e, TransactionNotFoundError):
                raise
            logger.error(f"Failed to update transaction metadata {transaction_id}: {e}")
            raise Exception(f"Failed to update transaction: {e}")

    async def count_transactions_for_user(
        self, 
        user_id: UUID, 
        transaction_type: Optional[str] = None
    ) -> int:
        """Count total transactions for a user"""
        
        # Validate transaction type if provided
        if transaction_type and transaction_type not in self.VALID_TRANSACTION_TYPES:
            raise InvalidTransactionTypeError(transaction_type)
        
        try:
            query = self.table.select("id", count="exact").eq("user_id", str(user_id))
            
            if transaction_type:
                query = query.eq("transaction_type", transaction_type)
            
            response = query.execute()
            
            # Handle response based on type (real Supabase vs mock)
            if hasattr(response, 'error') and response.error:
                logger.error(f"Database error counting transactions for user {user_id}: {response.error}")
                raise Exception(f"Database error: {response.error}")
            
            # Handle both real Supabase response and mock response
            if hasattr(response, 'count'):
                return response.count or 0
            elif hasattr(response, 'data'):
                return len(response.data) if response.data else 0
            else:
                return len(response) if response else 0
            
        except Exception as e:
            if isinstance(e, InvalidTransactionTypeError):
                raise
            logger.error(f"Failed to count transactions for user {user_id}: {e}")
            raise Exception(f"Failed to count transactions: {e}")

    async def get_user_transaction_summary(self, user_id: UUID) -> Dict[str, Any]:
        """Get transaction summary statistics for a user"""
        try:
            # Get all transactions for summary calculation
            all_transactions = await self.list_transactions_for_user(user_id, limit=1000)
            
            summary = {
                "total_transactions": len(all_transactions),
                "total_purchased": 0,
                "total_used": 0,
                "total_refunded": 0,
                "total_bonus": 0,
                "by_type": {}
            }
            
            for txn in all_transactions:
                txn_type = txn.transaction_type
                
                # Count by type
                summary["by_type"][txn_type] = summary["by_type"].get(txn_type, 0) + 1
                
                # Sum by category
                if txn_type == "purchase" and txn.credit_amount > 0:
                    summary["total_purchased"] += txn.credit_amount
                elif txn_type == "usage" and txn.credit_amount < 0:
                    summary["total_used"] += abs(txn.credit_amount)
                elif txn_type == "refund" and txn.credit_amount > 0:
                    summary["total_refunded"] += txn.credit_amount
                elif txn_type == "bonus" and txn.credit_amount > 0:
                    summary["total_bonus"] += txn.credit_amount
            
            return summary
            
        except Exception as e:
            logger.error(f"Failed to get transaction summary for user {user_id}: {e}")
            raise Exception(f"Failed to get transaction summary: {e}")

    async def delete_transaction(self, transaction_id: UUID) -> bool:
        """Delete a transaction (use with extreme caution - prefer marking as void)"""
        try:
            # First verify transaction exists
            existing = await self.get_transaction_by_id(transaction_id)
            if not existing:
                raise TransactionNotFoundError(str(transaction_id))
            
            response = self.table.delete().eq("id", str(transaction_id)).execute()
            
            # Handle response based on type (real Supabase vs mock)
            if hasattr(response, 'error') and response.error:
                logger.error(f"Database error deleting transaction {transaction_id}: {response.error}")
                raise Exception(f"Database error: {response.error}")
            
            logger.warning(f"DELETED transaction {transaction_id} - this should be rare!")
            return True
            
        except Exception as e:
            if isinstance(e, TransactionNotFoundError):
                raise
            logger.error(f"Failed to delete transaction {transaction_id}: {e}")
            raise Exception(f"Failed to delete transaction: {e}")

    # --- Health Check Methods ---
    
    async def health_check(self) -> Dict[str, Any]:
        """Perform basic health check on billing repository"""
        try:
            # Try a simple query
            response = self.table.select("id").limit(1).execute()
            
            # Handle response based on type (real Supabase vs mock)
            if hasattr(response, 'error') and response.error:
                return {
                    "healthy": False,
                    "error": str(response.error),
                    "timestamp": datetime.utcnow().isoformat()
                }
            
            return {
                "healthy": True,
                "timestamp": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Billing repository health check failed: {e}")
            return {
                "healthy": False,
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }

    # --- Testing Support Methods ---
    
    @classmethod
    def create_for_testing(cls, mock_table: DatabaseTable) -> "BillingRepository":
        """Factory method for creating repository with mock table for testing"""
        return cls(table=mock_table)
    
    def _handle_response(self, response, operation: str = "database operation"):
        """
        Helper method to handle different response types (real Supabase vs mock).
        This centralizes the response handling logic for easier maintenance.
        """
        # Handle error responses
        if hasattr(response, 'error') and response.error:
            raise Exception(f"Database error in {operation}: {response.error}")
        
        # Extract data from response
        if hasattr(response, 'data'):
            return response.data
        else:
            # For mocks that return data directly
            return response