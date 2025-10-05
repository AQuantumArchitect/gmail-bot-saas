# main_v2.py
"""
PHOENIX MAIN - Clean FastAPI Application
Simplified, working FastAPI app with proper Supabase Auth integration.

PRINCIPLES:
- Clean imports (no import failures)
- Simplified middleware setup
- Proper error handling
- Focus on core functionality
- Easy to understand and maintain
"""
import logging
import sys
from typing import Optional
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

# Import our clean v2 modules
from app_v2.core.config import settings
from app_v2.core.exceptions import (
    ValidationError,
    NotFoundError,
    AuthenticationError,
    APIError
)

# Import route modules
from app_v2.api.routes import auth, gmail

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager with proper startup/shutdown."""
    # Startup
    logger.info("🚀 Starting Gmail Bot API v2...")
    logger.info(f"📍 Environment: {settings.environment}")
    logger.info(f"🔧 Debug mode: {settings.debug_mode}")
    logger.info(f"🌐 Webapp URL: {settings.webapp_url}")

    # Test core components
    try:
        from app_v2.services.auth_service import create_auth_service
        auth_service = create_auth_service()
        health = await auth_service.health_check()
        if health.get("healthy"):
            logger.info("✅ Auth service healthy")
        else:
            logger.warning("⚠️  Auth service degraded")
    except Exception as e:
        logger.error(f"❌ Auth service check failed: {e}")

    logger.info("🎉 Gmail Bot API v2 started successfully")

    yield

    # Shutdown
    logger.info("🛑 Shutting down Gmail Bot API v2...")

    # Cleanup Supabase connections
    try:
        from app_v2.external.supabase_client import close_supabase_client
        await close_supabase_client()
        logger.info("✅ Supabase client closed")
    except Exception as e:
        logger.warning(f"⚠️  Error closing Supabase client: {e}")

    logger.info("👋 Gmail Bot API v2 shut down successfully")


def create_app() -> FastAPI:
    """
    Application Factory - creates a clean, working FastAPI app.

    No import failures, no complex middleware, just clean functionality.
    """

    # Configure logging
    log_level = logging.INFO if settings.is_production else logging.DEBUG
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)]
    )

    # Create FastAPI app
    app = FastAPI(
        title="Gmail Bot API v2",
        description="Clean AI-powered email processing API with Supabase Auth + Vault",
        version="2.0.0",
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        openapi_url="/openapi.json" if not settings.is_production else None,
        lifespan=lifespan
    )

    # Store settings in app state
    app.state.settings = settings

    # ========== MIDDLEWARE ==========

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if not settings.is_production else [str(settings.webapp_url)],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ========== EXCEPTION HANDLERS ==========

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

    @app.exception_handler(APIError)
    async def api_error_handler(request: Request, exc: APIError):
        logger.error(f"API error on {request.url.path}: {exc.message}")
        return JSONResponse(
            status_code=500,
            content={
                "error": "api_error",
                "message": exc.message,
                "details": exc.details
            }
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
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
                "message": "An unexpected error occurred"
            }
        )

    # ========== ROUTES ==========

    # Include API routes
    app.include_router(auth.router, prefix="/api")
    app.include_router(gmail.router, prefix="/api")

    # Root endpoint
    @app.get("/", tags=["root"])
    async def root():
        """Root endpoint - API information."""
        return {
            "service": "Gmail Bot API v2",
            "version": "2.0.0",
            "status": "running",
            "environment": settings.environment,
            "features": {
                "supabase_auth": True,
                "gmail_vault": True,
                "jwt_validation": True,
                "clean_architecture": True
            },
            "endpoints": {
                "auth": "/api/auth",
                "gmail": "/api/gmail",
                "docs": "/docs" if not settings.is_production else None
            }
        }

    # Health check
    @app.get("/health", tags=["health"])
    async def health_check():
        """Simple health check endpoint."""
        return {
            "status": "healthy",
            "service": "gmail-bot-api-v2",
            "version": "2.0.0",
            "environment": settings.environment
        }

    # Detailed health check
    @app.get("/health/detailed", tags=["health"])
    async def detailed_health_check():
        """Detailed health check with service dependencies."""
        health_status = {
            "status": "healthy",
            "service": "gmail-bot-api-v2",
            "version": "2.0.0",
            "environment": settings.environment,
            "checks": {
                "auth_service": "unknown",
                "supabase_client": "unknown",
                "user_repository": "unknown"
            }
        }

        # Test auth service
        try:
            from app_v2.services.auth_service import create_auth_service
            auth_service = create_auth_service()
            auth_health = await auth_service.health_check()
            health_status["checks"]["auth_service"] = "healthy" if auth_health.get("healthy") else "unhealthy"
        except Exception as e:
            health_status["checks"]["auth_service"] = "error"
            logger.error(f"Auth service health check failed: {e}")

        # Set overall status
        if any(status in ["unhealthy", "error"] for status in health_status["checks"].values()):
            health_status["status"] = "degraded"

        return health_status

    logger.info("✅ FastAPI app created successfully")
    return app


# Create the app instance
app = create_app()


# Development server runner
if __name__ == "__main__":
    import uvicorn

    logger.info("🚀 Starting development server...")

    uvicorn.run(
        "main_v2:app",
        host="0.0.0.0",
        port=8001,  # Different port to avoid conflicts
        reload=not settings.is_production,
        log_level="info" if settings.is_production else "debug"
    )