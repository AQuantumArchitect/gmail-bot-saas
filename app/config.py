import os
import secrets
from datetime import datetime
from typing import Optional, List, Dict, Any

from pydantic import Field, AnyHttpUrl, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # This is the modern Pydantic v2 way to configure settings loading.
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        validate_default=True,
        extra="ignore" # Ignore extra fields from environment variables
    )

    # Database
    database_url: AnyHttpUrl = Field(..., env=["DATABASE_URL", "SUPABASE_URL"])
    database_key: str = Field(..., env=["DATABASE_KEY", "SUPABASE_KEY"])
    database_service_key: str = Field(..., env=["DATABASE_SERVICE_KEY", "SUPABASE_SERVICE_KEY"])
    database_jwt_secret: str = Field(..., env=["DATABASE_JWT_SECRET", "SUPABASE_JWT_SECRET"])

    # OAuth
    google_client_id: str = Field(..., env=["GOOGLE_CLIENT_ID", "GMAIL_CLIENT_ID"])
    google_client_secret: str = Field(..., env=["GOOGLE_CLIENT_SECRET", "GMAIL_CLIENT_SECRET"])

    # API Keys
    anthropic_api_key: str = Field(..., env=["ANTHROPIC_API_KEY"])

    # Web
    webapp_url: AnyHttpUrl = Field(..., env=["WEBAPP_URL"])
    redirect_uri: AnyHttpUrl = Field(..., env=["REDIRECT_URI"])

    # Security
    state_secret_key: Optional[str] = Field(None, env=["STATE_SECRET_KEY"])
    vault_passphrase: str = Field(..., env=["VAULT_PASSPHRASE"])

    # Environment
    environment: str = Field("development", env=["ENVIRONMENT"])
    debug_mode: bool = Field(False, env=["DEBUG_MODE"])
    pytest_running: bool = Field(False, env=["PYTEST_RUNNING"])
    testing_mode: bool = Field(False, env=["TESTING_MODE"])

    # Feature flags
    enable_stripe: bool = Field(False, env=["ENABLE_STRIPE"])
    enable_background_processing: bool = Field(True, env=["ENABLE_BACKGROUND_PROCESSING"])
    enable_gmail_processing: bool = Field(True, env=["ENABLE_GMAIL_PROCESSING"])

    # Stripe
    stripe_secret_key: Optional[str] = Field(None, env=["STRIPE_SECRET_KEY"])
    stripe_webhook_secret: Optional[str] = Field(None, env=["STRIPE_WEBHOOK_SECRET"])


    @field_validator("google_client_id")
    def validate_google_client_id(cls, v: str) -> str:
        if not v.endswith('.apps.googleusercontent.com'):
            raise ValidationError('Invalid Google Client ID format')
        return v

    @field_validator("anthropic_api_key")
    def validate_anthropic_key(cls, v: str) -> str:
        if not v.startswith('sk-'):
            raise ValidationError('Invalid Anthropic API key')
        return v

    @model_validator(mode='after')
    def check_stripe_settings(self) -> 'Settings':
        # UPDATED: Validator now checks for both keys if Stripe is enabled
        if self.enable_stripe:
            if not self.stripe_secret_key:
                raise ValueError('STRIPE_SECRET_KEY is required when ENABLE_STRIPE is true')
            if not self.stripe_webhook_secret:
                raise ValueError('STRIPE_WEBHOOK_SECRET is required when ENABLE_STRIPE is true')
        return self

    @model_validator(mode='after')
    def generate_state_secret(self) -> 'Settings':
        state_key = self.state_secret_key
        debug = self.debug_mode
        if debug and not state_key:
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
