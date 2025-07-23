# app/external/stripe_client.py
"""
Async Stripe API client with comprehensive functionality for SaaS billing.
Handles customers, checkout sessions, payment intents, billing portal, and webhooks.
"""
import asyncio
import hashlib
import hmac
import json
import logging
import time
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlencode
import httpx

from app.core.billing_exceptions import (
    StripeError, 
    WebhookValidationError, 
    RateLimitError,
    BillingConfigurationError
)

logger = logging.getLogger(__name__)

class StripeClient:
    """
    Async Stripe API client with full SaaS billing functionality.
    Provides customer management, checkout sessions, payment processing, and webhooks.
    """
    
    # Stripe API configuration
    API_BASE = "https://api.stripe.com"
    API_VERSION = "2023-10-16"
    
    # Supported features
    SUPPORTED_CURRENCIES = ["usd", "eur", "gbp", "cad", "aud", "jpy"]
    SUPPORTED_PAYMENT_METHODS = ["card", "ideal", "sepa_debit", "bancontact", "sofort"]
    
    def __init__(self, secret_key: str, webhook_secret: str = None):
        if not secret_key:
            raise BillingConfigurationError("Stripe secret key is required")
        
        self.secret_key = secret_key
        self.webhook_secret = webhook_secret
        
        # HTTP client configuration
        self.timeout = 30.0
        self.max_retries = 3
        self.retry_delay = 1.0
        
        # Rate limiting (Stripe allows 100 req/sec, we use 80 for safety)
        self._rate_limit = 80
        self._rate_window = 1.0
        self._request_times = []
        
        # Circuit breaker
        self._circuit_breaker = {
            "failure_count": 0,
            "last_failure": None,
            "state": "closed",  # closed, open, half_open
            "failure_threshold": 5,
            "recovery_timeout": 60
        }
        
    async def _get_http_client(self) -> httpx.AsyncClient:
        """Get configured HTTP client"""
        headers = {
            "Authorization": f"Bearer {self.secret_key}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Stripe-Version": self.API_VERSION,
            "User-Agent": "SaaS-Email-Bot/1.0"
        }
        
        return httpx.AsyncClient(
            headers=headers,
            timeout=self.timeout,
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=20)
        )
    
    # --- Rate Limiting ---
    
    async def _apply_rate_limit(self):
        """Apply rate limiting to prevent hitting Stripe limits"""
        now = time.time()
        
        # Clean old request times
        self._request_times = [t for t in self._request_times if now - t < self._rate_window]
        
        # Check if we need to wait
        if len(self._request_times) >= self._rate_limit:
            sleep_time = self._rate_window - (now - self._request_times[0])
            if sleep_time > 0:
                logger.debug(f"Rate limiting: sleeping {sleep_time:.2f}s")
                await asyncio.sleep(sleep_time)
        
        self._request_times.append(now)
    
    # --- Circuit Breaker ---
    
    def _check_circuit_breaker(self) -> bool:
        """Check if circuit breaker allows requests"""
        now = time.time()
        cb = self._circuit_breaker
        
        if cb["state"] == "open":
            if cb["last_failure"] and now - cb["last_failure"] > cb["recovery_timeout"]:
                cb["state"] = "half_open"
                logger.info("Circuit breaker moving to half-open state")
                return True
            return False
        
        return True
    
    def _record_success(self):
        """Record successful request for circuit breaker"""
        self._circuit_breaker["failure_count"] = 0
        if self._circuit_breaker["state"] == "half_open":
            self._circuit_breaker["state"] = "closed"
            logger.info("Circuit breaker closed after successful request")
    
    def _record_failure(self):
        """Record failed request for circuit breaker"""
        cb = self._circuit_breaker
        cb["failure_count"] += 1
        cb["last_failure"] = time.time()
        
        if cb["failure_count"] >= cb["failure_threshold"]:
            cb["state"] = "open"
            logger.warning("Circuit breaker opened due to repeated failures")
    
    # --- Core HTTP Operations ---
    
    async def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Make authenticated request to Stripe API with retry logic"""
        
        if not self._check_circuit_breaker():
            raise StripeError("Circuit breaker is open - too many failures")
        
        await self._apply_rate_limit()
        
        url = f"{self.API_BASE}{endpoint}"
        
        # Encode form data if provided
        request_data = None
        if data:
            request_data = self._encode_form_data(data)
        
        for attempt in range(self.max_retries + 1):
            try:
                async with await self._get_http_client() as client:
                    response = await client.request(
                        method,
                        url,
                        content=request_data,
                        params=params
                    )
                    
                    # Handle response
                    if response.status_code == 429:
                        retry_after = int(response.headers.get("Retry-After", self.retry_delay))
                        if attempt < self.max_retries:
                            logger.warning(f"Rate limited, retrying in {retry_after}s")
                            await asyncio.sleep(retry_after)
                            continue
                        else:
                            raise RateLimitError(retry_after)
                    
                    response.raise_for_status()
                    result = response.json()
                    
                    self._record_success()
                    return result
                    
            except httpx.HTTPStatusError as e:
                self._record_failure()
                
                if e.response.status_code in [400, 401, 403, 404]:
                    # Client errors - don't retry
                    error_data = {}
                    try:
                        error_data = e.response.json()
                    except:
                        pass
                    
                    error_msg = error_data.get("error", {}).get("message", str(e))
                    raise StripeError(
                        f"Stripe API error: {error_msg}",
                        stripe_code=error_data.get("error", {}).get("code"),
                        status_code=e.response.status_code
                    )
                
                # Server errors - retry
                if attempt < self.max_retries:
                    wait_time = self.retry_delay * (2 ** attempt)
                    logger.warning(f"Request failed, retrying in {wait_time}s: {e}")
                    await asyncio.sleep(wait_time)
                    continue
                
                raise StripeError(f"Request failed after {self.max_retries} retries: {e}")
                
            except Exception as e:
                self._record_failure()
                if attempt < self.max_retries:
                    wait_time = self.retry_delay * (2 ** attempt)
                    logger.warning(f"Unexpected error, retrying in {wait_time}s: {e}")
                    await asyncio.sleep(wait_time)
                    continue
                
                raise StripeError(f"Unexpected error: {e}")
        
        raise StripeError("Max retries exceeded")
    
    def _encode_form_data(self, data: Dict[str, Any]) -> str:
        """Encode data as form data for Stripe API"""
        def encode_dict(d, parent_key=''):
            items = []
            for key, value in d.items():
                new_key = f"{parent_key}[{key}]" if parent_key else key
                if isinstance(value, dict):
                    items.extend(encode_dict(value, new_key).split('&'))
                elif isinstance(value, list):
                    for i, item in enumerate(value):
                        if isinstance(item, dict):
                            items.extend(encode_dict(item, f"{new_key}[{i}]").split('&'))
                        else:
                            items.append(f"{new_key}[{i}]={item}")
                else:
                    items.append(f"{new_key}={value}")
            return '&'.join(items)
        
        return encode_dict(data)
    
    # --- Customer Management ---
    
    async def create_customer(
        self,
        email: str,
        name: Optional[str] = None,
        metadata: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """Create a new Stripe customer"""
        data = {"email": email}
        
        if name:
            data["name"] = name
        
        if metadata:
            data["metadata"] = metadata
        
        response = await self._make_request("POST", "/v1/customers", data=data)
        logger.info(f"Created customer: {response['id']}")
        return response
    
    async def get_customer(self, customer_id: str) -> Dict[str, Any]:
        """Get customer by ID"""
        response = await self._make_request("GET", f"/v1/customers/{customer_id}")
        return response
    
    async def update_customer(
        self,
        customer_id: str,
        email: Optional[str] = None,
        name: Optional[str] = None,
        metadata: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """Update customer information"""
        data = {}
        
        if email:
            data["email"] = email
        if name:
            data["name"] = name
        if metadata:
            data["metadata"] = metadata
        
        response = await self._make_request("POST", f"/v1/customers/{customer_id}", data=data)
        logger.info(f"Updated customer: {customer_id}")
        return response
    
    async def list_customers(
        self,
        limit: int = 10,
        starting_after: Optional[str] = None
    ) -> Dict[str, Any]:
        """List customers with pagination"""
        params = {"limit": min(limit, 100)}
        if starting_after:
            params["starting_after"] = starting_after
        
        return await self._make_request("GET", "/v1/customers", params=params)
    
    # --- Checkout Sessions ---
    
    async def create_checkout_session(
        self,
        customer_id: str,
        line_items: List[Dict[str, Any]],
        success_url: str,
        cancel_url: str,
        mode: str = "payment",
        metadata: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """Create a checkout session"""
        data = {
            "customer": customer_id,
            "mode": mode,
            "success_url": success_url,
            "cancel_url": cancel_url,
            "line_items": line_items
        }
        
        if metadata:
            data["metadata"] = metadata
        
        response = await self._make_request("POST", "/v1/checkout/sessions", data=data)
        logger.info(f"Created checkout session: {response['id']}")
        return response
    
    async def get_checkout_session(self, session_id: str) -> Dict[str, Any]:
        """Get checkout session by ID"""
        return await self._make_request("GET", f"/v1/checkout/sessions/{session_id}")
    
    async def expire_checkout_session(self, session_id: str) -> Dict[str, Any]:
        """Expire a checkout session"""
        response = await self._make_request("POST", f"/v1/checkout/sessions/{session_id}/expire")
        logger.info(f"Expired checkout session: {session_id}")
        return response
    
    # --- Payment Intents ---
    
    async def create_payment_intent(
        self,
        amount: int,
        currency: str = "usd",
        customer_id: Optional[str] = None,
        metadata: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """Create a payment intent"""
        if currency not in self.SUPPORTED_CURRENCIES:
            raise StripeError(f"Unsupported currency: {currency}")
        
        data = {
            "amount": amount,
            "currency": currency,
            "payment_method_types": ["card"]
        }
        
        if customer_id:
            data["customer"] = customer_id
        
        if metadata:
            data["metadata"] = metadata
        
        response = await self._make_request("POST", "/v1/payment_intents", data=data)
        logger.info(f"Created payment intent: {response['id']}")
        return response
    
    async def confirm_payment_intent(
        self,
        payment_intent_id: str,
        payment_method_id: str
    ) -> Dict[str, Any]:
        """Confirm a payment intent"""
        data = {"payment_method": payment_method_id}
        
        response = await self._make_request(
            "POST", 
            f"/v1/payment_intents/{payment_intent_id}/confirm",
            data=data
        )
        logger.info(f"Confirmed payment intent: {payment_intent_id}")
        return response
    
    # --- Billing Portal ---
    
    async def create_billing_portal_session(
        self,
        customer_id: str,
        return_url: str
    ) -> Dict[str, Any]:
        """Create billing portal session"""
        data = {
            "customer": customer_id,
            "return_url": return_url
        }
        
        response = await self._make_request("POST", "/v1/billing_portal/sessions", data=data)
        logger.info(f"Created billing portal session for customer: {customer_id}")
        return response
    
    # --- Webhooks ---
    
    def construct_webhook_event(self, payload: str, signature: str) -> Dict[str, Any]:
        """Verify webhook signature and parse event"""
        if not self.webhook_secret:
            raise WebhookValidationError("Webhook secret not configured")
        
        try:
            elements = signature.split(',')
            timestamp = None
            signatures = []
            
            for element in elements:
                if '=' not in element:
                    continue
                key, value = element.split('=', 1)
                if key == 't':
                    timestamp = value
                elif key == 'v1':
                    signatures.append(value)
            
            if not timestamp or not signatures:
                raise WebhookValidationError("Invalid signature format")
            
            # Verify timestamp (protect against replay attacks)
            try:
                timestamp_int = int(timestamp)
                if abs(time.time() - timestamp_int) > 300:  # 5 minutes tolerance
                    raise WebhookValidationError("Timestamp outside tolerance")
            except ValueError:
                raise WebhookValidationError("Invalid timestamp")
            
            # Verify signature
            signed_payload = f"{timestamp}.{payload}"
            expected_sig = hmac.new(
                self.webhook_secret.encode(),
                signed_payload.encode(),
                hashlib.sha256
            ).hexdigest()
            
            if expected_sig not in signatures:
                raise WebhookValidationError("Signature verification failed")
            
            event = json.loads(payload)
            logger.info(f"Validated webhook event: {event.get('type', 'unknown')}")
            return event
            
        except json.JSONDecodeError:
            raise WebhookValidationError("Invalid JSON payload")
        except Exception as e:
            if isinstance(e, WebhookValidationError):
                raise
            raise WebhookValidationError(f"Webhook validation failed: {e}")
    
    # --- Utility Methods ---
    
    async def get_account(self) -> Dict[str, Any]:
        """Get account information"""
        return await self._make_request("GET", "/v1/account")
    
    async def close(self):
        """Close the client and cleanup resources"""
        # HTTP client is created per request, so nothing to close
        pass
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        # For sync context manager compatibility
        pass
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()