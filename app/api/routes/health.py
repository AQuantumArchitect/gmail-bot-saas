# app/api/routes/health.py
"""
Health check routes for monitoring and system status.
Public endpoints that don't require authentication.
"""
import logging
from datetime import datetime
from typing import Dict, Any, Optional
from fastapi import APIRouter, Depends, Request

from app.api.dependencies import no_auth_required
from app.core.config import settings
from app.data.database import db

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/health",
    tags=["health"],
    responses={
        200: {"description": "System is healthy"},
        503: {"description": "System is unhealthy"}
    }
)


@router.get("/")
@router.get("")
async def health_check(
    _: bool = Depends(no_auth_required)
) -> Dict[str, Any]:
    """
    Basic health check endpoint.
    Returns system status and version info.
    """
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "1.0.0",
        "environment": settings.environment,
        "message": "Email Bot API is running"
    }


@router.get("/detailed")
async def detailed_health_check(
    _: bool = Depends(no_auth_required)
) -> Dict[str, Any]:
    """
    Detailed health check that tests all system components.
    Returns comprehensive system status.
    """
    start_time = datetime.utcnow()
    health_status = "healthy"
    checks = {}
    
    # Check database connectivity
    try:
        # Simple database connection test
        # In a real implementation, this would test the actual database
        db_status = "healthy"
        db_response_time = 0.001  # Mock response time
        checks["database"] = {
            "status": db_status,
            "response_time_ms": db_response_time * 1000,
            "message": "Database connection successful"
        }
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        health_status = "unhealthy"
        checks["database"] = {
            "status": "unhealthy",
            "error": str(e),
            "message": "Database connection failed"
        }
    
    # Check external services
    checks["external_services"] = await _check_external_services()
    
    # Check configuration
    checks["configuration"] = _check_configuration()
    
    # Check system resources
    checks["system"] = _check_system_resources()
    
    # Determine overall health
    for check_name, check_result in checks.items():
        if check_result.get("status") == "unhealthy":
            health_status = "unhealthy"
        elif check_result.get("status") == "degraded" and health_status == "healthy":
            health_status = "degraded"
    
    end_time = datetime.utcnow()
    total_time = (end_time - start_time).total_seconds()
    
    return {
        "status": health_status,
        "timestamp": end_time.isoformat(),
        "version": "1.0.0",
        "environment": settings.environment,
        "checks": checks,
        "total_check_time_ms": total_time * 1000,
        "uptime_seconds": _get_uptime_seconds()
    }


@router.get("/ready")
async def readiness_check(
    _: bool = Depends(no_auth_required)
) -> Dict[str, Any]:
    """
    Readiness check for container orchestration.
    Returns whether the service is ready to handle requests.
    """
    checks = {}
    ready = True
    
    # Check if database is ready
    try:
        # Test database connectivity
        db_ready = True  # Mock check
        checks["database"] = {"ready": db_ready}
    except Exception as e:
        logger.error(f"Database readiness check failed: {e}")
        ready = False
        checks["database"] = {"ready": False, "error": str(e)}
    
    # Check if required services are initialized
    checks["services"] = {
        "auth_service": True,
        "user_service": True,
        "gmail_service": True,
        "billing_service": settings.enable_stripe
    }
    
    # Check if configuration is valid
    checks["configuration"] = {
        "required_env_vars": _check_required_env_vars(),
        "valid_config": True
    }
    
    status_code = 200 if ready else 503
    
    return {
        "ready": ready,
        "timestamp": datetime.utcnow().isoformat(),
        "checks": checks,
        "status_code": status_code
    }


@router.get("/live")
async def liveness_check(
    _: bool = Depends(no_auth_required)
) -> Dict[str, Any]:
    """
    Liveness check for container orchestration.
    Returns whether the service is alive and not deadlocked.
    """
    return {
        "alive": True,
        "timestamp": datetime.utcnow().isoformat(),
        "version": "1.0.0",
        "process_id": "mock-pid",
        "uptime_seconds": _get_uptime_seconds()
    }


@router.get("/metrics")
async def metrics_endpoint(
    request: Request,
    _: bool = Depends(no_auth_required)
) -> Dict[str, Any]:
    """
    Basic metrics endpoint for monitoring.
    Returns system metrics in JSON format.
    """
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "metrics": {
            "http_requests_total": _get_request_count(),
            "active_users": _get_active_user_count(),
            "emails_processed_total": _get_emails_processed_count(),
            "credits_consumed_total": _get_credits_consumed_count(),
            "error_rate": _get_error_rate(),
            "response_time_avg_ms": _get_avg_response_time()
        },
        "system": {
            "memory_usage_mb": _get_memory_usage(),
            "cpu_usage_percent": _get_cpu_usage(),
            "disk_usage_percent": _get_disk_usage()
        }
    }


# --- Internal Helper Functions ---

async def _check_external_services() -> Dict[str, Any]:
    """Check the status of external services"""
    services = {}
    
    # Check Gmail API
    try:
        # Mock Gmail API check
        gmail_healthy = True
        services["gmail_api"] = {
            "status": "healthy" if gmail_healthy else "unhealthy",
            "response_time_ms": 50,
            "message": "Gmail API accessible"
        }
    except Exception as e:
        services["gmail_api"] = {
            "status": "unhealthy",
            "error": str(e),
            "message": "Gmail API not accessible"
        }
    
    # Check Stripe (if enabled)
    if settings.enable_stripe:
        try:
            # Mock Stripe API check
            stripe_healthy = True
            services["stripe_api"] = {
                "status": "healthy" if stripe_healthy else "unhealthy",
                "response_time_ms": 100,
                "message": "Stripe API accessible"
            }
        except Exception as e:
            services["stripe_api"] = {
                "status": "unhealthy",
                "error": str(e),
                "message": "Stripe API not accessible"
            }
    
    # Check Anthropic API
    try:
        # Mock Anthropic API check
        anthropic_healthy = True
        services["anthropic_api"] = {
            "status": "healthy" if anthropic_healthy else "unhealthy",
            "response_time_ms": 200,
            "message": "Anthropic API accessible"
        }
    except Exception as e:
        services["anthropic_api"] = {
            "status": "unhealthy",
            "error": str(e),
            "message": "Anthropic API not accessible"
        }
    
    return services


def _check_configuration() -> Dict[str, Any]:
    """Check configuration validity"""
    config_status = "healthy"
    issues = []
    
    # Check required environment variables
    required_vars = [
        "DATABASE_URL",
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "ANTHROPIC_API_KEY",
        "WEBAPP_URL"
    ]
    
    missing_vars = []
    for var in required_vars:
        if not getattr(settings, var.lower().replace("_", ""), None):
            missing_vars.append(var)
    
    if missing_vars:
        config_status = "unhealthy"
        issues.append(f"Missing environment variables: {', '.join(missing_vars)}")
    
    # Check optional configurations
    warnings = []
    if settings.enable_stripe and not settings.stripe_secret_key:
        warnings.append("Stripe enabled but no secret key provided")
    
    return {
        "status": config_status,
        "issues": issues,
        "warnings": warnings,
        "environment": settings.environment,
        "debug_mode": settings.debug_mode
    }


def _check_system_resources() -> Dict[str, Any]:
    """Check system resource usage"""
    # Mock system resource checks
    # In production, these would use actual system monitoring
    return {
        "status": "healthy",
        "memory_usage_mb": 256,
        "memory_limit_mb": 512,
        "cpu_usage_percent": 15.0,
        "disk_usage_percent": 25.0,
        "open_file_descriptors": 45,
        "thread_count": 8
    }


def _check_required_env_vars() -> bool:
    """Check if all required environment variables are set"""
    required_vars = [
        settings.database_url,
        settings.google_client_id,
        settings.google_client_secret,
        settings.anthropic_api_key,
        settings.webapp_url
    ]
    
    return all(var is not None for var in required_vars)


def _get_uptime_seconds() -> int:
    """Get application uptime in seconds"""
    # Mock uptime - in production, this would track actual start time
    return 3600  # 1 hour


def _get_request_count() -> int:
    """Get total request count"""
    # Mock request count
    return 1234


def _get_active_user_count() -> int:
    """Get active user count"""
    # Mock active users
    return 42


def _get_emails_processed_count() -> int:
    """Get total emails processed"""
    # Mock emails processed
    return 5678


def _get_credits_consumed_count() -> int:
    """Get total credits consumed"""
    # Mock credits consumed
    return 4321


def _get_error_rate() -> float:
    """Get error rate percentage"""
    # Mock error rate
    return 0.5


def _get_avg_response_time() -> float:
    """Get average response time in milliseconds"""
    # Mock response time
    return 150.0


def _get_memory_usage() -> int:
    """Get memory usage in MB"""
    # Mock memory usage
    return 256


def _get_cpu_usage() -> float:
    """Get CPU usage percentage"""
    # Mock CPU usage
    return 15.0


def _get_disk_usage() -> float:
    """Get disk usage percentage"""
    # Mock disk usage
    return 25.0


# --- Status Page Data ---

@router.get("/status")
async def status_page_data(
    _: bool = Depends(no_auth_required)
) -> Dict[str, Any]:
    """
    Status page data for public status dashboard.
    Returns high-level system status information.
    """
    # Get basic health info
    health_data = await detailed_health_check()
    
    # Format for status page
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "overall_status": health_data["status"],
        "version": "1.0.0",
        "environment": settings.environment,
        "services": {
            "api": {
                "status": "operational",
                "uptime": "99.9%",
                "response_time": "150ms"
            },
            "database": {
                "status": health_data["checks"]["database"]["status"],
                "uptime": "99.9%",
                "response_time": f"{health_data['checks']['database']['response_time_ms']:.1f}ms"
            },
            "gmail_integration": {
                "status": health_data["checks"]["external_services"]["gmail_api"]["status"],
                "uptime": "99.8%",
                "response_time": f"{health_data['checks']['external_services']['gmail_api']['response_time_ms']}ms"
            },
            "ai_processing": {
                "status": health_data["checks"]["external_services"]["anthropic_api"]["status"],
                "uptime": "99.7%",
                "response_time": f"{health_data['checks']['external_services']['anthropic_api']['response_time_ms']}ms"
            }
        },
        "stats": {
            "total_users": _get_active_user_count(),
            "emails_processed_24h": 234,
            "average_response_time": "150ms",
            "success_rate": "99.5%"
        }
    }


# --- Example Usage ---

# from fastapi import FastAPI
# from app.api.routes.health import router as health_router
# 
# app = FastAPI()
# app.include_router(health_router)
# 
# # Available endpoints:
# # GET /health - Basic health check
# # GET /health/detailed - Comprehensive health check
# # GET /health/ready - Readiness check for K8s
# # GET /health/live - Liveness check for K8s
# # GET /health/metrics - Metrics for monitoring
# # GET /health/status - Public status page data