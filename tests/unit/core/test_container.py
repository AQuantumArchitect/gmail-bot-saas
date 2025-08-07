# tests/unit/test_container.py
"""
Test-first driver for the SAAS-Quality Dependency Injection Container.

This test suite verifies that the ServiceContainer in app/core/container.py
correctly manages the lifecycle and dependencies of all services and repositories.

Success Criteria Verified:
- ✅ All services instantiate without errors.
- ✅ Dependency injection works correctly.
- ✅ No circular dependency crashes are detected.
- ✅ Container health reports "healthy".
- ✅ Singleton patterns are enforced for services and repositories.
- ✅ Conditional dependency creation (e.g., Stripe) is handled.
"""

import pytest
from unittest.mock import patch, MagicMock

# Import the container and the functions to test
from app.core.container import (
    ServiceContainer,
    get_container,
    reset_container,
    container_health_check,
    # Import convenience functions to test them as well
    get_auth_service,
    get_billing_service,
    get_email_service,
    get_gmail_service,
    get_user_service,
    get_user_repository,
)

# --- Fixtures ---

@pytest.fixture(autouse=True)
def isolated_container():
    """
    Fixture to automatically reset the global container before and after each test.
    This ensures that tests are isolated and don't interfere with each other,
    which is critical when testing singletons.
    """
    # Reset before the test runs
    reset_container()
    yield
    # Reset after the test finishes
    reset_container()


@pytest.fixture(scope="class")
def mock_all_dependencies():
    """
    A class-scoped fixture to mock all external classes (services, repositories)
    for the duration of the test class. This prevents any real logic
    (like database calls) from running and isolates the container's behavior.
    """
    # Patches are applied to the location where the object is looked up.
    # For top-level imports in container.py, we patch them in that module's namespace.
    # For local imports inside methods (like for AuthService), we must patch the source module.
    with patch('app.core.container.UserRepository', MagicMock()), \
         patch('app.core.container.BillingRepository', MagicMock()), \
         patch('app.core.container.GmailRepository', MagicMock()), \
         patch('app.core.container.EmailRepository', MagicMock()), \
         patch('app.core.container.StripeClient', MagicMock()), \
         patch('app.core.container.BillingService', MagicMock(name="MockBillingService")), \
         patch('app.services.auth_service.AuthService', MagicMock(name="MockAuthService")), \
         patch('app.services.gmail_oauth_service.GmailOAuthService', MagicMock(name="MockGmailOAuthService")), \
         patch('app.services.gmail_service.GmailService', MagicMock(name="MockGmailService")), \
         patch('app.services.email_service.EmailService', MagicMock(name="MockEmailService")), \
         patch('app.services.user_service.UserService', MagicMock(name="MockUserService")):
        
        # The 'with' block activates the patches. We just need to yield to let the tests run.
        yield


@pytest.mark.usefixtures("mock_all_dependencies")
class TestSaaSContainerSmokeTests:
    """
    Tests the container in a fully mocked environment.
    Focuses on instantiation, singleton behavior, and health checks.
    """

    def test_get_container_is_singleton(self):
        """Verify that get_container() always returns the same instance."""
        container1 = get_container()
        container2 = get_container()
        assert container1 is container2
        assert isinstance(container1, ServiceContainer)

    def test_all_services_instantiate_without_errors(self):
        """
        High-level smoke test to ensure all services can be created.
        This also acts as a basic check for hidden circular dependencies.
        """
        container = get_container()
        
        # Attempt to get every service. If there's a circular dependency
        # or a basic instantiation error, this will fail with a RecursionError or other exception.
        assert container.get_auth_service() is not None
        assert container.get_billing_service() is not None
        assert container.get_gmail_oauth_service() is not None
        assert container.get_gmail_service() is not None
        assert container.get_email_service() is not None
        assert container.get_user_service() is not None
        
        # Also verify they are singletons by calling a getter twice
        assert container.get_email_service() is container.get_email_service()

    def test_all_repositories_are_singletons(self):
        """Verify that all repository getters return singleton instances."""
        container = get_container()
        
        # A list of getter methods to test
        repo_getters = [
            container.get_user_repository,
            container.get_billing_repository,
            container.get_gmail_repository,
            container.get_email_repository,
        ]
        
        for getter in repo_getters:
            instance1 = getter()
            instance2 = getter()
            assert instance1 is instance2, f"Repository from {getter.__name__} is not a singleton."

    @patch('app.core.container.settings')
    def test_stripe_client_is_conditional(self, mock_settings):
        """Test StripeClient is only created when enabled in settings."""
        # Case 1: Stripe is enabled
        mock_settings.enable_stripe = True
        mock_settings.stripe_secret_key = 'sk_test_123'
        mock_settings.stripe_webhook_secret = 'whsec_123'
        
        container = get_container()
        client1 = container.get_stripe_client()
        assert client1 is not None
        
        # Check it's a singleton
        client2 = container.get_stripe_client()
        assert client1 is client2
        
        # Reset for the next case
        reset_container()
        
        # Case 2: Stripe is disabled
        mock_settings.enable_stripe = False
        container = get_container()
        client3 = container.get_stripe_client()
        assert client3 is None

    def test_health_check_reports_healthy(self):
        """Test that the container_health_check function returns a healthy status."""
        # Instantiate a few services to populate the singletons cache
        container = get_container()
        container.get_user_repository()
        container.get_auth_service()
        
        health = container_health_check()
        
        assert health['container_status'] == 'healthy'
        assert health['initialized'] is True
        assert health['singletons_created'] >= 2
        assert health['services']['user_repo'] == 'available'
        assert health['services']['auth_service'] == 'available'
        assert health['services']['billing_repo'] == 'not_created'

    def test_health_check_reports_unhealthy_on_failure(self):
        """Test health check reports 'error' if container creation fails."""
        with patch('app.core.container.ServiceContainer.initialize', side_effect=Exception("Init Failed")):
            # The exception should be caught and reported in the health check
            health = container_health_check()
            assert health['container_status'] == 'error'
            assert health['error'] == 'Init Failed'
            
    def test_convenience_functions_call_container(self):
        """Verify that global convenience functions delegate to the container."""
        # We patch the container's methods to see if they are called
        with patch.object(ServiceContainer, 'get_auth_service') as mock_get_auth, \
             patch.object(ServiceContainer, 'get_user_repository') as mock_get_user_repo:

            # Call the global convenience functions
            get_auth_service()
            get_user_repository()

            # Check the underlying container methods were called
            mock_get_auth.assert_called_once()
            mock_get_user_repo.assert_called_once()


class TestSaaSDependencyInjection:
    """
    Tests the container's core dependency injection logic, ensuring services
    are constructed with the correct dependencies.
    """

    def test_dependency_injection_for_email_service(self):
        """
        Verify that EmailService is created with the correct dependencies
        from the container itself. This is a critical test of the container's main purpose.
        """
        # Patch the EmailService to inspect its constructor call, and mock its dependencies.
        with patch('app.services.email_service.EmailService', autospec=True) as PatchedEmailService:
            container = get_container()
            
            # Get the service, which will trigger its creation and injection
            container.get_email_service()
            
            # Check that the constructor was called exactly once
            PatchedEmailService.assert_called_once()
            
            # Get the keyword arguments passed to the constructor
            _, kwargs = PatchedEmailService.call_args
            
            # Assert that the injected dependencies are the same instances
            # that the container would provide if we called their getters.
            assert kwargs['gmail_service'] == container.get_gmail_service()
            assert kwargs['billing_service'] == container.get_billing_service()
            assert kwargs['auth_service'] == container.get_auth_service()
            assert kwargs['user_repository'] == container.get_user_repository()
            assert kwargs['email_repository'] == container.get_email_repository()
            assert kwargs['billing_repository'] == container.get_billing_repository()

    def test_dependency_injection_for_user_service(self):
        """
        Verify that UserService is created with the correct dependencies.
        """
        # Patch the UserService to inspect its constructor call, and mock its dependencies.
        with patch('app.services.user_service.UserService', autospec=True) as PatchedUserService:
            container = get_container()
            container.get_user_service()
            
            PatchedUserService.assert_called_once()
            _, kwargs = PatchedUserService.call_args
            
            assert kwargs['user_repository'] == container.get_user_repository()
            assert kwargs['billing_service'] == container.get_billing_service()
            assert kwargs['billing_repository'] == container.get_billing_repository()
            assert kwargs['email_repository'] == container.get_email_repository()
            assert kwargs['gmail_repository'] == container.get_gmail_repository()
