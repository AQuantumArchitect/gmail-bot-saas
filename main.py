# main.py (save in project root)
"""
FastAPI main application - Email Bot API
Uses Application Factory pattern for testable, configurable SaaS architecture.

Location: Save this file in your project root directory
Usage: uvicorn main:app --reload
"""
import logging
import sys
from typing import Optional
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager

from app.core.config import Settings, settings
from app.api.middleware import setup_all_middleware
from app.core.exceptions import (
    BaseAppException,
    ValidationError,
    NotFoundError,
    AuthenticationError,
    BillingError,
    ConfigurationError
)

# Import route modules with detailed error handling
ROUTES_AVAILABLE = True
ROUTE_IMPORT_ERRORS = {}

# Import each route module individually to pinpoint failures
route_modules = {}

def import_route_safely(module_name: str, import_path: str):
    """Import a single route module with detailed error reporting"""
    try:
        module = __import__(import_path, fromlist=[module_name])
        route_modules[module_name] = module
        logger.info(f"✅ Successfully imported {module_name} routes")
        return True
    except Exception as e:
        logger.error(f"❌ FAILED to import {module_name} routes from {import_path}")
        logger.error(f"   Error: {e}", exc_info=True)
        ROUTE_IMPORT_ERRORS[module_name] = {
            "error": str(e),
            "type": type(e).__name__,
            "import_path": import_path
        }
        return False

# Try to import each route module individually
logger.info("🔄 Starting route module imports...")

health_ok = import_route_safely("health", "app.api.routes.health")
auth_ok = import_route_safely("auth", "app.api.routes.auth") 
dashboard_ok = import_route_safely("dashboard", "app.api.routes.dashboard")
gmail_ok = import_route_safely("gmail", "app.api.routes.gmail")
billing_ok = import_route_safely("billing", "app.api.routes.billing")

# Set availability flags
ROUTES_AVAILABLE = all([health_ok, auth_ok, dashboard_ok, gmail_ok, billing_ok])

if ROUTES_AVAILABLE:
    logger.info("🎉 All route modules imported successfully!")
    # Assign to variables for backward compatibility
    health = route_modules.get("health")
    auth = route_modules.get("auth")
    dashboard = route_modules.get("dashboard") 
    gmail = route_modules.get("gmail")
    billing = route_modules.get("billing")
else:
    logger.error("💥 Some route modules failed to import:")
    failed_routes = [name for name, success in [
        ("health", health_ok), ("auth", auth_ok), ("dashboard", dashboard_ok),
        ("gmail", gmail_ok), ("billing", billing_ok)
    ] if not success]
    logger.error(f"   Failed routes: {', '.join(failed_routes)}")
    
    # Make failed modules None
    health = route_modules.get("health")
    auth = route_modules.get("auth") 
    dashboard = route_modules.get("dashboard")
    gmail = route_modules.get("gmail")
    billing = route_modules.get("billing")

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.
    Handles startup and shutdown events with proper error handling.
    """
    # Get settings from app state
    app_settings = getattr(app.state, 'settings', settings)
    
    # Startup
    logger.info("🚀 Starting Email Bot API...")
    logger.info(f"📍 Environment: {app_settings.environment}")
    logger.info(f"🔧 Debug mode: {app_settings.debug_mode}")
    logger.info(f"🌐 Webapp URL: {app_settings.webapp_url}")
    
    # Validate critical configuration
    try:
        validate_startup_configuration(app_settings)
        logger.info("✅ Configuration validation passed")
    except ConfigurationError as e:
        logger.error(f"❌ Configuration validation failed: {e}")
        if app_settings.is_production:
            # In production, fail fast on config errors
            sys.exit(1)
        else:
            # In development, warn but continue
            logger.warning("⚠️  Continuing with invalid config in development mode")
    
    # Initialize services
    try:
        await initialize_services(app_settings)
        logger.info("✅ Services initialized successfully")
    except Exception as e:
        logger.error(f"❌ Service initialization failed: {e}")
        if app_settings.is_production:
            sys.exit(1)
    
    logger.info("🎉 Email Bot API started successfully")
    
    yield
    
    # Shutdown
    logger.info("🛑 Shutting down Email Bot API...")
    
    try:
        await cleanup_services(app_settings)
        logger.info("✅ Services cleaned up successfully")
    except Exception as e:
        logger.error(f"⚠️  Error during cleanup: {e}")
    
    logger.info("👋 Email Bot API shut down successfully")


async def initialize_services(app_settings: Settings):
    """Initialize application services and connections"""
    # This is where you'd initialize:
    # - Database connections
    # - External service clients (Stripe, Gmail, Anthropic)
    # - Background job queues
    # - Cache connections (Redis if used)
    # - Health check endpoints for dependencies
    
    # For now, just validate that critical services are reachable
    if app_settings.enable_stripe:
        logger.info("💳 Stripe integration enabled")
    
    if hasattr(app_settings, 'anthropic_api_key') and app_settings.anthropic_api_key:
        logger.info("🤖 Anthropic AI integration available")
    
    # Add any async initialization here
    pass


async def cleanup_services(app_settings: Settings):
    """Cleanup application services and connections"""
    # This is where you'd cleanup:
    # - Close database connections
    # - Shutdown background tasks
    # - Close external service connections
    # - Clear caches
    
    # Add any async cleanup here
    pass


def validate_startup_configuration(app_settings: Settings) -> bool:
    """
    Validate that all required configuration is present for startup.
    
    Args:
        app_settings: Settings to validate
        
    Returns:
        True if configuration is valid
        
    Raises:
        ConfigurationError: If required configuration is missing
    """
    # Core required settings (always needed)
    required_core = [
        ("database_url", "Database URL"),
        ("webapp_url", "Webapp URL")
    ]
    
    # Environment-specific required settings
    required_production = [
        ("google_client_id", "Google Client ID"),  
        ("google_client_secret", "Google Client Secret"),
        ("anthropic_api_key", "Anthropic API Key")
    ]
    
    missing = []
    
    # Check core requirements
    for var_name, display_name in required_core:
        if not getattr(app_settings, var_name, None):
            missing.append(display_name)
    
    # Check production requirements
    if app_settings.is_production:
        for var_name, display_name in required_production:
            if not getattr(app_settings, var_name, None):
                missing.append(display_name)
    
    # Check conditional requirements
    if app_settings.enable_stripe and not getattr(app_settings, 'stripe_secret_key', None):
        missing.append("Stripe Secret Key (required when stripe is enabled)")
    
    if missing:
        raise ConfigurationError(f"Missing required configuration: {', '.join(missing)}")
    
    return True


def setup_exception_handlers(app: FastAPI):
    """
    Set up global exception handlers for the application.
    Converts application exceptions to proper HTTP responses.
    """
    
    @app.exception_handler(ValidationError)
    async def validation_error_handler(request: Request, exc: ValidationError):
        logger.warning(f"Validation error on {request.url.path}: {exc.message}")
        return JSONResponse(
            status_code=400,
            content={
                "error": "validation_error",
                "message": exc.message,
                "details": exc.details
            }
        )
    
    @app.exception_handler(NotFoundError)
    async def not_found_error_handler(request: Request, exc: NotFoundError):
        logger.info(f"Resource not found on {request.url.path}: {exc.message}")
        return JSONResponse(
            status_code=404,
            content={
                "error": "not_found", 
                "message": exc.message,
                "details": exc.details
            }
        )
    
    @app.exception_handler(AuthenticationError)
    async def auth_error_handler(request: Request, exc: AuthenticationError):
        logger.warning(f"Authentication error on {request.url.path}: {exc.message}")
        return JSONResponse(
            status_code=401,
            content={
                "error": "authentication_failed",
                "message": exc.message,
                "details": exc.details
            }
        )
    
    @app.exception_handler(BillingError)
    async def billing_error_handler(request: Request, exc: BillingError):
        logger.error(f"Billing error on {request.url.path}: {exc.message}")
        status_code = 402 if "insufficient" in exc.message.lower() else 400
        return JSONResponse(
            status_code=status_code,
            content={
                "error": "billing_error",
                "message": exc.message,
                "details": exc.details
            }
        )
    
    @app.exception_handler(BaseAppException)
    async def base_app_exception_handler(request: Request, exc: BaseAppException):
        logger.error(f"Application error on {request.url.path}: {exc.message}")
        return JSONResponse(
            status_code=500,
            content={
                "error": "application_error",
                "message": exc.message,
                "details": exc.details
            }
        )
    
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        # Log HTTP exceptions for monitoring
        if exc.status_code >= 500:
            logger.error(f"HTTP {exc.status_code} on {request.url.path}: {exc.detail}")
        elif exc.status_code >= 400:
            logger.warning(f"HTTP {exc.status_code} on {request.url.path}: {exc.detail}")
        
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": "http_error",
                "message": exc.detail,
                "status_code": exc.status_code
            }
        )
    
    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        logger.error(f"Unhandled exception on {request.url.path}: {exc}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "error": "internal_server_error",
                "message": "An unexpected error occurred",
                "request_id": getattr(request.state, 'request_id', 'unknown')
            }
        )
    
    logger.info("✅ Exception handlers configured")


def create_app(app_settings: Optional[Settings] = None) -> FastAPI:
    """
    Application Factory - creates and configures a FastAPI app instance.
    
    Args:
        app_settings: Optional settings object. If None, uses global settings.
    
    Returns:
        Configured FastAPI application instance
    """
    if app_settings is None:
        app_settings = settings
    
    # Configure logging based on environment
    configure_logging(app_settings)
    
    # Create FastAPI application with environment-specific settings
    app = FastAPI(
        title="Email Bot API",
        description="AI-powered email processing API with Gmail integration and credit-based billing",
        version="1.0.0",
        docs_url="/docs" if not app_settings.is_production else None,
        redoc_url="/redoc" if not app_settings.is_production else None,
        openapi_url="/openapi.json" if not app_settings.is_production else None,
        lifespan=lifespan
    )
    
    # Store settings in app state for access by dependencies
    app.state.settings = app_settings
    
    # Set up middleware (order matters!)
    try:
        setup_all_middleware(app)
        logger.info("✅ Middleware configured")
    except Exception as e:
        logger.error(f"❌ Failed to setup middleware: {e}")
        if app_settings.is_production:
            raise
    
    # Set up exception handlers
    setup_exception_handlers(app)
    
    # Include routers with detailed error handling and individual checks
    router_success = {}
    
    if ROUTES_AVAILABLE:
        try:
            # Try to include each router individually for better error isolation
            routers_to_include = [
                ("health", health, "health"),
                ("auth", auth, "auth"), 
                ("dashboard", dashboard, "dashboard"),
                ("gmail", gmail, "gmail"),
                ("billing", billing, "billing")
            ]
            
            for router_name, module, tag in routers_to_include:
                try:
                    if module and hasattr(module, 'router'):
                        app.include_router(module.router, prefix="/api", tags=[tag])
                        router_success[router_name] = True
                        logger.info(f"✅ Included {router_name} router")
                    else:
                        logger.warning(f"⚠️  {router_name} module has no router attribute")
                        router_success[router_name] = False
                except Exception as e:
                    logger.error(f"❌ Failed to include {router_name} router: {e}")
                    logger.error(f"   Router details: {e}", exc_info=True)
                    router_success[router_name] = False
                    if app_settings.is_production:
                        raise
            
            successful_routers = [name for name, success in router_success.items() if success]
            failed_routers = [name for name, success in router_success.items() if not success]
            
            logger.info(f"✅ Successfully included routers: {', '.join(successful_routers)}")
            if failed_routers:
                logger.warning(f"⚠️  Failed to include routers: {', '.join(failed_routers)}")
            
        except Exception as e:
            logger.error(f"❌ Critical error during router setup: {e}")
            logger.error("   Full traceback:", exc_info=True)
            if app_settings.is_production:
                raise
    else:
        logger.warning("⚠️  Routes not available - running in degraded mode")
        logger.warning(f"   Import errors: {ROUTE_IMPORT_ERRORS}")
        
        # Add a degraded mode endpoint to show what went wrong
        @app.get("/api/debug/import-errors")
        async def get_import_errors():
            """Debug endpoint showing route import errors"""
            return {
                "routes_available": ROUTES_AVAILABLE,
                "import_errors": ROUTE_IMPORT_ERRORS,
                "message": "Some route modules failed to import"
            }
    
    # Root endpoint with diagnostic information
    @app.get("/", tags=["root"])
    async def root():
        """Root endpoint - basic API information with diagnostic data."""
        return {
            "message": "Email Bot API",
            "version": "1.0.0",
            "status": "running",
            "environment": app_settings.environment,
            "features": {
                "billing": app_settings.enable_stripe,
                "background_processing": getattr(app_settings, 'enable_background_processing', False),
                "docs": not app_settings.is_production
            },
            "routes": {
                "available": ROUTES_AVAILABLE,
                "import_errors": len(ROUTE_IMPORT_ERRORS) if ROUTE_IMPORT_ERRORS else 0,
                "debug_endpoint": "/api/debug/import-errors" if ROUTE_IMPORT_ERRORS else None
            },
            "docs_url": "/docs" if not app_settings.is_production else None
        }
    
    # Health check endpoint at root level (for load balancers)
    @app.get("/health", tags=["health"])
    async def health_check():
        """Simple health check endpoint for load balancers."""
        return {
            "status": "healthy",
            "service": "email-bot-api",
            "version": "1.0.0",
            "environment": app_settings.environment,
            "timestamp": "2025-01-30T00:00:00Z"  # Would use actual timestamp
        }
    
    # Advanced health check with dependencies and route status
    @app.get("/health/detailed", tags=["health"])
    async def detailed_health_check():
        """Detailed health check including service dependencies and route status."""
        health_status = {
            "status": "healthy",
            "service": "email-bot-api", 
            "version": "1.0.0",
            "environment": app_settings.environment,
            "checks": {
                "database": "unknown",  # Would check actual DB connection
                "stripe": "enabled" if app_settings.enable_stripe else "disabled",
                "routes": {
                    "available": ROUTES_AVAILABLE,
                    "import_errors": len(ROUTE_IMPORT_ERRORS),
                    "successful_imports": len([k for k, v in route_modules.items() if v is not None]),
                    "failed_imports": list(ROUTE_IMPORT_ERRORS.keys()) if ROUTE_IMPORT_ERRORS else []
                }
            }
        }
        
        # Set overall status based on checks
        if ROUTE_IMPORT_ERRORS:
            health_status["status"] = "degraded"
        if any(status == "failed" for status in health_status["checks"].values() if isinstance(status, str)):
            health_status["status"] = "unhealthy"
        elif any(status in ["degraded", "unknown"] for status in health_status["checks"].values() if isinstance(status, str)):
            health_status["status"] = "degraded"
        
        return health_status
    
    logger.info(f"✅ FastAPI app created for environment: {app_settings.environment}")
    return app


def configure_logging(app_settings: Settings):
    """Configure application logging based on environment"""
    log_level = logging.INFO if app_settings.is_production else logging.DEBUG
    
    # Enhanced logging format
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    if not app_settings.is_production:
        log_format = "%(asctime)s - %(name)s:%(lineno)d - %(levelname)s - %(message)s"
    
    logging.basicConfig(
        level=log_level,
        format=log_format,
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    # Set specific logger levels
    if app_settings.is_production:
        # Reduce noise in production
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
        logging.getLogger("httpx").setLevel(logging.WARNING)
    
    logger.info(f"📝 Logging configured for {app_settings.environment} environment")


def create_test_app(test_settings: Optional[Settings] = None) -> FastAPI:
    """
    Creates a FastAPI app specifically configured for testing.
    
    Args:
        test_settings: Optional test-specific settings
        
    Returns:
        FastAPI app configured for testing
    """
    if test_settings is None:
        # Create test-specific settings
        test_settings = Settings(
            environment="testing",
            debug_mode=True,
            # Use test database if available
            database_url=getattr(settings, 'test_database_url', "sqlite:///./test.db"),
            # Disable external services for testing
            enable_stripe=False,
            # Test-friendly URLs
            webapp_url="http://localhost:3000"
        )
    
    logger.info("🧪 Creating test application")
    return create_app(test_settings)


# Create the main app instance for production/development
try:
    app = create_app()
except Exception as e:
    logger.error(f"❌ Failed to create main app: {e}")
    # Create a minimal app for graceful degradation
    app = FastAPI(title="Email Bot API - Degraded Mode")
    
    @app.get("/")
    async def degraded_root():
        return {"status": "degraded", "error": "Application failed to initialize properly"}
    
    @app.get("/health")
    async def degraded_health():
        return {"status": "unhealthy", "error": "Application initialization failed"}


# Development server runner
if __name__ == "__main__":
    import uvicorn
    
    # Get settings for development server
    try:
        dev_settings = app.state.settings
    except:
        dev_settings = settings
    
    logger.info("🚀 Starting development server...")
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=not dev_settings.is_production,
        log_level="info" if dev_settings.is_production else "debug",
        access_log=not dev_settings.is_production
    )


# --- Testing Support ---

def get_test_client():
    """
    Helper function to create a test client for testing.
    Usage in tests:
        from main import get_test_client
        client = get_test_client()
    """
    try:
        from fastapi.testclient import TestClient
        test_app = create_test_app()
        return TestClient(test_app)
    except ImportError:
        logger.error("TestClient not available - install test dependencies")
        return None


# --- Environment-Specific App Creation ---

def create_development_app() -> FastAPI:
    """Create app specifically for development"""
    dev_settings = Settings(
        environment="development",
        debug_mode=True,
        enable_stripe=False  # Usually disabled in dev
    )
    return create_app(dev_settings)


def create_production_app() -> FastAPI:
    """Create app specifically for production with validation"""
    prod_settings = Settings(
        environment="production",
        debug_mode=False,
        enable_stripe=True  # Usually enabled in prod
    )
    
    # Validate production configuration
    validate_startup_configuration(prod_settings)
    
    return create_app(prod_settings)


def create_staging_app() -> FastAPI:
    """Create app for staging environment"""
    staging_settings = Settings(
        environment="staging",
        debug_mode=True,  # Keep debug on for staging
        enable_stripe=True  # Test with real Stripe in staging
    )
    return create_app(staging_settings)


# --- Health Check Functions for External Monitoring ---

def get_app_health() -> dict:
    """Get current application health status (for external monitoring)"""
    try:
        # This would check actual service health
        return {
            "status": "healthy",
            "timestamp": "2025-01-30T00:00:00Z",
            "uptime": "unknown",
            "version": "1.0.0"
        }
    except Exception as e:
        return {
            "status": "unhealthy", 
            "error": str(e),
            "timestamp": "2025-01-30T00:00:00Z"
        }


def get_service_metrics() -> dict:
    """Get basic service metrics (for monitoring/alerting)"""
    return {
        "requests_total": "unknown",  # Would track actual metrics
        "errors_total": "unknown",
        "response_time_avg": "unknown",
        "active_connections": "unknown"
    }