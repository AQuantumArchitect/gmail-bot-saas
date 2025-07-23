# main.py (save in project root)
"""
FastAPI main application - Email Bot API
Uses Application Factory pattern for testable, configurable SaaS architecture.

Location: Save this file in your project root directory
Usage: uvicorn main:app --reload
"""
import logging
from typing import Optional
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager

from app.core.config import Settings, settings
from app.api.middleware import setup_all_middleware
from app.api.exceptions import setup_exception_handlers
from app.api.routes import (
    health,
    auth,
    dashboard,
    gmail,
    billing
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.
    Handles startup and shutdown events.
    """
    # Get settings from app state
    app_settings = getattr(app.state, 'settings', settings)
    
    # Startup
    logger.info("Starting Email Bot API...")
    logger.info(f"Environment: {app_settings.environment}")
    logger.info(f"Debug mode: {app_settings.debug_mode}")
    logger.info(f"Webapp URL: {app_settings.webapp_url}")
    
    # Initialize services if needed
    # This would be where you'd initialize database connections,
    # external service clients, etc.
    
    logger.info("Email Bot API started successfully")
    
    yield
    
    # Shutdown
    logger.info("Shutting down Email Bot API...")
    
    # Cleanup resources
    # This would be where you'd close database connections,
    # cleanup background tasks, etc.
    
    logger.info("Email Bot API shut down successfully")


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
    log_level = logging.INFO if app_settings.is_production else logging.DEBUG
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    # Create FastAPI application with environment-specific settings
    app = FastAPI(
        title="Email Bot API",
        description="AI-powered email processing API with Gmail integration",
        version="1.0.0",
        docs_url="/docs" if not app_settings.is_production else None,
        redoc_url="/redoc" if not app_settings.is_production else None,
        lifespan=lifespan
    )
    
    # Store settings in app state for access by dependencies
    app.state.settings = app_settings
    
    # Set up middleware (order matters!)
    setup_all_middleware(app)
    
    # Set up exception handlers
    setup_exception_handlers(app)
    
    # Include routers
    app.include_router(health.router, prefix="/api")
    app.include_router(auth.router, prefix="/api")
    app.include_router(dashboard.router, prefix="/api")
    app.include_router(gmail.router, prefix="/api")
    app.include_router(billing.router, prefix="/api")
    
    # Root endpoint
    @app.get("/")
    async def root():
        """Root endpoint - basic API information."""
        return {
            "message": "Email Bot API",
            "version": "1.0.0",
            "status": "running",
            "environment": app_settings.environment,
            "docs_url": "/docs" if not app_settings.is_production else None
        }
    
    # Health check endpoint at root level
    @app.get("/health")
    async def health_check():
        """Simple health check endpoint."""
        return {
            "status": "healthy",
            "service": "email-bot-api",
            "version": "1.0.0",
            "environment": app_settings.environment
        }
    
    # Catch-all for undefined routes
    @app.get("/{path:path}")
    async def catch_all(request: Request, path: str):
        """Catch-all route for undefined endpoints."""
        return JSONResponse(
            status_code=404,
            content={
                "error": "not_found",
                "message": f"Endpoint not found: {request.method} {request.url.path}",
                "available_endpoints": [
                    "GET /health",
                    "GET /api/health",
                    "POST /api/auth/validate-token",
                    "GET /api/auth/me",
                    "GET /api/dashboard/data",
                    "POST /api/gmail/connect",
                    "GET /api/billing/packages",
                    "POST /api/billing/create-checkout",
                    "GET /docs (development only)" if not app_settings.is_production else None
                ]
            }
        )
    
    logger.info(f"FastAPI app created for environment: {app_settings.environment}")
    return app


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
            pytest_running=True,
            testing_mode=True,
            # Use test database if available
            database_url=getattr(settings, 'test_database_url', settings.database_url),
            # Disable external services for testing
            enable_stripe=False,
            enable_background_processing=False
        )
    
    return create_app(test_settings)


# Create the main app instance for production/development
app = create_app()


# Development server runner
if __name__ == "__main__":
    import uvicorn
    
    # Get settings for development server
    dev_settings = app.state.settings
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=not dev_settings.is_production,
        log_level="info" if dev_settings.is_production else "debug"
    )


# --- Testing Support ---

def get_test_client():
    """
    Helper function to create a test client for testing.
    Usage in tests:
        from main import get_test_client
        client = get_test_client()
    """
    from fastapi.testclient import TestClient
    test_app = create_test_app()
    return TestClient(test_app)


# --- Configuration Validation ---

def validate_configuration(app_settings: Settings) -> bool:
    """
    Validate that all required configuration is present.
    
    Args:
        app_settings: Settings to validate
        
    Returns:
        True if configuration is valid
        
    Raises:
        ValueError: If required configuration is missing
    """
    required_vars = [
        ("database_url", "Database URL"),
        ("google_client_id", "Google Client ID"),
        ("google_client_secret", "Google Client Secret"),
        ("anthropic_api_key", "Anthropic API Key"),
        ("webapp_url", "Webapp URL")
    ]
    
    missing = []
    for var_name, display_name in required_vars:
        if not getattr(app_settings, var_name, None):
            missing.append(display_name)
    
    if missing:
        raise ValueError(f"Missing required configuration: {', '.join(missing)}")
    
    # Validate environment-specific settings
    if app_settings.enable_stripe and not getattr(app_settings, 'stripe_secret_key', None):
        raise ValueError("Stripe is enabled but STRIPE_SECRET_KEY is missing")
    
    return True


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
    """Create app specifically for production"""
    prod_settings = Settings(
        environment="production",
        debug_mode=False,
        enable_stripe=True  # Usually enabled in prod
    )
    
    # Validate production configuration
    validate_configuration(prod_settings)
    
    return create_app(prod_settings)


# --- Example Usage for Different Environments ---

# For testing:
# test_app = create_test_app()
# client = TestClient(test_app)

# For development:
# dev_app = create_development_app()

# For production:
# prod_app = create_production_app()

# For custom configuration:
# custom_settings = Settings(environment="staging", debug_mode=True)
# staging_app = create_app(custom_settings)