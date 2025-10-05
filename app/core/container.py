# app/core/container.py
"""
Enterprise-grade Dependency Injection Container
Supports all new async enterprise repositories with proper dependency management.
Thread-safe, lazy initialization, comprehensive error handling.

Key SAAS Patterns:
- Singleton pattern for expensive resources
- Async-aware service creation
- Proper dependency order
- Clean interface segregation
- Health monitoring
- Legacy compatibility
"""
import logging
import asyncio
from typing import Optional, Dict, Any, List, Union
from threading import Lock, RLock

# Core imports
from app.core.config import settings, Settings

# Repository imports (our new enterprise repositories)
from app.data.repositories.billing_repository import BillingRepository
from app.data.repositories.user_repository import UserRepository
from app.data.repositories.gmail_repository import GmailRepository
from app.data.repositories.email_repository import EmailRepository
from app.data.repositories.job_repository import JobRepository
from app.data.repositories.audit_repository import AuditRepository

# External service imports
from app.external.stripe_client import StripeClient

# Service imports
from app.services.billing_service import BillingService

logger = logging.getLogger(__name__)


class ServiceContainer:
    """
    Enterprise-grade service container with async support and proper dependency management.
    
    Features:
    - Thread-safe singleton management
    - Async-aware service creation
    - Enterprise repository support
    - Proper initialization order
    - Resource cleanup
    - Comprehensive logging
    - Health monitoring
    - Backward compatibility
    """
    
    def __init__(self):
        # Thread-safe singleton cache
        self._singletons: Dict[str, Any] = {}
        self._lock = RLock()
        self._initialized = False
        self._async_lock = asyncio.Lock() if asyncio.get_event_loop().is_running() else None
    
    def initialize(self):
        """Initialize container - called once at startup."""
        with self._lock:
            if self._initialized:
                return
            
            logger.info("Initializing Enterprise ServiceContainer...")
            
            # Pre-create critical singletons
            try:
                # Core repositories (no dependencies)
                self.get_user_repository()
                self.get_billing_repository()
                self.get_gmail_repository()
                self.get_email_repository()
                self.get_job_repository()
                self.get_audit_repository()
                
                logger.info("Enterprise repositories initialized")
                
                # External services
                stripe_client = self.get_stripe_client()
                if stripe_client:
                    logger.info("Stripe client initialized")
                else:
                    logger.info("Stripe client disabled")
                
                self._initialized = True
                logger.info("Enterprise ServiceContainer initialized successfully")
                
            except Exception as e:
                logger.error(f"Failed to initialize ServiceContainer: {e}")
                raise
    
    # ========== REPOSITORY SINGLETONS ==========
    
    def get_user_repository(self) -> UserRepository:
        """Get user repository singleton."""
        return self._get_or_create_singleton('user_repo', UserRepository)
    
    def get_billing_repository(self) -> BillingRepository:
        """Get billing repository singleton."""
        return self._get_or_create_singleton('billing_repo', BillingRepository)
    
    def get_gmail_repository(self) -> GmailRepository:
        """Get Gmail repository singleton."""
        return self._get_or_create_singleton('gmail_repo', GmailRepository)
    
    def get_email_repository(self) -> EmailRepository:
        """Get email repository singleton."""
        return self._get_or_create_singleton('email_repo', EmailRepository)
    
    def get_job_repository(self) -> JobRepository:
        """Get job repository singleton."""
        return self._get_or_create_singleton('job_repo', JobRepository)
    
    def get_audit_repository(self) -> AuditRepository:
        """Get audit repository singleton."""
        return self._get_or_create_singleton('audit_repo', AuditRepository)
    
    # ========== EXTERNAL SERVICE SINGLETONS ==========
    
    def get_stripe_client(self) -> Optional[StripeClient]:
        """
        Get Stripe client singleton.
        Returns None if Stripe is not enabled.
        """
        if 'stripe_client' not in self._singletons:
            with self._lock:
                # Double-check pattern
                if 'stripe_client' not in self._singletons:
                    if settings.enable_stripe and settings.stripe_secret_key:
                        try:
                            self._singletons['stripe_client'] = StripeClient(
                                secret_key=settings.stripe_secret_key,
                                webhook_secret=settings.stripe_webhook_secret
                            )
                            logger.debug("Created StripeClient singleton")
                        except Exception as e:
                            logger.error(f"Failed to create StripeClient: {e}")
                            self._singletons['stripe_client'] = None
                    else:
                        self._singletons['stripe_client'] = None
                        logger.debug("Stripe client disabled by configuration")
        
        return self._singletons['stripe_client']
    
    # ========== SERVICE LAYER SINGLETONS ==========
    
    def get_auth_service(self):
        """Get auth service with dependencies."""
        return self._get_or_create_singleton(
            'auth_service',
            lambda: self._create_auth_service()
        )
    
    def get_billing_service(self) -> BillingService:
        """Get billing service with dependencies."""
        return self._get_or_create_singleton(
            'billing_service',
            lambda: self._create_billing_service()
        )
    
    def get_gmail_oauth_service(self):
        """Get Gmail OAuth service with dependencies."""
        return self._get_or_create_singleton(
            'gmail_oauth_service',
            lambda: self._create_gmail_oauth_service()
        )
    
    def get_gmail_service(self):
        """Get Gmail service with dependencies."""
        return self._get_or_create_singleton(
            'gmail_service',
            lambda: self._create_gmail_service()
        )
    
    def get_email_service(self):
        """Get email service with dependencies."""
        return self._get_or_create_singleton(
            'email_service',
            lambda: self._create_email_service()
        )
    
    def get_user_service(self):
        """Get user service with dependencies."""
        return self._get_or_create_singleton(
            'user_service',
            lambda: self._create_user_service()
        )
    
    def get_job_service(self):
        """Get job service with dependencies."""
        return self._get_or_create_singleton(
            'job_service',
            lambda: self._create_job_service()
        )
    
    def get_audit_service(self):
        """Get audit service with dependencies."""
        return self._get_or_create_singleton(
            'audit_service',
            lambda: self._create_audit_service()
        )
    
    # ========== SERVICE CREATION METHODS ==========
    
    def _create_auth_service(self):
        """Create auth service with proper dependencies."""
        try:
            from app.services.auth_service import AuthService
            return AuthService(
                user_repository=self.get_user_repository(),
                audit_repository=self.get_audit_repository()
            )
        except ImportError as e:
            logger.warning(f"AuthService not available: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to create AuthService: {e}")
            raise
    
    def _create_billing_service(self) -> BillingService:
        """Create billing service with proper dependencies."""
        try:
            return BillingService(
                billing_repo=self.get_billing_repository(),
                user_repo=self.get_user_repository(),
                stripe_client=self.get_stripe_client(),
                audit_repository=self.get_audit_repository()
            )
        except Exception as e:
            logger.error(f"Failed to create BillingService: {e}")
            raise
    
    def _create_gmail_oauth_service(self):
        """Create Gmail OAuth service with proper dependencies."""
        try:
            from app.services.gmail_oauth_service import GmailOAuthService
            return GmailOAuthService(
                gmail_repository=self.get_gmail_repository(),
                user_repository=self.get_user_repository(),
                audit_repository=self.get_audit_repository()
            )
        except ImportError as e:
            logger.warning(f"GmailOAuthService not available: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to create GmailOAuthService: {e}")
            raise
    
    def _create_gmail_service(self):
        """Create Gmail service with proper dependencies."""
        try:
            from app.services.gmail_service import GmailService
            return GmailService(
                gmail_repository=self.get_gmail_repository(),
                user_repository=self.get_user_repository(),
                email_repository=self.get_email_repository(),
                job_repository=self.get_job_repository(),
                oauth_service=self.get_gmail_oauth_service(),
                audit_repository=self.get_audit_repository()
            )
        except ImportError as e:
            logger.warning(f"GmailService not available: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to create GmailService: {e}")
            raise
    
    def _create_email_service(self):
        """Create email service with proper dependencies."""
        try:
            from app.services.email_service import EmailService
            return EmailService(
                gmail_service=self.get_gmail_service(),
                billing_service=self.get_billing_service(),
                auth_service=self.get_auth_service(),
                user_repository=self.get_user_repository(),
                email_repository=self.get_email_repository(),
                billing_repository=self.get_billing_repository(),
                audit_repository=self.get_audit_repository()
            )
        except ImportError as e:
            logger.warning(f"EmailService not available: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to create EmailService: {e}")
            raise
    
    def _create_user_service(self):
        """Create user service with proper dependencies."""
        try:
            from app.services.user_service import UserService
            return UserService(
                user_repository=self.get_user_repository(),
                billing_service=self.get_billing_service(),
                billing_repository=self.get_billing_repository(),
                email_repository=self.get_email_repository(),
                gmail_repository=self.get_gmail_repository(),
                audit_repository=self.get_audit_repository()
            )
        except ImportError as e:
            logger.warning(f"UserService not available: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to create UserService: {e}")
            raise
    
    def _create_job_service(self):
        """Create job service with proper dependencies."""
        try:
            from app.services.job_service import JobService
            return JobService(
                job_repository=self.get_job_repository(),
                user_repository=self.get_user_repository(),
                gmail_service=self.get_gmail_service(),
                email_service=self.get_email_service(),
                audit_repository=self.get_audit_repository()
            )
        except ImportError as e:
            logger.warning(f"JobService not available: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to create JobService: {e}")
            raise
    
    def _create_audit_service(self):
        """Create audit service with proper dependencies."""
        try:
            from app.services.audit_service import AuditService
            return AuditService(
                audit_repository=self.get_audit_repository(),
                user_repository=self.get_user_repository()
            )
        except ImportError as e:
            logger.warning(f"AuditService not available: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to create AuditService: {e}")
            raise

    def _create_email_processing_service(self):
        """Create email processing service with proper dependencies."""
        try:
            from app.services.email_processing_service import EmailProcessingService
            return EmailProcessingService(
                email_repository=self.get_email_repository(),
                user_repository=self.get_user_repository(),
                billing_service=self.get_billing_service()
            )
        except ImportError as e:
            logger.warning(f"EmailProcessingService not available: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to create EmailProcessingService: {e}")
            raise

    def get_email_processing_service(self):
        """Get email processing service singleton."""
        return self._get_or_create_singleton('email_processing_service', self._create_email_processing_service)

    # Add to the convenience functions section at bottom of container.py (around line 200+)
    def get_email_processing_service():
        """Convenience function to get email processing service."""
        return get_container().get_email_processing_service()
    
    # ========== ASYNC HELPER METHODS ==========
    
    async def get_service_async(self, service_name: str):
        """Get service asynchronously (for services that need async initialization)."""
        try:
            # Map service names to methods
            service_getters = {
                'auth_service': self.get_auth_service,
                'billing_service': self.get_billing_service,
                'gmail_oauth_service': self.get_gmail_oauth_service,
                'gmail_service': self.get_gmail_service,
                'email_service': self.get_email_service,
                'user_service': self.get_user_service,
                'job_service': self.get_job_service,
                'audit_service': self.get_audit_service,
            }
            
            getter = service_getters.get(service_name)
            if not getter:
                raise ValueError(f"Unknown service: {service_name}")
            
            # For now, all services are created synchronously
            # This method provides async interface for future async services
            return getter()
            
        except Exception as e:
            logger.error(f"Failed to get async service {service_name}: {e}")
            raise
    
    async def initialize_async_services(self):
        """Initialize services that require async setup."""
        try:
            # Currently all services are sync-initialized
            # This method is for future async service initialization
            logger.debug("Async service initialization complete")
        except Exception as e:
            logger.error(f"Failed to initialize async services: {e}")
            raise
    
    # ========== UTILITY METHODS ==========
    
    def _get_or_create_singleton(self, key: str, factory):
        """Thread-safe singleton creation with comprehensive error handling."""
        if key in self._singletons:
            return self._singletons[key]
        
        with self._lock:
            # Double-check pattern
            if key in self._singletons:
                return self._singletons[key]
            
            try:
                if callable(factory):
                    instance = factory()
                else:
                    # Factory is a class, instantiate it
                    instance = factory()
                
                self._singletons[key] = instance
                logger.debug(f"Created singleton: {key}")
                return instance
                
            except Exception as e:
                logger.error(f"Failed to create singleton {key}: {e}")
                # Store None to prevent repeated failures
                self._singletons[key] = None
                raise
    
    def health_check(self) -> Dict[str, Any]:
        """Comprehensive container health check."""
        try:
            health = {
                "container_status": "healthy",
                "initialized": self._initialized,
                "singletons_created": len([v for v in self._singletons.values() if v is not None]),
                "total_singletons": len(self._singletons),
                "repositories": {},
                "services": {},
                "external_services": {}
            }
            
            # Check repositories
            repositories = [
                ("user_repo", "UserRepository"),
                ("billing_repo", "BillingRepository"),
                ("gmail_repo", "GmailRepository"),
                ("email_repo", "EmailRepository"),
                ("job_repo", "JobRepository"),
                ("audit_repo", "AuditRepository")
            ]
            
            for repo_key, repo_name in repositories:
                if repo_key in self._singletons:
                    instance = self._singletons[repo_key]
                    if instance is not None:
                        health["repositories"][repo_name] = "available"
                        # Try to call health_check if available
                        if hasattr(instance, 'health_check'):
                            try:
                                repo_health = instance.health_check()
                                health["repositories"][f"{repo_name}_health"] = repo_health
                            except:
                                health["repositories"][f"{repo_name}_health"] = "health_check_failed"
                    else:
                        health["repositories"][repo_name] = "failed_to_create"
                else:
                    health["repositories"][repo_name] = "not_created"
            
            # Check services
            services = [
                ("auth_service", "AuthService"),
                ("billing_service", "BillingService"),
                ("gmail_oauth_service", "GmailOAuthService"),
                ("gmail_service", "GmailService"),
                ("email_service", "EmailService"),
                ("user_service", "UserService"),
                ("job_service", "JobService"),
                ("audit_service", "AuditService")
            ]
            
            for service_key, service_name in services:
                if service_key in self._singletons:
                    instance = self._singletons[service_key]
                    if instance is not None:
                        health["services"][service_name] = "available"
                    else:
                        health["services"][service_name] = "failed_to_create"
                else:
                    health["services"][service_name] = "not_created"
            
            # Check external services
            stripe_client = self._singletons.get('stripe_client')
            if stripe_client is not None:
                health["external_services"]["StripeClient"] = "available"
            elif settings.enable_stripe:
                health["external_services"]["StripeClient"] = "failed_to_create"
            else:
                health["external_services"]["StripeClient"] = "disabled"
            
            return health
            
        except Exception as e:
            return {
                "container_status": "unhealthy",
                "error": str(e),
                "initialized": self._initialized
            }
    
    def get_dependency_graph(self) -> Dict[str, List[str]]:
        """Get dependency graph for debugging."""
        return {
            "user_repo": [],
            "billing_repo": [],
            "gmail_repo": [],
            "email_repo": [],
            "job_repo": [],
            "audit_repo": [],
            "stripe_client": [],
            "auth_service": ["user_repo", "audit_repo"],
            "billing_service": ["billing_repo", "user_repo", "stripe_client", "audit_repo"],
            "gmail_oauth_service": ["gmail_repo", "user_repo", "audit_repo"],
            "gmail_service": ["gmail_repo", "user_repo", "email_repo", "job_repo", "gmail_oauth_service", "audit_repo"],
            "email_service": ["gmail_service", "billing_service", "auth_service", "user_repo", "email_repo", "billing_repo", "audit_repo"],
            "user_service": ["user_repo", "billing_service", "billing_repo", "email_repo", "gmail_repo", "audit_repo"],
            "job_service": ["job_repo", "user_repo", "gmail_service", "email_service", "audit_repo"],
            "audit_service": ["audit_repo", "user_repo"]
        }
    
    def reset_singletons(self):
        """Reset all singleton instances (useful for testing)."""
        with self._lock:
            old_count = len(self._singletons)
            # Call cleanup on services that support it
            for key, instance in self._singletons.items():
                if instance and hasattr(instance, 'cleanup'):
                    try:
                        instance.cleanup()
                        logger.debug(f"Cleaned up {key}")
                    except Exception as e:
                        logger.warning(f"Error cleaning up {key}: {e}")
            
            self._singletons.clear()
            self._initialized = False
            logger.debug(f"Reset {old_count} singletons")
    
    def close_resources(self):
        """Clean up resources properly."""
        with self._lock:
            # Close repositories that support it
            for key, instance in self._singletons.items():
                if instance and hasattr(instance, 'close'):
                    try:
                        instance.close()
                        logger.debug(f"Closed resource: {key}")
                    except Exception as e:
                        logger.warning(f"Error closing resource {key}: {e}")
            
            logger.info("Enterprise ServiceContainer resources closed")
    
    # ========== LEGACY COMPATIBILITY ==========
    
    @property
    def billing_config(self) -> Settings:
        """Legacy property - returns the global settings object."""
        return settings


# ========== GLOBAL CONTAINER MANAGEMENT ==========

# Global container instance
_container: Optional[ServiceContainer] = None
_container_lock = Lock()


def get_container() -> ServiceContainer:
    """Get the global service container instance."""
    global _container
    
    if _container is None:
        with _container_lock:
            # Double-check pattern
            if _container is None:
                _container = ServiceContainer()
                _container.initialize()
                logger.info("Created global Enterprise ServiceContainer")
    
    return _container


def reset_container():
    """Reset the global container (useful for testing)."""
    global _container
    
    with _container_lock:
        if _container:
            _container.close_resources()
            _container.reset_singletons()
        _container = None
        logger.info("Reset global Enterprise ServiceContainer")


async def get_container_async() -> ServiceContainer:
    """Get container with async initialization."""
    container = get_container()
    await container.initialize_async_services()
    return container


# ========== REPOSITORY CONVENIENCE FUNCTIONS ==========

def get_user_repository(self) -> UserRepository:
    """Get user repository singleton with Supabase client."""
    def create_user_repo():
        # Get Supabase client if available
        supabase_client = getattr(self, '_supabase_client', None)
        if not supabase_client:
            try:
                from app.external.supabase_client import SupabaseClient
                supabase_client = SupabaseClient()
                self._supabase_client = supabase_client
            except Exception:
                # Fall back to in-memory for testing/development
                logger.warning("Failed to create Supabase client, using in-memory UserRepository")
                return UserRepository()
        
        return UserRepository(supabase_client=supabase_client)
    
    return self._get_or_create_singleton('user_repo', create_user_repo)

def get_billing_repository() -> BillingRepository:
    """Convenience function to get the billing repository."""
    return get_container().get_billing_repository()


def get_gmail_repository() -> GmailRepository:
    """Convenience function to get the Gmail repository."""
    return get_container().get_gmail_repository()


def get_email_repository() -> EmailRepository:
    """Convenience function to get the email repository."""
    return get_container().get_email_repository()


def get_job_repository() -> JobRepository:
    """Convenience function to get the job repository."""
    return get_container().get_job_repository()


def get_audit_repository() -> AuditRepository:
    """Convenience function to get the audit repository."""
    return get_container().get_audit_repository()


# ========== SERVICE CONVENIENCE FUNCTIONS ==========

def get_auth_service():
    """Convenience function to get auth service."""
    return get_container().get_auth_service()


def get_billing_service() -> BillingService:
    """Convenience function to get the billing service."""
    return get_container().get_billing_service()


def get_gmail_oauth_service():
    """Convenience function to get Gmail OAuth service."""
    return get_container().get_gmail_oauth_service()


def get_gmail_service():
    """Convenience function to get Gmail service."""
    return get_container().get_gmail_service()


def get_email_service():
    """Convenience function to get email service."""
    return get_container().get_email_service()


def get_user_service():
    """Convenience function to get user service."""
    return get_container().get_user_service()


def get_job_service():
    """Convenience function to get job service."""
    return get_container().get_job_service()


def get_audit_service():
    """Convenience function to get audit service."""
    return get_container().get_audit_service()


# ========== EXTERNAL SERVICE CONVENIENCE FUNCTIONS ==========

def get_stripe_client() -> Optional[StripeClient]:
    """Convenience function to get the Stripe client."""
    return get_container().get_stripe_client()


# ========== LEGACY COMPATIBILITY FUNCTIONS ==========

def get_billing_config() -> Settings:
    """Legacy function - returns settings."""
    return settings


# ========== ASYNC CONVENIENCE FUNCTIONS ==========

async def get_service_async(service_name: str):
    """Get any service asynchronously."""
    container = await get_container_async()
    return await container.get_service_async(service_name)


# ========== HEALTH CHECK FUNCTIONS ==========

def container_health_check() -> Dict[str, Any]:
    """Get comprehensive container health status."""
    try:
        return get_container().health_check()
    except Exception as e:
        return {
            "container_status": "error",
            "error": str(e)
        }


def get_dependency_graph() -> Dict[str, List[str]]:
    """Get service dependency graph."""
    try:
        return get_container().get_dependency_graph()
    except Exception as e:
        logger.error(f"Failed to get dependency graph: {e}")
        return {}


# ========== TESTING UTILITIES ==========

def create_test_container() -> ServiceContainer:
    """Create a fresh container for testing."""
    container = ServiceContainer()
    container.initialize()
    return container


async def create_test_container_async() -> ServiceContainer:
    """Create a fresh container for testing with async initialization."""
    container = ServiceContainer()
    container.initialize()
    await container.initialize_async_services()
    return container
