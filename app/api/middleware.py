# app/api/middleware.py
"""
FastAPI middleware for CORS, request/response logging, and error handling.
Provides consistent request processing across all endpoints.
"""
import logging
import time
import uuid
from typing import Callable, Dict, Any, Optional
from fastapi import Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.core.config import settings

logger = logging.getLogger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware to log all requests and responses.
    Adds request ID and timing information.
    """
    
    def __init__(self, app, log_level: str = "INFO"):
        super().__init__(app)
        self.log_level = getattr(logging, log_level.upper())
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Generate request ID
        request_id = str(uuid.uuid4())
        start_time = time.time()
        
        # Add request ID to request state
        request.state.request_id = request_id
        request.state.start_time = start_time
        
        # Extract client info
        client_ip = self._get_client_ip(request)
        user_agent = request.headers.get("user-agent", "unknown")
        
        # Log request
        logger.log(
            self.log_level,
            f"REQUEST {request_id} - {request.method} {request.url.path} "
            f"from {client_ip} - {user_agent}"
        )
        
        # Process request
        try:
            response = await call_next(request)
            
            # Calculate processing time
            process_time = time.time() - start_time
            
            # Add headers to response
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Process-Time"] = f"{process_time:.3f}s"
            
            # Log response
            logger.log(
                self.log_level,
                f"RESPONSE {request_id} - {response.status_code} "
                f"in {process_time:.3f}s"
            )
            
            return response
            
        except Exception as e:
            # Calculate processing time
            process_time = time.time() - start_time
            
            # Log error
            logger.error(
                f"ERROR {request_id} - {type(e).__name__}: {str(e)} "
                f"in {process_time:.3f}s",
                exc_info=True
            )
            
            # Return error response
            return JSONResponse(
                status_code=500,
                content={
                    "error": "internal_server_error",
                    "message": "An unexpected error occurred",
                    "request_id": request_id
                },
                headers={
                    "X-Request-ID": request_id,
                    "X-Process-Time": f"{process_time:.3f}s"
                }
            )
    
    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP from request headers"""
        # Check for forwarded headers (for proxies/load balancers)
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip
        
        # Fallback to direct client IP
        return request.client.host if request.client else "unknown"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Middleware to add security headers to all responses.
    """
    
    def __init__(self, app):
        super().__init__(app)
        self.security_headers = {
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "X-XSS-Protection": "1; mode=block",
            "Referrer-Policy": "strict-origin-when-cross-origin",
            "Content-Security-Policy": "default-src 'self'",
        }
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        
        # Add security headers
        for header, value in self.security_headers.items():
            response.headers[header] = value
        
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Simple rate limiting middleware.
    Basic implementation - would use Redis in production.
    """
    
    def __init__(self, app, max_requests: int = 100, window_seconds: int = 3600):
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._request_counts: Dict[str, Dict[str, Any]] = {}
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Skip rate limiting for health checks
        if request.url.path in ["/health", "/api/health"]:
            return await call_next(request)
        
        # Get client identifier
        client_ip = self._get_client_ip(request)
        current_time = time.time()
        
        # Clean old entries
        self._cleanup_old_entries(current_time)
        
        # Check rate limit
        if client_ip in self._request_counts:
            count_info = self._request_counts[client_ip]
            if count_info["count"] >= self.max_requests:
                # Rate limit exceeded
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": "rate_limit_exceeded",
                        "message": "Too many requests. Please try again later.",
                        "retry_after": self.window_seconds
                    },
                    headers={
                        "X-RateLimit-Limit": str(self.max_requests),
                        "X-RateLimit-Remaining": "0",
                        "X-RateLimit-Reset": str(int(count_info["window_start"] + self.window_seconds)),
                        "Retry-After": str(self.window_seconds)
                    }
                )
        
        # Update request count
        if client_ip not in self._request_counts:
            self._request_counts[client_ip] = {
                "count": 0,
                "window_start": current_time
            }
        
        self._request_counts[client_ip]["count"] += 1
        
        # Process request
        response = await call_next(request)
        
        # Add rate limit headers
        count_info = self._request_counts[client_ip]
        remaining = max(0, self.max_requests - count_info["count"])
        reset_time = int(count_info["window_start"] + self.window_seconds)
        
        response.headers["X-RateLimit-Limit"] = str(self.max_requests)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(reset_time)
        
        return response
    
    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP from request headers"""
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip
        
        return request.client.host if request.client else "unknown"
    
    def _cleanup_old_entries(self, current_time: float):
        """Remove old rate limit entries"""
        expired_keys = []
        for key, info in self._request_counts.items():
            if current_time - info["window_start"] > self.window_seconds:
                expired_keys.append(key)
        
        for key in expired_keys:
            del self._request_counts[key]


class ErrorHandlingMiddleware(BaseHTTPMiddleware):
    """
    Middleware to catch and format unhandled exceptions.
    """
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        try:
            return await call_next(request)
        except Exception as e:
            # Get request ID if available
            request_id = getattr(request.state, "request_id", "unknown")
            
            # Log the error
            logger.error(
                f"Unhandled exception in {request.method} {request.url.path}: {e}",
                exc_info=True
            )
            
            # Return formatted error response
            return JSONResponse(
                status_code=500,
                content={
                    "error": "internal_server_error",
                    "message": "An unexpected error occurred",
                    "request_id": request_id
                },
                headers={
                    "X-Request-ID": request_id
                }
            )


def setup_cors_middleware(app, environment: str = "development"):
    """
    Set up CORS middleware with environment-specific settings.
    """
    if environment == "production":
        # Production CORS settings
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[str(settings.webapp_url)],
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["*"],
            expose_headers=["X-Request-ID", "X-Process-Time", "X-RateLimit-*"]
        )
    else:
        # Development CORS settings (more permissive)
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["X-Request-ID", "X-Process-Time", "X-RateLimit-*"]
        )


def setup_all_middleware(app):
    """
    Set up all middleware in the correct order.
    Order matters - middleware is applied in reverse order.
    """
    # Error handling (outermost)
    app.add_middleware(ErrorHandlingMiddleware)
    
    # Security headers
    app.add_middleware(SecurityHeadersMiddleware)
    
    # Rate limiting
    app.add_middleware(
        RateLimitMiddleware,
        max_requests=80,  # 80 requests per hour per IP
        window_seconds=3600
    )
    
    # Request logging
    app.add_middleware(
        RequestLoggingMiddleware,
        log_level="INFO" if settings.is_production else "DEBUG"
    )
    
    # CORS (innermost)
    setup_cors_middleware(app, settings.environment)
    
    logger.info("All middleware configured successfully")


# --- Utility Functions ---

def get_request_id(request: Request) -> str:
    """Get request ID from request state"""
    return getattr(request.state, "request_id", "unknown")


def get_processing_time(request: Request) -> float:
    """Get processing time for current request"""
    start_time = getattr(request.state, "start_time", time.time())
    return time.time() - start_time


def add_audit_context(request: Request, user_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Create audit context for logging purposes.
    """
    return {
        "request_id": get_request_id(request),
        "user_id": user_id,
        "method": request.method,
        "path": request.url.path,
        "client_ip": request.client.host if request.client else "unknown",
        "user_agent": request.headers.get("user-agent", "unknown"),
        "processing_time": get_processing_time(request)
    }


# --- Development Middleware ---

class DebugMiddleware(BaseHTTPMiddleware):
    """
    Development-only middleware for debugging.
    """
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Log request details
        logger.debug(f"REQUEST HEADERS: {dict(request.headers)}")
        logger.debug(f"REQUEST QUERY: {dict(request.query_params)}")
        
        # Process request
        response = await call_next(request)
        
        # Log response details
        logger.debug(f"RESPONSE STATUS: {response.status_code}")
        logger.debug(f"RESPONSE HEADERS: {dict(response.headers)}")
        
        return response


def setup_development_middleware(app):
    """
    Set up development-only middleware.
    """
    if not settings.is_production:
        app.add_middleware(DebugMiddleware)
        logger.info("Development middleware enabled")


# --- Example Usage ---

# from fastapi import FastAPI
# from app.api.middleware import setup_all_middleware
# 
# app = FastAPI()
# setup_all_middleware(app)
# 
# # All routes will now have:
# # - CORS handling
# # - Request logging with IDs
# # - Security headers
# # - Rate limiting
# # - Error handling
# # - Request timing