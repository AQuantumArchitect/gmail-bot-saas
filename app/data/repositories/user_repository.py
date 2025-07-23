from datetime import datetime
from typing import Optional, Dict, Any

from app.core.exceptions import ValidationError, NotFoundError


class UserRepository:
    """
    Repository for user_profiles table CRUD operations.
    Works with user_profiles that references auth.users(id) from Supabase.
    """
    
    def __init__(self):
        # Internal storage: user_id -> user_profile dict
        self._user_profiles: Dict[str, Dict[str, Any]] = {}

    def get_user_profile(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user profile by user_id (from auth.users)."""
        profile = self._user_profiles.get(user_id)
        return profile.copy() if profile else None

    def create_user_profile(self, user_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a user profile. user_id should be from auth.users(id)."""
        user_id = user_data.get("user_id")
        if not user_id:
            raise ValidationError("user_id is required")
        
        if user_id in self._user_profiles:
            raise ValidationError("User profile already exists")

        # Create user profile matching database schema
        now = datetime.utcnow().isoformat()
        profile = {
            "user_id": user_id,
            "email": user_data.get("email"),
            "display_name": user_data.get("display_name"),
            "timezone": user_data.get("timezone", "UTC"),
            "email_filters": user_data.get("email_filters", {
                "exclude_senders": [],
                "exclude_domains": ["noreply@", "no-reply@"],
                "include_keywords": [],
                "exclude_keywords": ["unsubscribe", "marketing"],
                "min_email_length": 100,
                "max_emails_per_batch": 5
            }),
            "ai_preferences": user_data.get("ai_preferences", {
                "summary_style": "concise",
                "summary_length": "medium",
                "include_action_items": True,
                "include_sentiment": False,
                "language": "en"
            }),
            "credits_remaining": user_data.get("credits_remaining", 5),
            "bot_enabled": user_data.get("bot_enabled", True),
            "created_at": now,
            "updated_at": now,
        }
        
        self._user_profiles[user_id] = profile
        return profile.copy()

    def update_user_profile(self, user_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Update user profile."""
        profile = self._user_profiles.get(user_id)
        if not profile:
            raise NotFoundError(f"User profile {user_id} not found")
        
        # Prevent updates to readonly fields
        readonly = {"user_id", "created_at"}
        for field in updates:
            if field in readonly:
                raise ValidationError(f"Readonly field '{field}' cannot be updated")
        
        # Apply updates
        for field, value in updates.items():
            profile[field] = value
        
        profile["updated_at"] = datetime.utcnow().isoformat()
        return profile.copy()

    def delete_user_profile(self, user_id: str) -> bool:
        """Delete user profile."""
        profile = self._user_profiles.pop(user_id, None)
        return profile is not None

    def count_user_profiles(self) -> int:
        """Count total user profiles."""
        return len(self._user_profiles)

    def user_profile_exists(self, user_id: str) -> bool:
        """Check if user profile exists."""
        return user_id in self._user_profiles

    def add_credits(self, user_id: str, amount: int, description: str) -> Dict[str, Any]:
        """Add credits to a user's account."""
        if amount <= 0:
            raise ValidationError("amount must be positive")
        if not description:
            raise ValidationError("description is required")

        profile = self._user_profiles.get(user_id)
        if not profile:
            raise NotFoundError(f"User profile {user_id} not found")

        profile["credits_remaining"] = profile.get("credits_remaining", 0) + amount
        profile["updated_at"] = datetime.utcnow().isoformat()
        # Optionally log description somewhere
        return profile.copy()

    def deduct_credits(self, user_id: str, amount: int, description: str) -> Dict[str, Any]:
        """Deduct credits from a user's account, raising if insufficient."""
        if amount <= 0:
            raise ValidationError("amount must be positive")
        if not description:
            raise ValidationError("description is required")

        profile = self._user_profiles.get(user_id)
        if not profile:
            raise NotFoundError(f"User profile {user_id} not found")

        balance = profile.get("credits_remaining", 0)
        if amount > balance:
            raise ValidationError(f"insufficient credits: balance {balance}, requested {amount}")

        profile["credits_remaining"] = balance - amount
        profile["updated_at"] = datetime.utcnow().isoformat()
        # Optionally log description somewhere
        return profile.copy()
