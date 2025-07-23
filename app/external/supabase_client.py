# app/external/supabase_client.py
"""
Supabase Database Client - External service integration for Supabase operations.
Provides database operations, authentication, storage, and real-time features with proper error handling.
"""
import logging
import time
import json
from typing import Dict, Any, List, Optional, Union
from datetime import datetime, timedelta
import httpx
from urllib.parse import urlencode

from app.core.config import settings
from app.core.exceptions import APIError, ValidationError, AuthenticationError, NotFoundError

logger = logging.getLogger(__name__)


class SupabaseClient:
    """
    Supabase client with database operations, authentication, and real-time features.
    Handles CRUD operations, RLS, authentication, and storage with proper error handling.
    """
    
    # API endpoints
    REST_API_PATH = "/rest/v1"
    AUTH_API_PATH = "/auth/v1"
    STORAGE_API_PATH = "/storage/v1"
    REALTIME_API_PATH = "/realtime/v1"
    
    # Database operation types
    SELECT = "select"
    INSERT = "insert"
    UPDATE = "update"
    DELETE = "delete"
    UPSERT = "upsert"
    
    # Rate limiting
    MAX_REQUESTS_PER_SECOND = 100
    MAX_CONNECTIONS = 20
    
    def __init__(self):
        self.url = settings.database_url
        self.key = settings.database_key
        self.service_key = settings.database_service_key
        self.jwt_secret = settings.database_jwt_secret
        
        # Remove trailing slash from URL
        if self.url.endswith('/'):
            self.url = self.url[:-1]
        
        # Rate limiting state
        self._request_times = []
        self._last_request_time = 0
        
        # Circuit breaker state
        self._circuit_breaker = {
            "failure_count": 0,
            "last_failure": None,
            "state": "closed"
        }
        
        # Connection pool
        self._connection_pool = None
    
    # --- Database Operations ---
    
    async def select(
        self,
        table: str,
        columns: str = "*",
        filters: Optional[Dict[str, Any]] = None,
        order_by: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        user_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Select data from a table.
        
        Args:
            table: Table name
            columns: Columns to select (default: "*")
            filters: Filter conditions
            order_by: Order by clause
            limit: Limit number of results
            offset: Offset for pagination
            user_id: User ID for RLS
            
        Returns:
            List of records
        """
        if not table:
            raise ValidationError("Table name is required")
        
        params = {}
        
        # Add select columns
        if columns != "*":
            params["select"] = columns
        
        # Add filters
        if filters:
            for key, value in filters.items():
                if isinstance(value, dict):
                    # Handle operators like {"gt": 10}, {"like": "%test%"}
                    for op, val in value.items():
                        params[f"{key}"] = f"{op}.{val}"
                else:
                    params[f"{key}"] = f"eq.{value}"
        
        # Add ordering
        if order_by:
            params["order"] = order_by
        
        # Add pagination
        if limit:
            params["limit"] = str(limit)
        if offset:
            params["offset"] = str(offset)
        
        response = await self._make_request(
            "GET",
            f"{self.REST_API_PATH}/{table}",
            params=params,
            user_id=user_id
        )
        
        logger.info(f"Selected {len(response)} records from {table}")
        return response
    
    async def insert(
        self,
        table: str,
        data: Union[Dict[str, Any], List[Dict[str, Any]]],
        return_data: bool = True,
        user_id: Optional[str] = None
    ) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
        """
        Insert data into a table.
        
        Args:
            table: Table name
            data: Data to insert (single record or list of records)
            return_data: Whether to return inserted data
            user_id: User ID for RLS
            
        Returns:
            Inserted record(s)
        """
        if not table:
            raise ValidationError("Table name is required")
        
        if not data:
            raise ValidationError("Data is required")
        
        headers = {
            "Content-Type": "application/json"
        }
        
        if return_data:
            headers["Prefer"] = "return=representation"
        
        response = await self._make_request(
            "POST",
            f"{self.REST_API_PATH}/{table}",
            json=data,
            headers=headers,
            user_id=user_id
        )
        
        if isinstance(data, list):
            logger.info(f"Inserted {len(data)} records into {table}")
        else:
            logger.info(f"Inserted 1 record into {table}")
        
        return response
    
    async def update(
        self,
        table: str,
        data: Dict[str, Any],
        filters: Dict[str, Any],
        return_data: bool = True,
        user_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Update data in a table.
        
        Args:
            table: Table name
            data: Data to update
            filters: Filter conditions
            return_data: Whether to return updated data
            user_id: User ID for RLS
            
        Returns:
            Updated records
        """
        if not table:
            raise ValidationError("Table name is required")
        
        if not data:
            raise ValidationError("Update data is required")
        
        if not filters:
            raise ValidationError("Filters are required for updates")
        
        params = {}
        for key, value in filters.items():
            if isinstance(value, dict):
                for op, val in value.items():
                    params[f"{key}"] = f"{op}.{val}"
            else:
                params[f"{key}"] = f"eq.{value}"
        
        headers = {
            "Content-Type": "application/json"
        }
        
        if return_data:
            headers["Prefer"] = "return=representation"
        
        response = await self._make_request(
            "PATCH",
            f"{self.REST_API_PATH}/{table}",
            json=data,
            params=params,
            headers=headers,
            user_id=user_id
        )
        
        logger.info(f"Updated {len(response)} records in {table}")
        return response
    
    async def delete(
        self,
        table: str,
        filters: Dict[str, Any],
        return_data: bool = True,
        user_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Delete data from a table.
        
        Args:
            table: Table name
            filters: Filter conditions
            return_data: Whether to return deleted data
            user_id: User ID for RLS
            
        Returns:
            Deleted records
        """
        if not table:
            raise ValidationError("Table name is required")
        
        if not filters:
            raise ValidationError("Filters are required for deletes")
        
        params = {}
        for key, value in filters.items():
            if isinstance(value, dict):
                for op, val in value.items():
                    params[f"{key}"] = f"{op}.{val}"
            else:
                params[f"{key}"] = f"eq.{value}"
        
        headers = {}
        if return_data:
            headers["Prefer"] = "return=representation"
        
        response = await self._make_request(
            "DELETE",
            f"{self.REST_API_PATH}/{table}",
            params=params,
            headers=headers,
            user_id=user_id
        )
        
        logger.info(f"Deleted {len(response)} records from {table}")
        return response
    
    async def upsert(
        self,
        table: str,
        data: Union[Dict[str, Any], List[Dict[str, Any]]],
        on_conflict: str = "id",
        return_data: bool = True,
        user_id: Optional[str] = None
    ) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
        """
        Upsert data into a table.
        
        Args:
            table: Table name
            data: Data to upsert
            on_conflict: Column(s) to check for conflicts
            return_data: Whether to return upserted data
            user_id: User ID for RLS
            
        Returns:
            Upserted record(s)
        """
        if not table:
            raise ValidationError("Table name is required")
        
        if not data:
            raise ValidationError("Data is required")
        
        headers = {
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates"
        }
        
        if return_data:
            headers["Prefer"] += ",return=representation"
        
        response = await self._make_request(
            "POST",
            f"{self.REST_API_PATH}/{table}",
            json=data,
            headers=headers,
            user_id=user_id
        )
        
        if isinstance(data, list):
            logger.info(f"Upserted {len(data)} records into {table}")
        else:
            logger.info(f"Upserted 1 record into {table}")
        
        return response
    
    # --- Advanced Queries ---
    
    async def execute_rpc(
        self,
        function_name: str,
        params: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None
    ) -> Any:
        """
        Execute a PostgreSQL function/stored procedure.
        
        Args:
            function_name: Name of the function
            params: Function parameters
            user_id: User ID for RLS
            
        Returns:
            Function result
        """
        if not function_name:
            raise ValidationError("Function name is required")
        
        headers = {
            "Content-Type": "application/json"
        }
        
        response = await self._make_request(
            "POST",
            f"{self.REST_API_PATH}/rpc/{function_name}",
            json=params or {},
            headers=headers,
            user_id=user_id
        )
        
        logger.info(f"Executed RPC function: {function_name}")
        return response
    
    async def execute_sql(
        self,
        query: str,
        params: Optional[List[Any]] = None,
        user_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Execute raw SQL query (requires service key).
        
        Args:
            query: SQL query
            params: Query parameters
            user_id: User ID for RLS
            
        Returns:
            Query results
        """
        if not query:
            raise ValidationError("Query is required")
        
        # This would typically use a different endpoint or method
        # For now, we'll use RPC with a custom function
        return await self.execute_rpc(
            "execute_sql",
            {"query": query, "params": params or []},
            user_id=user_id
        )
    
    async def get_table_schema(self, table: str) -> Dict[str, Any]:
        """
        Get table schema information.
        
        Args:
            table: Table name
            
        Returns:
            Table schema
        """
        if not table:
            raise ValidationError("Table name is required")
        
        query = """
        SELECT column_name, data_type, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_name = $1
        ORDER BY ordinal_position
        """
        
        result = await self.execute_sql(query, [table])
        
        return {
            "table": table,
            "columns": result
        }
    
    # --- Authentication Operations ---
    
    async def sign_up(
        self,
        email: str,
        password: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Sign up a new user.
        
        Args:
            email: User email
            password: User password
            metadata: Additional user metadata
            
        Returns:
            User and session data
        """
        if not email or not password:
            raise ValidationError("Email and password are required")
        
        data = {
            "email": email,
            "password": password
        }
        
        if metadata:
            data["data"] = metadata
        
        response = await self._make_request(
            "POST",
            f"{self.AUTH_API_PATH}/signup",
            json=data,
            use_service_key=False
        )
        
        logger.info(f"Signed up user: {email}")
        return response
    
    async def sign_in(self, email: str, password: str) -> Dict[str, Any]:
        """
        Sign in a user.
        
        Args:
            email: User email
            password: User password
            
        Returns:
            User and session data
        """
        if not email or not password:
            raise ValidationError("Email and password are required")
        
        data = {
            "email": email,
            "password": password
        }
        
        response = await self._make_request(
            "POST",
            f"{self.AUTH_API_PATH}/token?grant_type=password",
            json=data,
            use_service_key=False
        )
        
        logger.info(f"Signed in user: {email}")
        return response
    
    async def sign_out(self, access_token: str) -> Dict[str, Any]:
        """
        Sign out a user.
        
        Args:
            access_token: User's access token
            
        Returns:
            Sign out result
        """
        if not access_token:
            raise ValidationError("Access token is required")
        
        headers = {
            "Authorization": f"Bearer {access_token}"
        }
        
        response = await self._make_request(
            "POST",
            f"{self.AUTH_API_PATH}/logout",
            headers=headers,
            use_service_key=False
        )
        
        logger.info("Signed out user")
        return response
    
    async def get_user(self, access_token: str) -> Dict[str, Any]:
        """
        Get user information.
        
        Args:
            access_token: User's access token
            
        Returns:
            User data
        """
        if not access_token:
            raise ValidationError("Access token is required")
        
        headers = {
            "Authorization": f"Bearer {access_token}"
        }
        
        response = await self._make_request(
            "GET",
            f"{self.AUTH_API_PATH}/user",
            headers=headers,
            use_service_key=False
        )
        
        return response
    
    async def update_user(
        self,
        access_token: str,
        updates: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Update user information.
        
        Args:
            access_token: User's access token
            updates: User updates
            
        Returns:
            Updated user data
        """
        if not access_token:
            raise ValidationError("Access token is required")
        
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        
        response = await self._make_request(
            "PUT",
            f"{self.AUTH_API_PATH}/user",
            json=updates,
            headers=headers,
            use_service_key=False
        )
        
        logger.info("Updated user profile")
        return response
    
    # --- Storage Operations ---
    
    async def upload_file(
        self,
        bucket: str,
        file_path: str,
        file_data: bytes,
        content_type: str = "application/octet-stream",
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Upload a file to storage.
        
        Args:
            bucket: Storage bucket name
            file_path: File path within bucket
            file_data: File content
            content_type: File content type
            user_id: User ID for RLS
            
        Returns:
            Upload result
        """
        if not bucket or not file_path:
            raise ValidationError("Bucket and file path are required")
        
        headers = {
            "Content-Type": content_type
        }
        
        response = await self._make_request(
            "POST",
            f"{self.STORAGE_API_PATH}/object/{bucket}/{file_path}",
            data=file_data,
            headers=headers,
            user_id=user_id
        )
        
        logger.info(f"Uploaded file: {bucket}/{file_path}")
        return response
    
    async def download_file(
        self,
        bucket: str,
        file_path: str,
        user_id: Optional[str] = None
    ) -> bytes:
        """
        Download a file from storage.
        
        Args:
            bucket: Storage bucket name
            file_path: File path within bucket
            user_id: User ID for RLS
            
        Returns:
            File content
        """
        if not bucket or not file_path:
            raise ValidationError("Bucket and file path are required")
        
        response = await self._make_request(
            "GET",
            f"{self.STORAGE_API_PATH}/object/{bucket}/{file_path}",
            user_id=user_id,
            return_raw=True
        )
        
        logger.info(f"Downloaded file: {bucket}/{file_path}")
        return response
    
    async def delete_file(
        self,
        bucket: str,
        file_path: str,
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Delete a file from storage.
        
        Args:
            bucket: Storage bucket name
            file_path: File path within bucket
            user_id: User ID for RLS
            
        Returns:
            Delete result
        """
        if not bucket or not file_path:
            raise ValidationError("Bucket and file path are required")
        
        response = await self._make_request(
            "DELETE",
            f"{self.STORAGE_API_PATH}/object/{bucket}/{file_path}",
            user_id=user_id
        )
        
        logger.info(f"Deleted file: {bucket}/{file_path}")
        return response
    
    # --- Utility Methods ---
    
    async def health_check(self) -> Dict[str, Any]:
        """
        Perform health check on Supabase instance.
        
        Returns:
            Health status
        """
        try:
            # Simple query to check database connectivity
            response = await self.select(
                "user_profiles",
                columns="count(*)",
                limit=1
            )
            
            return {
                "status": "healthy",
                "database": "connected",
                "timestamp": datetime.utcnow().isoformat(),
                "circuit_breaker": self._circuit_breaker["state"]
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "database": "disconnected",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat(),
                "circuit_breaker": self._circuit_breaker["state"]
            }
    
    async def get_connection_info(self) -> Dict[str, Any]:
        """Get connection information."""
        return {
            "url": self.url,
            "authenticated": bool(self.key),
            "service_key_configured": bool(self.service_key),
            "jwt_secret_configured": bool(self.jwt_secret),
            "circuit_breaker_state": self._circuit_breaker["state"],
            "failure_count": self._circuit_breaker["failure_count"],
            "requests_last_second": len(self._request_times)
        }
    
    # --- Core HTTP Operations ---
    
    async def _make_request(
        self,
        method: str,
        endpoint: str,
        json: Optional[Any] = None,
        data: Optional[bytes] = None,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        user_id: Optional[str] = None,
        use_service_key: bool = True,
        return_raw: bool = False
    ) -> Any:
        """
        Make authenticated request to Supabase API.
        
        Args:
            method: HTTP method
            endpoint: API endpoint
            json: JSON data
            data: Raw data
            params: Query parameters
            headers: Request headers
            user_id: User ID for RLS
            use_service_key: Whether to use service key
            return_raw: Whether to return raw response
            
        Returns:
            API response
        """
        # Check circuit breaker
        if not self._check_circuit_breaker():
            raise APIError("Circuit breaker is open - too many failures")
        
        # Apply rate limiting
        await self._apply_rate_limit()
        
        # Prepare headers
        request_headers = {
            "apikey": self.key,
            "User-Agent": "supabase-python-client"
        }
        
        if use_service_key and self.service_key:
            request_headers["Authorization"] = f"Bearer {self.service_key}"
        elif user_id:
            # Generate user JWT for RLS
            user_jwt = self._generate_user_jwt(user_id)
            request_headers["Authorization"] = f"Bearer {user_jwt}"
        
        if headers:
            request_headers.update(headers)
        
        url = f"{self.url}{endpoint}"
        
        try:
            async with self._get_http_client() as client:
                response = await client.request(
                    method,
                    url,
                    json=json,
                    content=data,
                    params=params,
                    headers=request_headers
                )
                
                if response.status_code >= 400:
                    self._record_failure()
                    
                    if response.status_code == 401:
                        raise AuthenticationError("Invalid API key or authorization")
                    elif response.status_code == 403:
                        raise AuthenticationError("Insufficient permissions")
                    elif response.status_code == 404:
                        raise NotFoundError("Resource not found")
                    elif response.status_code == 429:
                        raise APIError("Rate limit exceeded")
                    else:
                        try:
                            error_data = response.json()
                            error_msg = error_data.get("message", str(response.status_code))
                            raise APIError(f"Supabase API error: {error_msg}")
                        except:
                            raise APIError(f"Supabase API error: {response.status_code}")
                
                self._record_success()
                
                if return_raw:
                    return response.content
                
                # Handle empty responses
                if response.status_code == 204:
                    return {}
                
                return response.json()
                
        except httpx.RequestError as e:
            self._record_failure()
            raise APIError(f"Network error: {e}")
    
    def _generate_user_jwt(self, user_id: str) -> str:
        """
        Generate JWT token for user authentication.
        
        Args:
            user_id: User ID
            
        Returns:
            JWT token
        """
        # This is a simplified JWT generation
        # In production, you'd use a proper JWT library
        import jwt
        
        payload = {
            "sub": user_id,
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,  # 1 hour
            "role": "authenticated"
        }
        
        return jwt.encode(payload, self.jwt_secret, algorithm="HS256")
    
    # --- Helper Methods ---
    
    def _get_http_client(self) -> httpx.AsyncClient:
        """Get HTTP client with connection pooling."""
        return httpx.AsyncClient(
            timeout=30.0,
            limits=httpx.Limits(
                max_keepalive_connections=10,
                max_connections=self.MAX_CONNECTIONS
            )
        )
    
    async def _apply_rate_limit(self):
        """Apply rate limiting to prevent API quota exhaustion."""
        now = time.time()
        
        # Remove old requests (older than 1 second)
        self._request_times = [t for t in self._request_times if now - t < 1.0]
        
        # Check if we need to wait
        if len(self._request_times) >= self.MAX_REQUESTS_PER_SECOND:
            sleep_time = 1.0 - (now - self._request_times[0])
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)
        
        # Small delay between requests
        if now - self._last_request_time < 0.01:
            await asyncio.sleep(0.01)
        
        self._request_times.append(time.time())
        self._last_request_time = time.time()
    
    def _check_circuit_breaker(self) -> bool:
        """Check if circuit breaker allows requests."""
        now = datetime.utcnow()
        
        if self._circuit_breaker["state"] == "open":
            if (self._circuit_breaker["last_failure"] and 
                now - self._circuit_breaker["last_failure"] > timedelta(minutes=2)):
                self._circuit_breaker["state"] = "half-open"
                return True
            return False
        
        return True
    
    def _record_success(self):
        """Record successful API call."""
        self._circuit_breaker["failure_count"] = 0
        self._circuit_breaker["state"] = "closed"
    
    def _record_failure(self):
        """Record failed API call."""
        self._circuit_breaker["failure_count"] += 1
        self._circuit_breaker["last_failure"] = datetime.utcnow()
        
        if self._circuit_breaker["failure_count"] >= 5:
            self._circuit_breaker["state"] = "open"
            logger.warning("Supabase API circuit breaker opened due to failures")


# Import required modules
import asyncio
import jwt