# app/core/config.py
import os
import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List, Dict, Any

from pydantic import Field, AnyHttpUrl, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


@dataclass
class CreditPackage:
    """Represents a credit package that users can purchase"""
    key: str
    name: str
    credits: int
    price_cents: int
    popular: bool = False
    
    @property
    def price_usd(self) -> float:
        """Price in USD as float"""
        return self.price_cents / 100
    
    @property
    def price_per_credit_usd(self) -> float:
        """Price per credit in USD"""
        return self.price_cents / self.credits / 100
    
    def calculate_savings_percent(self, baseline_package: 'CreditPackage') -> Optional[float]:
        """Calculate savings percentage compared to baseline package"""
        if baseline_package.key == self.key:
            return None
        
        baseline_per_credit = baseline_package.price_per_credit_usd
        our_per_credit = self.price_per_credit_usd
        
        savings = ((baseline_per_credit - our_per_credit) / baseline_per_credit) * 100
        return round(savings, 1) if savings > 0 else None


class Settings(BaseSettings):
    # Pydantic model configuration
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding='utf-8',
        case_sensitive=False,
        extra="ignore"
    )

    # Database
    database_url: AnyHttpUrl = Field(..., validation_alias="SUPABASE_URL")
    database_key: str = Field(..., validation_alias="SUPABASE_KEY")
    database_service_key: str = Field(..., validation_alias="SUPABASE_SERVICE_KEY")
    database_jwt_secret: str = Field(..., validation_alias="SUPABASE_JWT_SECRET")
    test_database_url: Optional[AnyHttpUrl] = Field(None, validation_alias="TEST_DATABASE_URL")

    # OAuth
    google_client_id: str = Field(..., validation_alias="GOOGLE_CLIENT_ID")
    google_client_secret: str = Field(..., validation_alias="GOOGLE_CLIENT_SECRET")

    # API Keys
    anthropic_api_key: str = Field(..., validation_alias="ANTHROPIC_API_KEY")

    # Web
    webapp_url: AnyHttpUrl = Field(..., validation_alias="WEBAPP_URL")
    redirect_uri: AnyHttpUrl = Field(..., validation_alias="REDIRECT_URI")

    # Security
    state_secret_key: Optional[str] = Field(None, validation_alias="STATE_SECRET_KEY")
    vault_passphrase: str = Field(..., validation_alias="VAULT_PASSPHRASE")

    # Environment
    environment: str = Field("development", validation_alias="ENVIRONMENT")
    debug_mode: bool = Field(False, validation_alias="DEBUG_MODE")
    pytest_running: bool = Field(False, validation_alias="PYTEST_RUNNING")
    testing_mode: bool = Field(False, validation_alias="TESTING_MODE")

    # Feature flags
    enable_stripe: bool = Field(False, validation_alias="ENABLE_STRIPE")
    enable_background_processing: bool = Field(True, validation_alias="ENABLE_BACKGROUND_PROCESSING")
    enable_gmail_processing: bool = Field(True, validation_alias="ENABLE_GMAIL_PROCESSING")

    # Stripe Configuration
    stripe_secret_key: Optional[str] = Field(None, validation_alias="STRIPE_SECRET_KEY")
    stripe_publishable_key: Optional[str] = Field(None, validation_alias="STRIPE_PUBLISHABLE_KEY")
    stripe_webhook_secret: Optional[str] = Field(None, validation_alias="STRIPE_WEBHOOK_SECRET")
    
    # Stripe Performance Settings
    stripe_max_retries: int = Field(3, validation_alias="STRIPE_MAX_RETRIES")
    stripe_timeout_seconds: int = Field(30, validation_alias="STRIPE_TIMEOUT_SECONDS")
    stripe_retry_delay_seconds: int = Field(1, validation_alias="STRIPE_RETRY_DELAY_SECONDS")
    stripe_requests_per_second: int = Field(80, validation_alias="STRIPE_REQUESTS_PER_SECOND")

    # Credit Package Configuration
    credit_packages: Optional[Dict[str, Dict[str, Any]]] = Field(None, validation_alias="CREDIT_PACKAGES")

    @field_validator("google_client_id")
    def validate_google_client_id(cls, v: str) -> str:
        if not v.endswith('.apps.googleusercontent.com'):
            raise ValueError('Invalid Google Client ID format')
        return v

    @field_validator("anthropic_api_key")
    def validate_anthropic_key(cls, v: str) -> str:
        if not v.startswith('sk-'):
            raise ValueError('Invalid Anthropic API key')
        return v

    @model_validator(mode='after')
    def check_stripe_settings(self) -> 'Settings':
        if self.enable_stripe:
            if not self.stripe_secret_key:
                raise ValueError('STRIPE_SECRET_KEY is required when ENABLE_STRIPE is true')
            if not self.stripe_publishable_key:
                raise ValueError('STRIPE_PUBLISHABLE_KEY is required when ENABLE_STRIPE is true')
            if not self.stripe_webhook_secret:
                raise ValueError('STRIPE_WEBHOOK_SECRET is required when ENABLE_STRIPE is true')
        return self

    @model_validator(mode='after')
    def generate_state_secret(self) -> 'Settings':
        if self.debug_mode and not self.state_secret_key:
            self.state_secret_key = secrets.token_urlsafe(32)
        return self

    @property
    def is_local_development(self) -> bool:
        return self.environment == 'development'

    @property
    def is_production(self) -> bool:
        return self.environment == 'production'

    @property
    def portal_return_url(self) -> str:
        """Stripe portal return URL"""
        return f"{self.webapp_url}/billing/return"

    def get_credit_packages(self) -> Dict[str, CreditPackage]:
        """Get configured credit packages with defaults"""
        # Default packages
        default_packages = {
            "starter": CreditPackage(
                key="starter",
                name="Starter Pack", 
                credits=100, 
                price_cents=500,
                popular=False
            ),
            "pro": CreditPackage(
                key="pro",
                name="Pro Pack", 
                credits=1000, 
                price_cents=4000,
                popular=True
            ), 
            "enterprise": CreditPackage(
                key="enterprise",
                name="Enterprise Pack", 
                credits=5000, 
                price_cents=20000,
                popular=False
            ),
        }
        
        # Override with settings if available
        if self.credit_packages:
            for key, pkg_data in self.credit_packages.items():
                if key in default_packages:
                    default_packages[key] = CreditPackage(
                        key=key,
                        name=pkg_data.get("name", default_packages[key].name),
                        credits=pkg_data.get("credits", default_packages[key].credits),
                        price_cents=pkg_data.get("price_cents", default_packages[key].price_cents),
                        popular=pkg_data.get("popular", default_packages[key].popular)
                    )
        
        return default_packages
    
    def get_credit_package_by_key(self, package_key: str) -> Optional[CreditPackage]:
        """Get a credit package by its key"""
        packages = self.get_credit_packages()
        return packages.get(package_key)
    
    def get_packages_with_savings(self) -> Dict[str, Dict]:
        """Get all packages with calculated savings percentages"""
        packages = self.get_credit_packages()
        baseline = packages.get("starter")
        
        if not baseline:
            return {key: {"package": pkg, "savings_percent": None} 
                   for key, pkg in packages.items()}
        
        result = {}
        for key, package in packages.items():
            savings = package.calculate_savings_percent(baseline)
            result[key] = {
                "package": package,
                "savings_percent": savings
            }
        
        return result
    
    def validate_billing_configuration(self) -> bool:
        """Validate that all required billing configuration is present"""
        if self.enable_stripe:
            if not self.stripe_secret_key:
                raise ValueError("Stripe secret key is required when Stripe is enabled")
            if not self.stripe_webhook_secret:
                raise ValueError("Stripe webhook secret is required when Stripe is enabled")
        
        packages = self.get_credit_packages()
        if not packages:
            raise ValueError("At least one credit package must be configured")
        
        for key, package in packages.items():
            if package.credits <= 0:
                raise ValueError(f"Package {key} must have positive credits")
            if package.price_cents <= 0:
                raise ValueError(f"Package {key} must have positive price")
        
        return True


# Singleton global instance
settings = Settings()

# Helper accessors
def get_database_url() -> AnyHttpUrl:
    return settings.database_url

def get_database_key() -> str:
    return settings.database_key

def is_local_development() -> bool:
    return settings.is_local_development

def is_production() -> bool:
    return settings.is_production

def is_debug_mode() -> bool:
    return settings.debug_mode

def is_stripe_enabled() -> bool:
    return settings.enable_stripe

def is_background_processing_enabled() -> bool:
    return settings.enable_background_processing

def is_gmail_processing_enabled() -> bool:
    return settings.enable_gmail_processing