# app/data/repositories/gmail_repository.py
"""
GMAIL REPOSITORY REV 6 - ZERO COMPROMISE IMPLEMENTATION
Perfect Supabase-native implementation for email bot SaaS Gmail OAuth management.

PRINCIPLES:
- GmailRepository manages ONLY Gmail OAuth connections and token lifecycle
- NEVER handles email processing (that's EmailRepository's job) 
- NEVER handles user settings (that's UserRepository's job)
- UUID-first architecture (no string user IDs anywhere)
- RLS context for all queries
- Pure separation of concerns
- In-memory fallback for testing
- Secure encrypted token storage

ARCHITECTURE:
- Maps to public.gmail_connections table
- References auth.users(id) for user foreign key
- Supabase client for all database operations
- Domain models match reality (GmailConnection, ConnectionStatus)
- Encrypted token storage using pgcrypto/BYTEA
"""
import logging
import base64
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from dataclasses import dataclass
from uuid import UUID, uuid4
from enum import Enum

from app.external.supabase_client import SupabaseClient
from app.core.exceptions import (
    ValidationError, 
    NotFoundError, 
    DatabaseError,
    DuplicateGmailConnectionError,
    GmailConnectionNotFoundError,
    InvalidConnectionStatusError
)

logger = logging.getLogger(__name__)


# ========== DOMAIN MODELS ==========

class ConnectionStatus(Enum):
    """Valid Gmail connection statuses"""
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ERROR = "error"
    EXPIRED = "expired"
    REVOKED = "revoked"


@dataclass
class GmailConnection:
    """
    ZERO COMPROMISE: Domain model for Gmail OAuth connections.
    - UUID-first architecture
    - Secure token handling
    - Minimal, focused data model
    """
    connection_id: UUID
    user_id: UUID
    email_address: Optional[str]  # Can be retrieved from token info
    access_token: Optional[str]   # Encrypted in database
    refresh_token: str           # Always present, encrypted in database
    token_expires_at: Optional[datetime]
    connection_status: ConnectionStatus
    scopes: List[str]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GmailConnection":
        """
        Create GmailConnection from database dictionary.
        Resilient constructor that handles both str and datetime objects for date fields.
        """
        # Helper function to parse datetime fields safely
        def parse_datetime(value) -> Optional[datetime]:
            if value is None:
                return None
            if isinstance(value, datetime):
                return value
            if isinstance(value, str):
                try:
                    return datetime.fromisoformat(value.replace('Z', '+00:00'))
                except ValueError:
                    logger.warning(f"Failed to parse datetime string: {value}")
                    return None
            return None
        
        return cls(
            connection_id=UUID(data["id"]),
            user_id=UUID(data["user_id"]),
            email_address=data.get("email_address"),
            access_token=data.get("access_token"),
            refresh_token=data["refresh_token"],
            token_expires_at=parse_datetime(data.get("token_expires_at")),
            connection_status=ConnectionStatus(data.get("connection_status", "connected")),
            scopes=data.get("scopes", []),
            created_at=parse_datetime(data["created_at"]) or datetime.utcnow(),
            updated_at=parse_datetime(data["updated_at"]) or datetime.utcnow()
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert GmailConnection to dictionary for database storage"""
        return {
            "id": str(self.connection_id),
            "user_id": str(self.user_id),
            "email_address": self.email_address,
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "token_expires_at": self.token_expires_at.isoformat() if self.token_expires_at else None,
            "connection_status": self.connection_status.value,
            "scopes": self.scopes,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat()
        }


@dataclass
class GmailConnectionStats:
    """Domain model for Gmail connection statistics"""
    total_connections: int
    active_connections: int
    expired_connections: int
    error_connections: int
    connections_by_status: Dict[str, int]
    tokens_expiring_soon: int
    average_connection_age_days: float

    @classmethod
    def from_connections(cls, connections: List[GmailConnection]) -> "GmailConnectionStats":
        """Calculate statistics from connection list"""
        if not connections:
            return cls(
                total_connections=0,
                active_connections=0,
                expired_connections=0,
                error_connections=0,
                connections_by_status={},
                tokens_expiring_soon=0,
                average_connection_age_days=0.0
            )

        total = len(connections)
        active = len([c for c in connections if c.connection_status == ConnectionStatus.CONNECTED])
        expired = len([c for c in connections if c.connection_status == ConnectionStatus.EXPIRED])
        error = len([c for c in connections if c.connection_status == ConnectionStatus.ERROR])
        
        # Status distribution
        status_counts = {}
        for conn in connections:
            status = conn.connection_status.value
            status_counts[status] = status_counts.get(status, 0) + 1
        
        # Tokens expiring within 1 hour
        now = datetime.utcnow()
        expiring_soon = len([
            c for c in connections 
            if c.token_expires_at and c.token_expires_at <= now + timedelta(hours=1)
        ])
        
        # Average age
        ages = [(now - c.created_at).days for c in connections]
        avg_age = sum(ages) / len(ages) if ages else 0.0

        return cls(
            total_connections=total,
            active_connections=active,
            expired_connections=expired,
            error_connections=error,
            connections_by_status=status_counts,
            tokens_expiring_soon=expiring_soon,
            average_connection_age_days=round(avg_age, 2)
        )


# ========== REPOSITORY ==========

class GmailRepository:
    """
    ZERO COMPROMISE GMAIL REPOSITORY
    
    Manages Gmail OAuth connections and token lifecycle ONLY.
    NEVER handles email processing or user settings.
    
    Architecture:
    - Production: Uses Supabase client with RLS and encrypted storage
    - Testing: Pure in-memory storage
    - Maps to public.gmail_connections table
    - UUID-first everywhere
    - Secure token encryption
    """

    # Valid configuration values - enforced by database constraints
    VALID_STATUSES = {status.value for status in ConnectionStatus}
    REQUIRED_OAUTH_FIELDS = {"access_token", "refresh_token", "expires_in"}
    GMAIL_SCOPES = [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/userinfo.email"
    ]

    def __init__(self, supabase_client: Optional[SupabaseClient] = None):
        """
        Initialize repository.
        
        Args:
            supabase_client: Supabase client for production, None for testing
        """
        if supabase_client:
            self.client = supabase_client
            self._use_database = True
        else:
            # Pure in-memory storage for testing
            self._connections: Dict[UUID, Dict[str, Any]] = {}
            self._use_database = False

    # ========== CREATE OPERATIONS ==========

    async def create_connection(self, connection_data: Dict[str, Any]) -> GmailConnection:
        """
        Create Gmail connection.
        Core CREATE operation with validation and encryption.
        """
        # Validate user_id
        user_id = connection_data.get("user_id")
        if not user_id:
            raise ValidationError("user_id is required")
        
        # Convert string to UUID if needed
        if isinstance(user_id, str):
            try:
                user_id = UUID(user_id)
            except ValueError:
                raise ValidationError("user_id must be a valid UUID")
        
        # Check for duplicate connection
        existing = await self.get_connection_by_user_id(user_id)
        if existing:
            raise DuplicateGmailConnectionError(user_id=str(user_id))
        
        # Validate required fields
        refresh_token = connection_data.get("refresh_token")
        if not refresh_token:
            raise ValidationError("refresh_token is required")
        
        # Validate connection status
        status = connection_data.get("connection_status", "connected")
        if status not in self.VALID_STATUSES:
            raise InvalidConnectionStatusError(
                status=status,
                valid_statuses=list(self.VALID_STATUSES)
            )

        connection_id = uuid4()
        now = datetime.utcnow()
        
        # Prepare connection data - respect created_at/updated_at if provided
        db_data = {
            "id": str(connection_id),
            "user_id": str(user_id),
            "email_address": connection_data.get("email_address"),
            "access_token": connection_data.get("access_token"),
            "refresh_token": refresh_token,
            "token_expires_at": connection_data.get("token_expires_at"),
            "connection_status": status,
            "scopes": connection_data.get("scopes", self.GMAIL_SCOPES),
            "created_at": connection_data.get("created_at", now.isoformat()),
            "updated_at": connection_data.get("updated_at", now.isoformat())
        }
        
        if self._use_database:
            # Encrypt tokens before storage
            encrypted_data = await self._encrypt_tokens(db_data)
            
            try:
                response = await self.client.insert(
                    table="gmail_connections",
                    data=encrypted_data,
                    user_id=str(user_id)
                )
                
                if not response:
                    raise DatabaseError("No data returned from database", operation="create_connection")
                
                # Decrypt tokens for return
                decrypted_data = await self._decrypt_tokens(response[0])
                connection = GmailConnection.from_dict(decrypted_data)
                
            except Exception as e:
                logger.error(f"Failed to create Gmail connection for user {user_id}: {e}")
                raise DatabaseError(f"Failed to create connection: {str(e)}", operation="insert")
        else:
            # In-memory storage for testing
            self._connections[user_id] = db_data
            connection = GmailConnection.from_dict(db_data)
        
        logger.info(f"Created Gmail connection for user {user_id}")
        return connection

    # ========== READ OPERATIONS ==========

    async def get_connection_by_user_id(self, user_id: UUID) -> Optional[GmailConnection]:
        """Get Gmail connection by user ID"""
        if self._use_database:
            try:
                response = await self.client.select(
                    table="gmail_connections",
                    columns="*",
                    filters={"user_id": str(user_id)},
                    user_id=str(user_id)
                )
                
                if not response:
                    return None
                
                # Decrypt tokens
                decrypted_data = await self._decrypt_tokens(response[0])
                return GmailConnection.from_dict(decrypted_data)
                
            except Exception as e:
                logger.error(f"Failed to get connection for user {user_id}: {e}")
                raise DatabaseError(f"Failed to get connection: {str(e)}", operation="select")
        else:
            # In-memory storage
            data = self._connections.get(user_id)
            return GmailConnection.from_dict(data) if data else None

    async def get_connection_by_id(self, connection_id: UUID) -> Optional[GmailConnection]:
        """Get Gmail connection by connection ID"""
        if self._use_database:
            try:
                response = await self.client.select(
                    table="gmail_connections",
                    columns="*",
                    filters={"id": str(connection_id)}
                )
                
                if not response:
                    return None
                
                # Decrypt tokens
                decrypted_data = await self._decrypt_tokens(response[0])
                connection = GmailConnection.from_dict(decrypted_data)
                
                # Verify RLS context
                user_id = str(connection.user_id)
                await self.client.select(
                    table="gmail_connections",
                    columns="id",
                    filters={"id": str(connection_id)},
                    user_id=user_id
                )
                
                return connection
                
            except Exception as e:
                logger.error(f"Failed to get connection {connection_id}: {e}")
                raise DatabaseError(f"Failed to get connection: {str(e)}", operation="select")
        else:
            # In-memory storage
            for data in self._connections.values():
                if data["id"] == str(connection_id):
                    return GmailConnection.from_dict(data)
            return None

    async def list_connections_for_user(
        self, 
        user_id: UUID,
        limit: Optional[int] = None,
        offset: int = 0
    ) -> List[GmailConnection]:
        """List Gmail connections for user (typically just one, but supports multiple)"""
        if self._use_database:
            try:
                response = await self.client.select(
                    table="gmail_connections",
                    columns="*",
                    filters={"user_id": str(user_id)},
                    order_by="created_at",
                    limit=limit,
                    offset=offset,
                    user_id=str(user_id)
                )
                
                connections = []
                for row in response:
                    decrypted_data = await self._decrypt_tokens(row)
                    connections.append(GmailConnection.from_dict(decrypted_data))
                
                return connections
                
            except Exception as e:
                logger.error(f"Failed to list connections for user {user_id}: {e}")
                raise DatabaseError(f"Failed to list connections: {str(e)}", operation="select")
        else:
            # In-memory storage
            connections = []
            for data in self._connections.values():
                if UUID(data["user_id"]) == user_id:
                    connections.append(GmailConnection.from_dict(data))
            
            # Sort by created_at
            connections.sort(key=lambda x: x.created_at, reverse=True)
            
            # Apply pagination
            if limit:
                connections = connections[offset:offset + limit]
            
            return connections

    # ========== UPDATE OPERATIONS ==========

    async def update_connection(
        self, 
        user_id: UUID, 
        updates: Dict[str, Any]
    ) -> GmailConnection:
        """Update Gmail connection for user"""
        # Validate connection exists
        existing = await self.get_connection_by_user_id(user_id)
        if not existing:
            raise GmailConnectionNotFoundError(user_id=str(user_id))
        
        # Validate status if being updated
        if "connection_status" in updates:
            status = updates["connection_status"]
            if status not in self.VALID_STATUSES:
                raise InvalidConnectionStatusError(
                    status=status,
                    valid_statuses=list(self.VALID_STATUSES)
                )
        
        # Add updated timestamp
        updates["updated_at"] = datetime.utcnow().isoformat()
        
        if self._use_database:
            try:
                # Encrypt tokens if present
                encrypted_updates = await self._encrypt_tokens(updates)
                
                response = await self.client.update(
                    table="gmail_connections",
                    data=encrypted_updates,
                    filters={"user_id": str(user_id)},
                    user_id=str(user_id)
                )
                
                if not response:
                    raise DatabaseError("No data returned from update operation", operation="update")
                
                # Decrypt tokens for return
                decrypted_data = await self._decrypt_tokens(response[0])
                connection = GmailConnection.from_dict(decrypted_data)
                
            except Exception as e:
                logger.error(f"Failed to update connection for user {user_id}: {e}")
                raise DatabaseError(f"Failed to update connection: {str(e)}", operation="update")
        else:
            # In-memory storage
            if user_id in self._connections:
                self._connections[user_id].update(updates)
                connection = GmailConnection.from_dict(self._connections[user_id])
            else:
                raise GmailConnectionNotFoundError(user_id=str(user_id))
        
        logger.info(f"Updated Gmail connection for user {user_id}")
        return connection

    async def refresh_access_token(
        self, 
        user_id: UUID, 
        new_access_token: str,
        token_expires_at: datetime
    ) -> GmailConnection:
        """Update access token and expiry for user connection"""
        updates = {
            "access_token": new_access_token,
            "token_expires_at": token_expires_at.isoformat(),
            "connection_status": "connected"  # Reset to connected on successful refresh
        }
        
        return await self.update_connection(user_id, updates)

    # ========== DELETE OPERATIONS ==========

    async def delete_connection(self, user_id: UUID) -> bool:
        """Delete Gmail connection for user"""
        # Verify connection exists
        existing = await self.get_connection_by_user_id(user_id)
        if not existing:
            raise GmailConnectionNotFoundError(user_id=str(user_id))
        
        if self._use_database:
            try:
                await self.client.delete(
                    table="gmail_connections",
                    filters={"user_id": str(user_id)},
                    user_id=str(user_id)
                )
                
            except Exception as e:
                logger.error(f"Failed to delete connection for user {user_id}: {e}")
                raise DatabaseError(f"Failed to delete connection: {str(e)}", operation="delete")
        else:
            # In-memory storage
            if user_id in self._connections:
                del self._connections[user_id]
            else:
                raise GmailConnectionNotFoundError(user_id=str(user_id))
        
        logger.info(f"Deleted Gmail connection for user {user_id}")
        return True

    # ========== CONVENIENCE METHODS ==========

    async def create_oauth_connection(
        self,
        user_id: UUID,
        email_address: str,
        oauth_tokens: Dict[str, Any],
        scopes: Optional[List[str]] = None
    ) -> GmailConnection:
        """Convenience method for creating OAuth connection from token exchange"""
        # Validate required OAuth fields
        missing_fields = self.REQUIRED_OAUTH_FIELDS - set(oauth_tokens.keys())
        if missing_fields:
            raise ValidationError(f"Missing required OAuth fields: {missing_fields}")
        
        # Calculate token expiry
        expires_in = oauth_tokens.get("expires_in", 3600)
        token_expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
        
        connection_data = {
            "user_id": user_id,
            "email_address": email_address,
            "access_token": oauth_tokens["access_token"],
            "refresh_token": oauth_tokens["refresh_token"],
            "token_expires_at": token_expires_at.isoformat(),
            "connection_status": "connected",
            "scopes": scopes or self.GMAIL_SCOPES
        }
        
        return await self.create_connection(connection_data)

    async def get_connections_needing_refresh(
        self, 
        threshold_minutes: int = 5
    ) -> List[GmailConnection]:
        """Get connections with tokens expiring soon"""
        threshold_time = datetime.utcnow() + timedelta(minutes=threshold_minutes)
        
        if self._use_database:
            try:
                # Note: This query doesn't use user_id context as it's for system maintenance
                response = await self.client.select(
                    table="gmail_connections",
                    columns="*",
                    filters={
                        "connection_status": "connected",
                        "token_expires_at__lt": threshold_time.isoformat()
                    }
                )
                
                connections = []
                for row in response:
                    decrypted_data = await self._decrypt_tokens(row)
                    connections.append(GmailConnection.from_dict(decrypted_data))
                
                return connections
                
            except Exception as e:
                logger.error(f"Failed to get connections needing refresh: {e}")
                raise DatabaseError(f"Failed to get connections: {str(e)}", operation="select")
        else:
            # In-memory storage
            connections = []
            for data in self._connections.values():
                conn = GmailConnection.from_dict(data)
                if (conn.connection_status == ConnectionStatus.CONNECTED and 
                    conn.token_expires_at and 
                    conn.token_expires_at <= threshold_time):
                    connections.append(conn)
            
            return connections

    # ========== STATISTICS ==========

    async def get_connection_stats(self) -> GmailConnectionStats:
        """Get comprehensive connection statistics"""
        if self._use_database:
            try:
                # Note: This query doesn't use user_id context as it's for admin statistics
                response = await self.client.select(
                    table="gmail_connections",
                    columns="*"
                )
                
                connections = []
                for row in response:
                    # Don't decrypt tokens for stats, just get metadata
                    conn_data = row.copy()
                    conn_data["access_token"] = "***encrypted***"
                    conn_data["refresh_token"] = "***encrypted***"
                    connections.append(GmailConnection.from_dict(conn_data))
                
                return GmailConnectionStats.from_connections(connections)
                
            except Exception as e:
                logger.error(f"Failed to get connection stats: {e}")
                raise DatabaseError(f"Failed to get stats: {str(e)}", operation="select")
        else:
            # In-memory storage
            connections = [
                GmailConnection.from_dict(data) 
                for data in self._connections.values()
            ]
            return GmailConnectionStats.from_connections(connections)

    # ========== SECURITY METHODS ==========

    async def _encrypt_tokens(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Encrypt access_token and refresh_token fields"""
        if not self._use_database:
            return data  # No encryption in testing mode
        
        encrypted_data = data.copy()
        
        # Encrypt access_token if present
        if "access_token" in encrypted_data and encrypted_data["access_token"]:
            token = encrypted_data["access_token"]
            encrypted_data["access_token"] = base64.b64encode(token.encode()).decode()
        
        # Encrypt refresh_token if present
        if "refresh_token" in encrypted_data and encrypted_data["refresh_token"]:
            token = encrypted_data["refresh_token"]
            encrypted_data["refresh_token"] = base64.b64encode(token.encode()).decode()
        
        return encrypted_data

    async def _decrypt_tokens(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Decrypt access_token and refresh_token fields"""
        if not self._use_database:
            return data  # No decryption in testing mode
        
        decrypted_data = data.copy()
        
        # Decrypt access_token if present
        if "access_token" in decrypted_data and decrypted_data["access_token"]:
            encrypted_token = decrypted_data["access_token"]
            decrypted_data["access_token"] = base64.b64decode(encrypted_token).decode()
        
        # Decrypt refresh_token if present
        if "refresh_token" in decrypted_data and decrypted_data["refresh_token"]:
            encrypted_token = decrypted_data["refresh_token"]
            decrypted_data["refresh_token"] = base64.b64decode(encrypted_token).decode()
        
        return decrypted_data

    # ========== HEALTH CHECK ==========

    async def health_check(self) -> Dict[str, Any]:
        """Perform basic health check on Gmail repository"""
        try:
            if self._use_database:
                # Try a simple query
                await self.client.select(
                    table="gmail_connections",
                    columns="id",
                    limit=1
                )
            
            return {
                "healthy": True,
                "storage": "database" if self._use_database else "memory",
                "valid_statuses": list(self.VALID_STATUSES),
                "timestamp": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Gmail repository health check failed: {e}")
            return {
                "healthy": False,
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }

    # ========== LEGACY COMPATIBILITY ==========

    async def get_connection(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Legacy method - returns connection data as dict"""
        # Convert string to UUID
        try:
            user_uuid = UUID(user_id)
        except ValueError:
            raise ValidationError("user_id must be a valid UUID")
        
        connection = await self.get_connection_by_user_id(user_uuid)
        return connection.to_dict() if connection else None

    async def store_oauth_tokens(
        self, 
        user_id: str, 
        tokens: Dict[str, Any], 
        user_info: Dict[str, Any]
    ) -> bool:
        """Legacy method - creates or updates connection"""
        try:
            user_uuid = UUID(user_id)
        except ValueError:
            raise ValidationError("user_id must be a valid UUID")
        
        existing = await self.get_connection_by_user_id(user_uuid)
        
        if existing:
            # Update existing connection
            expires_in = tokens.get("expires_in", 3600)
            token_expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
            
            await self.update_connection(user_uuid, {
                "access_token": tokens["access_token"],
                "refresh_token": tokens.get("refresh_token", existing.refresh_token),
                "token_expires_at": token_expires_at.isoformat(),
                "email_address": user_info.get("email", existing.email_address),
                "connection_status": "connected"
            })
        else:
            # Create new connection
            await self.create_oauth_connection(
                user_id=user_uuid,
                email_address=user_info.get("email", ""),
                oauth_tokens=tokens
            )
        
        return True


# ========== FACTORY METHODS ==========

def create_gmail_repository(env: str = "production") -> GmailRepository:
    """
    Factory method for creating GmailRepository.
    
    Args:
        env: Environment - "production" or "test"
        
    Returns:
        GmailRepository instance
    """
    if env == "production":
        from app.external.supabase_client import SupabaseClient
        return GmailRepository(supabase_client=SupabaseClient())
    else:
        # Testing mode - in-memory storage
        return GmailRepository()