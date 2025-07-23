# app/services/user_service.py
"""
User Service - Simple user management for email summary bot.

Handles:
- User profile management
- Email preferences (filters, AI settings)
- Credit balance queries
- Bot enable/disable
- Basic dashboard data
"""
import logging
from uuid import UUID
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta

from app.core.exceptions import ValidationError, NotFoundError
from app.data.repositories.user_repository import UserRepository
from app.data.repositories.email_repository import EmailRepository
from app.data.repositories.gmail_repository import GmailRepository
from app.services.billing_service import BillingService

logger = logging.getLogger(__name__)


class UserService:
    """
    Simple user service for email bot - focused on core user needs.
    """
    
    def __init__(
        self,
        user_repository: UserRepository,
        billing_service: BillingService,
        email_repository: EmailRepository,
        gmail_repository: GmailRepository
    ):
        self.user_repository = user_repository
        self.billing_service = billing_service
        self.email_repository = email_repository
        self.gmail_repository = gmail_repository
        
        # Default preferences
        self.default_email_filters = {
            "exclude_senders": [],
            "exclude_domains": ["noreply@", "no-reply@"],
            "include_keywords": [],
            "exclude_keywords": ["unsubscribe", "marketing"],
            "min_email_length": 100,
            "max_emails_per_batch": 5
        }
        
        self.default_ai_preferences = {
            "summary_style": "concise",
            "summary_length": "medium",
            "include_action_items": True,
            "include_sentiment": False,
            "language": "en"
        }
    
    # --- Core User Profile Management ---
    
    async def get_user_profile(self, user_id: str) -> Dict[str, Any]:
        """Get user profile"""
        if not user_id:
            raise ValidationError("user_id cannot be empty")
        
        profile = self.user_repository.get_user_profile(user_id)
        if not profile:
            raise NotFoundError(f"User profile {user_id} not found")
        
        return profile
    
    async def create_user_profile(self, user_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create new user profile with defaults"""
        # Validate required fields
        if not user_data.get("user_id"):
            raise ValidationError("user_id is required")
        
        if not user_data.get("email"):
            raise ValidationError("email is required")
        
        # Validate email format
        import re
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, user_data["email"]):
            raise ValidationError("Invalid email format")
        
        # Apply defaults
        profile_data = {
            "user_id": user_data["user_id"],
            "email": user_data["email"],
            "display_name": user_data.get("display_name"),
            "timezone": user_data.get("timezone", "UTC"),
            "email_filters": user_data.get("email_filters", self.default_email_filters),
            "ai_preferences": user_data.get("ai_preferences", self.default_ai_preferences),
            "credits_remaining": user_data.get("credits_remaining", 5),  # Starter credits
            "bot_enabled": user_data.get("bot_enabled", True),
            "processing_frequency": user_data.get("processing_frequency", "15min")
        }
        
        return self.user_repository.create_user_profile(profile_data)
    
    async def update_user_profile(self, user_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Update user profile"""
        # Verify user exists
        await self.get_user_profile(user_id)
        
        # Validate updates
        readonly_fields = {"user_id", "created_at"}
        for field in readonly_fields:
            if field in updates:
                raise ValidationError(f"Cannot update readonly field: {field}")
        
        return self.user_repository.update_user_profile(user_id, updates)
    
    async def delete_user_profile(self, user_id: str) -> Dict[str, Any]:
        """Delete user profile and cleanup data"""
        # Verify user exists
        await self.get_user_profile(user_id)
        
        # Delete data
        user_deleted = self.user_repository.delete_user_profile(user_id)
        emails_cleaned = self.email_repository.delete_user_email_data(user_id)
        gmail_cleaned = self.gmail_repository.cleanup_user_connections(user_id)
        
        return {
            "success": user_deleted,
            "user_id": user_id,
            "data_cleaned": True,
            "emails_cleaned": emails_cleaned,
            "gmail_cleaned": gmail_cleaned,
            "deleted_at": datetime.now().isoformat()
        }
    
    # --- User Preferences ---
    
    async def get_user_preferences(self, user_id: str) -> Dict[str, Any]:
        """Get user email and AI preferences"""
        profile = await self.get_user_profile(user_id)
        
        return {
            "user_id": user_id,
            "email_filters": profile.get("email_filters", self.default_email_filters),
            "ai_preferences": profile.get("ai_preferences", self.default_ai_preferences),
            "processing_frequency": profile.get("processing_frequency", "15min")
        }
    
    async def update_email_filters(self, user_id: str, filters: Dict[str, Any]) -> Dict[str, Any]:
        """Update email filters"""
        # Basic validation
        if "min_email_length" in filters:
            if not isinstance(filters["min_email_length"], int) or filters["min_email_length"] < 0:
                raise ValidationError("min_email_length must be a non-negative integer")
        
        profile = await self.update_user_profile(user_id, {"email_filters": filters})
        
        return {
            "success": True,
            "user_id": user_id,
            "email_filters": profile["email_filters"]
        }
    
    async def update_ai_preferences(self, user_id: str, preferences: Dict[str, Any]) -> Dict[str, Any]:
        """Update AI preferences"""
        # Basic validation
        if "summary_style" in preferences:
            valid_styles = ["concise", "detailed", "bullet_points"]
            if preferences["summary_style"] not in valid_styles:
                raise ValidationError(f"Invalid summary_style. Must be one of: {valid_styles}")
        
        profile = await self.update_user_profile(user_id, {"ai_preferences": preferences})
        
        return {
            "success": True,
            "user_id": user_id,
            "ai_preferences": profile["ai_preferences"]
        }
    
    async def reset_preferences_to_default(self, user_id: str) -> Dict[str, Any]:
        """Reset preferences to defaults"""
        updates = {
            "email_filters": self.default_email_filters,
            "ai_preferences": self.default_ai_preferences,
            "processing_frequency": "15min"
        }
        
        profile = await self.update_user_profile(user_id, updates)
        
        return {
            "success": True,
            "user_id": user_id,
            "preferences_reset": True
        }
    
    # --- Simple Settings ---
    
    async def update_timezone(self, user_id: str, timezone: str) -> Dict[str, Any]:
        """Update user timezone"""
        # Basic timezone validation
        valid_timezones = [
            "UTC", "America/New_York", "America/Los_Angeles", "America/Chicago",
            "Europe/London", "Europe/Paris", "Europe/Berlin", "Asia/Tokyo"
        ]
        
        if timezone not in valid_timezones:
            raise ValidationError(f"Invalid timezone. Must be one of: {valid_timezones}")
        
        profile = await self.update_user_profile(user_id, {"timezone": timezone})
        
        return {
            "success": True,
            "user_id": user_id,
            "timezone": profile["timezone"]
        }
    
    # --- Credit Management ---
    
    async def get_credit_balance(self, user_id: str) -> Dict[str, Any]:
        """Get user's current credit balance using new billing service"""
        try:
            balance = await self.billing_service.get_credit_balance(UUID(user_id))
            return {
                "credits_remaining": balance.credits_remaining,
                "last_updated": balance.last_updated.isoformat()
            }
        except Exception as e:
            logger.error(f"Failed to get credit balance for {user_id}: {e}")
            raise
    
    async def get_credit_history(self, user_id: str, limit: int = 50) -> Dict[str, Any]:
        """Get user's credit transaction history using new billing service"""
        try:
            history = await self.billing_service.get_billing_history(UUID(user_id), limit)
            return {
                "transactions": [
                    {
                        "id": str(txn.id),
                        "transaction_type": txn.transaction_type,
                        "credit_amount": txn.credit_amount,
                        "credit_balance_after": txn.credit_balance_after,
                        "description": txn.description,
                        "usd_amount": txn.usd_amount,
                        "created_at": txn.created_at.isoformat(),
                        "metadata": txn.metadata
                    }
                    for txn in history.transactions
                ],
                "total_transactions": history.total_transactions
            }
        except Exception as e:
            logger.error(f"Failed to get credit history for {user_id}: {e}")
            raise
    
    async def check_sufficient_credits(self, user_id: str, required: int) -> bool:
        """Check if user has enough credits"""
        profile = await self.get_user_profile(user_id)
        current_balance = profile.get("credits_remaining", 0)
        return current_balance >= required
    
    # --- Bot Management ---
    
    async def enable_bot(self, user_id: str) -> Dict[str, Any]:
        """Enable user's bot"""
        profile = await self.update_user_profile(user_id, {"bot_enabled": True})
        
        return {
            "success": True,
            "user_id": user_id,
            "bot_enabled": True
        }
    
    async def disable_bot(self, user_id: str) -> Dict[str, Any]:
        """Disable user's bot"""
        profile = await self.update_user_profile(user_id, {"bot_enabled": False})
        
        return {
            "success": True,
            "user_id": user_id,
            "bot_enabled": False
        }
    
    async def get_bot_status(self, user_id: str) -> Dict[str, Any]:
        """Get simple bot status"""
        profile = await self.get_user_profile(user_id)
        
        # Check Gmail connection
        gmail_connection = self.gmail_repository.get_connection_info(user_id)
        gmail_connected = gmail_connection is not None and gmail_connection.get("connection_status") == "connected"
        
        # Simple status logic
        bot_enabled = profile.get("bot_enabled", False)
        credits_remaining = profile.get("credits_remaining", 0)
        
        if not bot_enabled:
            status = "disabled"
        elif not gmail_connected:
            status = "no_gmail"
        elif credits_remaining <= 0:
            status = "no_credits"
        else:
            status = "active"
        
        return {
            "user_id": user_id,
            "bot_enabled": bot_enabled,
            "gmail_connected": gmail_connected,
            "credits_remaining": credits_remaining,
            "status": status,
            "processing_frequency": profile.get("processing_frequency", "15min")
        }
    
    async def update_processing_frequency(self, user_id: str, frequency: str) -> Dict[str, Any]:
        """Update how often emails are processed"""
        valid_frequencies = ["15min", "30min", "1h", "2h", "4h", "daily"]
        if frequency not in valid_frequencies:
            raise ValidationError(f"Invalid frequency. Must be one of: {valid_frequencies}")
        
        profile = await self.update_user_profile(user_id, {"processing_frequency": frequency})
        
        return {
            "success": True,
            "user_id": user_id,
            "processing_frequency": frequency
        }
    
    # --- Simple Dashboard Data ---
    
    async def get_dashboard_data(self, user_id: str) -> Dict[str, Any]:
        """Get basic dashboard data - everything a user needs to see"""
        # Get user profile
        profile = await self.get_user_profile(user_id)
        
        # Get bot status
        bot_status = await self.get_bot_status(user_id)
        
        # Get basic stats
        email_stats = self.email_repository.get_processing_stats(user_id)
        
        # Get recent transactions
        recent_transactions = await self.get_credit_history(user_id, limit=5)
        
        return {
            "user_id": user_id,
            "timestamp": datetime.now().isoformat(),
            "user_profile": {
                "display_name": profile.get("display_name"),
                "email": profile.get("email"),
                "timezone": profile.get("timezone"),
                "created_at": profile.get("created_at")
            },
            "bot_status": bot_status,
            "credits": {
                "remaining": profile.get("credits_remaining", 0),
                "recent_transactions": recent_transactions["transactions"]
            },
            "email_stats": {
                "total_processed": email_stats.get("total_processed", 0),
                "total_successful": email_stats.get("total_successful", 0),
                "success_rate": email_stats.get("success_rate", 0.0)
            }
        }
    
    async def get_user_statistics(self, user_id: str) -> Dict[str, Any]:
        """Get simple user statistics"""
        # Verify user exists
        await self.get_user_profile(user_id)
        
        # Get stats
        stats = self.email_repository.get_processing_stats(user_id)
        
        return {
            "user_id": user_id,
            "total_emails_processed": stats.get("total_processed", 0),
            "successful_emails": stats.get("total_successful", 0),
            "failed_emails": stats.get("total_failed", 0),
            "success_rate": stats.get("success_rate", 0.0),
            "credits_used": stats.get("total_credits_used", 0)
        }
    
    # --- Simple Lifecycle ---
    
    async def suspend_user(self, user_id: str, reason: str) -> Dict[str, Any]:
        """Suspend user account"""
        profile = await self.update_user_profile(user_id, {
            "status": "suspended",
            "bot_enabled": False,
            "suspension_reason": reason
        })
        
        return {
            "success": True,
            "user_id": user_id,
            "status": "suspended",
            "reason": reason
        }
    
    async def reactivate_user(self, user_id: str) -> Dict[str, Any]:
        """Reactivate user account"""
        profile = await self.update_user_profile(user_id, {
            "status": "active",
            "suspension_reason": None
        })
        
        return {
            "success": True,
            "user_id": user_id,
            "status": "active"
        }