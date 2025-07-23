# tests/unit/test_config.py - Test-First Configuration Driver
"""
Test-first driver for clean configuration system.

This test defines what the new app/config.py should look like:
- Standardized environment variable names
- Proper Pydantic V2 validation
- Environment detection
- Feature flags
- Clean error handling

The implementation thread will make these tests pass by building
the new configuration system.
"""

import pytest
import os
from unittest.mock import patch
from pydantic import ValidationError

# This import will initially fail - that's expected
# The implementation thread will build this to make tests pass
from app.config import Settings


class TestConfigurationStandardization:
    """Test standardized environment variable naming"""
    
    def test_database_url_standardization(self):
        """DATABASE_URL should replace SUPABASE_URL"""
        test_env = {
            'DATABASE_URL': 'https://test.supabase.co',
            'DATABASE_KEY': 'test_key',
            'DATABASE_SERVICE_KEY': 'test_service_key',
            'DATABASE_JWT_SECRET': 'test_jwt_secret',
            'GOOGLE_CLIENT_ID': 'test_client_id.apps.googleusercontent.com',
            'GOOGLE_CLIENT_SECRET': 'test_secret',
            'ANTHROPIC_API_KEY': 'sk-ant-test',
            'WEBAPP_URL': 'http://localhost:8000',
            'REDIRECT_URI': 'http://localhost:8000/auth/callback',
            'VAULT_PASSPHRASE': 'test_vault_passphrase'
        }
        
        with patch.dict(os.environ, test_env, clear=True):
            settings = Settings()
            assert str(settings.database_url) == 'https://test.supabase.co/'
            assert settings.database_key == 'test_key'
            assert settings.database_service_key == 'test_service_key'
    
    def test_google_oauth_standardization(self):
        """GOOGLE_* should replace GMAIL_* prefixes"""
        test_env = {
            'DATABASE_URL': 'https://test.supabase.co',
            'DATABASE_KEY': 'test_key',
            'DATABASE_SERVICE_KEY': 'test_service_key',
            'DATABASE_JWT_SECRET': 'test_jwt_secret',
            'GOOGLE_CLIENT_ID': '123-test.apps.googleusercontent.com',
            'GOOGLE_CLIENT_SECRET': 'GOCSPX-test_secret',
            'ANTHROPIC_API_KEY': 'sk-ant-test',
            'WEBAPP_URL': 'http://localhost:8000',
            'REDIRECT_URI': 'http://localhost:8000/auth/callback',
            'VAULT_PASSPHRASE': 'test_vault_passphrase'
        }
        
        with patch.dict(os.environ, test_env, clear=True):
            settings = Settings()
            assert settings.google_client_id == '123-test.apps.googleusercontent.com'
            assert settings.google_client_secret == 'GOCSPX-test_secret'
    
    def test_all_standardized_variable_names(self):
        """All environment variables should follow consistent naming"""
        test_env = {
            'DATABASE_URL': 'https://test.supabase.co',
            'DATABASE_KEY': 'test_key',
            'DATABASE_SERVICE_KEY': 'test_service_key',
            'DATABASE_JWT_SECRET': 'test_jwt_secret',
            'GOOGLE_CLIENT_ID': 'test_client_id.apps.googleusercontent.com',
            'GOOGLE_CLIENT_SECRET': 'test_secret',
            'ANTHROPIC_API_KEY': 'sk-ant-test',
            'WEBAPP_URL': 'http://localhost:8000',
            'REDIRECT_URI': 'http://localhost:8000/auth/callback',
            'STATE_SECRET_KEY': 'test_state_secret',
            'VAULT_PASSPHRASE': 'test_vault_passphrase'
        }
        
        with patch.dict(os.environ, test_env, clear=True):
            settings = Settings()
            
            # Test all required fields are accessible
            assert hasattr(settings, 'database_url')
            assert hasattr(settings, 'database_key') 
            assert hasattr(settings, 'database_service_key')
            assert hasattr(settings, 'database_jwt_secret')
            assert hasattr(settings, 'google_client_id')
            assert hasattr(settings, 'google_client_secret')
            assert hasattr(settings, 'anthropic_api_key')
            assert hasattr(settings, 'webapp_url')
            assert hasattr(settings, 'redirect_uri')
            assert hasattr(settings, 'state_secret_key')
            assert hasattr(settings, 'vault_passphrase')


class TestConfigurationValidation:
    """Test Pydantic V2 validation catches errors"""
    
    def test_required_fields_validation(self):
        """Missing required fields should raise ValidationError"""
        from pydantic_settings import SettingsConfigDict
        
        # Create a test-specific Settings class that doesn't load .env files
        class TestSettings(Settings):
            model_config = SettingsConfigDict(
                env_file=None,  # Don't load .env files
                case_sensitive=False,
                validate_default=True
            )
        
        # Test with completely empty environment
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValidationError) as exc_info:
                TestSettings()
            
            # Should mention missing required fields
            error_str = str(exc_info.value)
            assert 'database_url' in error_str or 'Field required' in error_str
    
    def test_url_format_validation(self):
        """Invalid URL formats should be rejected"""
        invalid_urls = ['not-a-url', 'ftp://invalid.com', '', 'http://']
        
        for invalid_url in invalid_urls:
            test_env = {
                'DATABASE_URL': invalid_url,
                'DATABASE_KEY': 'test_key',
                'DATABASE_SERVICE_KEY': 'test_service_key',
                'DATABASE_JWT_SECRET': 'test_jwt_secret',
                'GOOGLE_CLIENT_ID': 'test_client_id.apps.googleusercontent.com',
                'GOOGLE_CLIENT_SECRET': 'test_secret',
                'ANTHROPIC_API_KEY': 'sk-ant-test',
                'WEBAPP_URL': 'http://localhost:8000',
                'REDIRECT_URI': 'http://localhost:8000/auth/callback',
                'VAULT_PASSPHRASE': 'test_vault_passphrase'
            }
            
            with patch.dict(os.environ, test_env, clear=True):
                with pytest.raises(ValidationError):
                    Settings()
    
    def test_api_key_format_validation(self):
        """Invalid API key formats should be rejected"""
        invalid_keys = ['', 'too-short', 'invalid-format']
        
        for invalid_key in invalid_keys:
            test_env = {
                'DATABASE_URL': 'https://test.supabase.co',
                'DATABASE_KEY': 'test_key',
                'DATABASE_SERVICE_KEY': 'test_service_key',
                'DATABASE_JWT_SECRET': 'test_jwt_secret',
                'GOOGLE_CLIENT_ID': 'test_client_id.apps.googleusercontent.com',
                'GOOGLE_CLIENT_SECRET': 'test_secret',
                'ANTHROPIC_API_KEY': invalid_key,
                'WEBAPP_URL': 'http://localhost:8000',
                'REDIRECT_URI': 'http://localhost:8000/auth/callback',
                'VAULT_PASSPHRASE': 'test_vault_passphrase'
            }
            
            with patch.dict(os.environ, test_env, clear=True):
                with pytest.raises(ValidationError):
                    Settings()
    
    def test_google_client_id_validation(self):
        """Google Client ID should have proper format"""
        test_env = {
            'DATABASE_URL': 'https://test.supabase.co',
            'DATABASE_KEY': 'test_key',
            'DATABASE_SERVICE_KEY': 'test_service_key',
            'DATABASE_JWT_SECRET': 'test_jwt_secret',
            'GOOGLE_CLIENT_ID': 'invalid-client-id',
            'GOOGLE_CLIENT_SECRET': 'test_secret',
            'ANTHROPIC_API_KEY': 'sk-ant-test',
            'WEBAPP_URL': 'http://localhost:8000',
            'REDIRECT_URI': 'http://localhost:8000/auth/callback',
            'VAULT_PASSPHRASE': 'test_vault_passphrase'
        }
        
        with patch.dict(os.environ, test_env, clear=True):
            with pytest.raises(ValidationError):
                Settings()


class TestEnvironmentDetection:
    """Test environment detection and configuration"""
    
    def test_development_environment_detection(self):
        """Should detect development environment correctly"""
        test_env = {
            'DATABASE_URL': 'https://test.supabase.co',
            'DATABASE_KEY': 'test_key',
            'DATABASE_SERVICE_KEY': 'test_service_key',
            'DATABASE_JWT_SECRET': 'test_jwt_secret',
            'GOOGLE_CLIENT_ID': 'test_client_id.apps.googleusercontent.com',
            'GOOGLE_CLIENT_SECRET': 'test_secret',
            'ANTHROPIC_API_KEY': 'sk-ant-test',
            'WEBAPP_URL': 'http://localhost:8000',
            'REDIRECT_URI': 'http://localhost:8000/auth/callback',
            'ENVIRONMENT': 'development',
            'DEBUG_MODE': 'true',
            'VAULT_PASSPHRASE': 'test_vault_passphrase'
        }
        
        with patch.dict(os.environ, test_env, clear=True):
            settings = Settings()
            assert settings.environment == 'development'
            assert settings.debug_mode == True
            assert settings.is_local_development == True
            assert settings.is_production == False
    
    def test_production_environment_detection(self):
        """Should detect production environment correctly"""
        test_env = {
            'DATABASE_URL': 'https://prod.supabase.co',
            'DATABASE_KEY': 'prod_key',
            'DATABASE_SERVICE_KEY': 'prod_service_key',
            'DATABASE_JWT_SECRET': 'test_jwt_secret',
            'GOOGLE_CLIENT_ID': 'prod_client_id.apps.googleusercontent.com',
            'GOOGLE_CLIENT_SECRET': 'prod_secret',
            'ANTHROPIC_API_KEY': 'sk-ant-prod',
            'WEBAPP_URL': 'https://emailbot.com',
            'REDIRECT_URI': 'https://emailbot.com/auth/callback',
            'ENVIRONMENT': 'production',
            'DEBUG_MODE': 'false',
            'VAULT_PASSPHRASE': 'test_vault_passphrase'
        }
        
        with patch.dict(os.environ, test_env, clear=True):
            settings = Settings()
            assert settings.environment == 'production'
            assert settings.debug_mode == False
            assert settings.is_local_development == False
            assert settings.is_production == True
    
    def test_testing_environment_detection(self):
        """Should detect testing environment correctly"""
        test_env = {
            'DATABASE_URL': 'https://test.supabase.co',
            'DATABASE_KEY': 'test_key',
            'DATABASE_SERVICE_KEY': 'test_service_key',
            'DATABASE_JWT_SECRET': 'test_jwt_secret',
            'GOOGLE_CLIENT_ID': 'test_client_id.apps.googleusercontent.com',
            'GOOGLE_CLIENT_SECRET': 'test_secret',
            'ANTHROPIC_API_KEY': 'sk-ant-test',
            'WEBAPP_URL': 'http://localhost:8000',
            'REDIRECT_URI': 'http://localhost:8000/auth/callback',
            'PYTEST_RUNNING': 'true',
            'TESTING_MODE': 'true',
            'VAULT_PASSPHRASE': 'test_vault_passphrase'
        }
        
        with patch.dict(os.environ, test_env, clear=True):
            settings = Settings()
            assert settings.pytest_running == True
            assert settings.testing_mode == True


class TestFeatureFlags:
    """Test feature flag functionality"""
    
    def test_stripe_feature_flag(self):
        """Stripe can be enabled/disabled via feature flag"""
        # Test enabled
        test_env = {
            'DATABASE_URL': 'https://test.supabase.co',
            'DATABASE_KEY': 'test_key',
            'DATABASE_SERVICE_KEY': 'test_service_key',
            'DATABASE_JWT_SECRET': 'test_jwt_secret',
            'GOOGLE_CLIENT_ID': 'test_client_id.apps.googleusercontent.com',
            'GOOGLE_CLIENT_SECRET': 'test_secret',
            'ANTHROPIC_API_KEY': 'sk-ant-test',
            'WEBAPP_URL': 'http://localhost:8000',
            'REDIRECT_URI': 'http://localhost:8000/auth/callback',
            'ENABLE_STRIPE': 'true',
            'VAULT_PASSPHRASE': 'test_vault_passphrase'
        }
        
        with patch.dict(os.environ, test_env, clear=True):
            settings = Settings()
            assert settings.enable_stripe == True
        
        # Test disabled
        test_env['ENABLE_STRIPE'] = 'false'
        with patch.dict(os.environ, test_env, clear=True):
            settings = Settings()
            assert settings.enable_stripe == False
    
    def test_background_processing_feature_flag(self):
        """Background processing can be enabled/disabled"""
        test_env = {
            'DATABASE_URL': 'https://test.supabase.co',
            'DATABASE_KEY': 'test_key',
            'DATABASE_SERVICE_KEY': 'test_service_key',
            'DATABASE_JWT_SECRET': 'test_jwt_secret',
            'GOOGLE_CLIENT_ID': 'test_client_id.apps.googleusercontent.com',
            'GOOGLE_CLIENT_SECRET': 'test_secret',
            'ANTHROPIC_API_KEY': 'sk-ant-test',
            'WEBAPP_URL': 'http://localhost:8000',
            'REDIRECT_URI': 'http://localhost:8000/auth/callback',
            'ENABLE_BACKGROUND_PROCESSING': 'false',
            'VAULT_PASSPHRASE': 'test_vault_passphrase'
        }
        
        with patch.dict(os.environ, test_env, clear=True):
            settings = Settings()
            assert settings.enable_background_processing == False
    
    def test_gmail_processing_feature_flag(self):
        """Gmail processing can be enabled/disabled"""
        test_env = {
            'DATABASE_URL': 'https://test.supabase.co',
            'DATABASE_KEY': 'test_key',
            'DATABASE_SERVICE_KEY': 'test_service_key',
            'DATABASE_JWT_SECRET': 'test_jwt_secret',
            'GOOGLE_CLIENT_ID': 'test_client_id.apps.googleusercontent.com',
            'GOOGLE_CLIENT_SECRET': 'test_secret',
            'ANTHROPIC_API_KEY': 'sk-ant-test',
            'WEBAPP_URL': 'http://localhost:8000',
            'REDIRECT_URI': 'http://localhost:8000/auth/callback',
            'ENABLE_GMAIL_PROCESSING': 'true',
            'VAULT_PASSPHRASE': 'test_vault_passphrase'
        }
        
        with patch.dict(os.environ, test_env, clear=True):
            settings = Settings()
            assert settings.enable_gmail_processing == True


class TestDevelopmentBypasses:
    """Test development bypass functionality"""
    
    def test_dev_auth_bypass_only_in_debug(self):
        """Dev auth bypass should only work in debug mode"""
        # Should work in debug mode
        test_env = {
            'DATABASE_URL': 'https://test.supabase.co',
            'DATABASE_KEY': 'test_key',
            'DATABASE_SERVICE_KEY': 'test_service_key',
            'DATABASE_JWT_SECRET': 'test_jwt_secret',
            'GOOGLE_CLIENT_ID': 'test_client_id.apps.googleusercontent.com',
            'GOOGLE_CLIENT_SECRET': 'test_secret',
            'ANTHROPIC_API_KEY': 'sk-ant-test',
            'WEBAPP_URL': 'http://localhost:8000',
            'REDIRECT_URI': 'http://localhost:8000/auth/callback',
            'DEBUG_MODE': 'true',
            'DEV_AUTH_BYPASS': 'true',
            'VAULT_PASSPHRASE': 'test_vault_passphrase'
        }
        
        with patch.dict(os.environ, test_env, clear=True):
            settings = Settings()
            assert settings.dev_auth_bypass == True
        
        # Should fail in production mode
        test_env['DEBUG_MODE'] = 'false'
        with patch.dict(os.environ, test_env, clear=True):
            with pytest.raises(ValidationError):
                Settings()
    
    def test_dev_admin_bypass_only_in_debug(self):
        """Dev admin bypass should only work in debug mode"""
        # Should work in debug mode
        test_env = {
            'DATABASE_URL': 'https://test.supabase.co',
            'DATABASE_KEY': 'test_key',
            'DATABASE_SERVICE_KEY': 'test_service_key',
            'DATABASE_JWT_SECRET': 'test_jwt_secret',
            'GOOGLE_CLIENT_ID': 'test_client_id.apps.googleusercontent.com',
            'GOOGLE_CLIENT_SECRET': 'test_secret',
            'ANTHROPIC_API_KEY': 'sk-ant-test',
            'WEBAPP_URL': 'http://localhost:8000',
            'REDIRECT_URI': 'http://localhost:8000/auth/callback',
            'DEBUG_MODE': 'true',
            'DEV_ADMIN_BYPASS': 'true',
            'VAULT_PASSPHRASE': 'test_vault_passphrase'
        }
        
        with patch.dict(os.environ, test_env, clear=True):
            settings = Settings()
            assert settings.dev_admin_bypass == True
        
        # Should fail in production mode
        test_env['DEBUG_MODE'] = 'false'
        with patch.dict(os.environ, test_env, clear=True):
            with pytest.raises(ValidationError):
                Settings()


class TestOptionalFields:
    """Test optional fields and their defaults"""
    
    def test_optional_stripe_fields(self):
        """Stripe fields should be optional when Stripe disabled"""
        test_env = {
            'DATABASE_URL': 'https://test.supabase.co',
            'DATABASE_KEY': 'test_key',
            'DATABASE_SERVICE_KEY': 'test_service_key',
            'DATABASE_JWT_SECRET': 'test_jwt_secret',
            'GOOGLE_CLIENT_ID': 'test_client_id.apps.googleusercontent.com',
            'GOOGLE_CLIENT_SECRET': 'test_secret',
            'ANTHROPIC_API_KEY': 'sk-ant-test',
            'WEBAPP_URL': 'http://localhost:8000',
            'REDIRECT_URI': 'http://localhost:8000/auth/callback',
            'ENABLE_STRIPE': 'false',
            'VAULT_PASSPHRASE': 'test_vault_passphrase'
        }
        
        with patch.dict(os.environ, test_env, clear=True):
            settings = Settings()
            assert settings.enable_stripe == False
            # Should work without Stripe keys
    
    def test_required_stripe_fields_when_enabled(self):
        """Stripe fields should be required when Stripe enabled"""
        from pydantic_settings import SettingsConfigDict
        
        # Create a test-specific Settings class that doesn't load .env files
        class TestSettings(Settings):
            model_config = SettingsConfigDict(
                env_file=None,  # Don't load .env files
                case_sensitive=False,
                validate_default=True
            )
        
        test_env = {
            'DATABASE_URL': 'https://test.supabase.co',
            'DATABASE_KEY': 'test_key',
            'DATABASE_SERVICE_KEY': 'test_service_key',
            'DATABASE_JWT_SECRET': 'test_jwt_secret',
            'GOOGLE_CLIENT_ID': 'test_client_id.apps.googleusercontent.com',
            'GOOGLE_CLIENT_SECRET': 'test_secret',
            'ANTHROPIC_API_KEY': 'sk-ant-test',
            'WEBAPP_URL': 'http://localhost:8000',
            'REDIRECT_URI': 'http://localhost:8000/auth/callback',
            'ENABLE_STRIPE': 'true',
            'VAULT_PASSPHRASE': 'test_vault_passphrase'
            # Missing STRIPE_SECRET_KEY
        }
        
        with patch.dict(os.environ, test_env, clear=True):
            with pytest.raises(ValueError):
                TestSettings()
    
    def test_state_secret_key_auto_generation(self):
        """STATE_SECRET_KEY should auto-generate in development"""
        test_env = {
            'DATABASE_URL': 'https://test.supabase.co',
            'DATABASE_KEY': 'test_key',
            'DATABASE_SERVICE_KEY': 'test_service_key',
            'DATABASE_JWT_SECRET': 'test_jwt_secret',
            'GOOGLE_CLIENT_ID': 'test_client_id.apps.googleusercontent.com',
            'GOOGLE_CLIENT_SECRET': 'test_secret',
            'ANTHROPIC_API_KEY': 'sk-ant-test',
            'WEBAPP_URL': 'http://localhost:8000',
            'REDIRECT_URI': 'http://localhost:8000/auth/callback',
            'DEBUG_MODE': 'true',
            'VAULT_PASSPHRASE': 'test_vault_passphrase'
            # Missing STATE_SECRET_KEY - should auto-generate
        }
        
        with patch.dict(os.environ, test_env, clear=True):
            settings = Settings()
            assert settings.state_secret_key is not None
            assert len(settings.state_secret_key) > 0


class TestConfigurationService:
    """Test configuration service functionality"""
    
    def test_settings_singleton_behavior(self):
        """Settings should behave as expected for singleton pattern"""
        test_env = {
            'DATABASE_URL': 'https://test.supabase.co',
            'DATABASE_KEY': 'test_key',
            'DATABASE_SERVICE_KEY': 'test_service_key',
            'DATABASE_JWT_SECRET': 'test_jwt_secret',
            'GOOGLE_CLIENT_ID': 'test_client_id.apps.googleusercontent.com',
            'GOOGLE_CLIENT_SECRET': 'test_secret',
            'ANTHROPIC_API_KEY': 'sk-ant-test',
            'WEBAPP_URL': 'http://localhost:8000',
            'REDIRECT_URI': 'http://localhost:8000/auth/callback',
            'VAULT_PASSPHRASE': 'test_vault_passphrase'
        }
        
        with patch.dict(os.environ, test_env, clear=True):
            settings1 = Settings()
            settings2 = Settings()
            
            # Both should work
            assert settings1.database_url == settings2.database_url
    
    def test_global_settings_instance(self):
        """Global settings instance should be accessible"""
        # This tests that app.config has a global 'settings' instance
        from app.config import settings
        
        assert hasattr(settings, 'database_url')
        assert hasattr(settings, 'debug_mode')
    
    def test_helper_functions(self):
        """Helper functions should work correctly"""
        # These should exist in the new config
        from app.config import (
            get_database_url,
            get_database_key,
            is_local_development,
            is_stripe_enabled,
            is_background_processing_enabled,
            is_debug_mode
        )
        
        # Should be callable
        assert callable(get_database_url)
        assert callable(get_database_key)
        assert callable(is_local_development)
        assert callable(is_stripe_enabled)
        assert callable(is_background_processing_enabled)
        assert callable(is_debug_mode)


