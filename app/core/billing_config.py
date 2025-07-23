# app/core/billing_config.py
"""
Billing configuration management with injectable settings for SaaS billing system.
Handles credit packages, Stripe configuration, and billing-related settings.
"""
from dataclasses import dataclass
from typing import Dict, Optional
from app.core.config import settings

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

@dataclass 
class BillingConfig:
    """Configuration for billing system with all necessary settings"""
    stripe_secret_key: str
    stripe_webhook_secret: str
    stripe_publishable_key: str
    enable_stripe: bool
    portal_return_url: str
    credit_packages: Dict[str, CreditPackage]
    
    # Retry and timeout settings
    stripe_max_retries: int = 3
    stripe_timeout_seconds: int = 30
    stripe_retry_delay_seconds: int = 1
    
    # Rate limiting
    stripe_requests_per_second: int = 80
    
    @classmethod
    def from_settings(cls) -> "BillingConfig":
        """Create BillingConfig from application settings"""
        # Define credit packages
        packages = {
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
        if hasattr(settings, 'credit_packages') and settings.credit_packages:
            for key, pkg_data in settings.credit_packages.items():
                if key in packages:
                    packages[key] = CreditPackage(
                        key=key,
                        name=pkg_data.get("name", packages[key].name),
                        credits=pkg_data.get("credits", packages[key].credits),
                        price_cents=pkg_data.get("price_cents", packages[key].price_cents),
                        popular=pkg_data.get("popular", packages[key].popular)
                    )
        
        return cls(
            stripe_secret_key=settings.stripe_secret_key,
            stripe_webhook_secret=getattr(settings, 'stripe_webhook_secret', ''),
            stripe_publishable_key=getattr(settings, 'stripe_publishable_key', ''),
            enable_stripe=settings.enable_stripe,
            portal_return_url=f"{settings.webapp_url}/billing/return",
            credit_packages=packages,
            stripe_max_retries=getattr(settings, 'stripe_max_retries', 3),
            stripe_timeout_seconds=getattr(settings, 'stripe_timeout_seconds', 30),
            stripe_retry_delay_seconds=getattr(settings, 'stripe_retry_delay_seconds', 1),
            stripe_requests_per_second=getattr(settings, 'stripe_requests_per_second', 80)
        )
    
    def get_package_by_key(self, package_key: str) -> Optional[CreditPackage]:
        """Get a credit package by its key"""
        return self.credit_packages.get(package_key)
    
    def get_packages_with_savings(self) -> Dict[str, Dict]:
        """Get all packages with calculated savings percentages"""
        baseline = self.credit_packages.get("starter")
        if not baseline:
            return {key: {"package": pkg, "savings_percent": None} 
                   for key, pkg in self.credit_packages.items()}
        
        result = {}
        for key, package in self.credit_packages.items():
            savings = package.calculate_savings_percent(baseline)
            result[key] = {
                "package": package,
                "savings_percent": savings
            }
        
        return result
    
    def validate_configuration(self) -> bool:
        """Validate that all required configuration is present"""
        if self.enable_stripe:
            if not self.stripe_secret_key:
                raise ValueError("Stripe secret key is required when Stripe is enabled")
            if not self.stripe_webhook_secret:
                raise ValueError("Stripe webhook secret is required when Stripe is enabled")
        
        if not self.credit_packages:
            raise ValueError("At least one credit package must be configured")
        
        for key, package in self.credit_packages.items():
            if package.credits <= 0:
                raise ValueError(f"Package {key} must have positive credits")
            if package.price_cents <= 0:
                raise ValueError(f"Package {key} must have positive price")
        
        return True