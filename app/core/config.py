# app/core/config.py
import os
import secrets
from datetime import datetime
from typing import Optional, List, Dict, Any

from pydantic import Field, AnyHttpUrl, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # Stripe
    stripe_secret_key: Optional[str] = Field(None, validation_alias="STRIPE_SECRET_KEY")
    stripe_publishable_key: Optional[str] = Field(None, validation_alias="STRIPE_PUBLISHABLE_KEY")
    stripe_webhook_secret: Optional[str] = Field(None, validation_alias="STRIPE_WEBHOOK_SECRET")

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