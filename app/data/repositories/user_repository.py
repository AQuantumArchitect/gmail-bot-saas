# app/data/repositories/user_repository.py
"""
ZERO COMPROMISE USER REPOSITORY - Rev 6
Perfect Supabase-native implementation for email bot SaaS.

PRINCIPLES:
- UserRepository manages ONLY user settings and preferences
- NEVER touches credits (that's BillingRepository's job)
- Always includes email (we're an email bot - users always have email)
- UUID-first architecture (no string user IDs anywhere)
- RLS context for all queries
- Pure separation of concerns
- In-memory fallback for testing

ARCHITECTURE:
- Maps to public.user_settings table (shadow metadata)
- Joins with auth.users for email when needed
- Supabase client for all database operations
- Domain models match reality (UserSettings, not UserProfile)
"""
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, asdict, field
from uuid import UUID, uuid4

from app.external.supabase_client import SupabaseClient
from app.core.exceptions import (
    ValidationError, 
    NotFoundError, 
    DatabaseError,
    UserProfileNotFoundError,
    UserProfileExistsError,
    InvalidTimezoneError
)

logger = logging.getLogger(__name__)


# ========== DOMAIN MODELS ==========

@dataclass
class EmailFilters:
    """Domain model for email filtering preferences"""
    exclude_senders: List[str] = field(default_factory=list)
    exclude_domains: List[str] = field(default_factory=lambda: ["noreply@", "no-reply@"])
    include_keywords: List[str] = field(default_factory=list)
    exclude_keywords: List[str] = field(default_factory=lambda: ["unsubscribe", "marketing"])
    min_email_length: int = 100
    max_emails_per_batch: int = 5

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EmailFilters":
        """Create EmailFilters from dictionary"""
        return cls(**data)

    def to_dict(self) -> Dict[str, Any]:
        """Convert EmailFilters to dictionary"""
        return asdict(self)


@dataclass
class AIPreferences:
    """Domain model for AI processing preferences"""
    summary_style: str = "concise"
    summary_length: str = "medium"
    include_action_items: bool = True
    include_sentiment: bool = False
    language: str = "en"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AIPreferences":
        """Create AIPreferences from dictionary"""
        return cls(**data)

    def to_dict(self) -> Dict[str, Any]:
        """Convert AIPreferences to dictionary"""
        return asdict(self)


@dataclass
class UserSettings:
    """
    ZERO COMPROMISE: Domain model for user settings and preferences.
    - No credits_remaining (BillingRepository owns that)
    - Always includes email (we're an email bot)
    - UUID-first architecture
    """
    user_id: UUID
    email: str  # Always present - we're an email bot!
    display_name: Optional[str]
    timezone: str
    bot_enabled: bool
    processing_frequency_minutes: int
    last_processed_at: Optional[datetime]
    email_filters: EmailFilters
    ai_preferences: AIPreferences
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserSettings":
        """Create UserSettings from dictionary"""
        # Create a copy to avoid mutating the original
        data = data.copy()
        
        # Handle UUID conversion
        if isinstance(data.get("user_id"), str):
            data["user_id"] = UUID(data["user_id"])
        
        # Handle datetime conversion - support both strings and datetime objects
        for field in ["created_at", "updated_at", "last_processed_at"]:
            if field in data and data[field] is not None:
                if isinstance(data[field], str):
                    # Parse string datetime
                    data[field] = datetime.fromisoformat(data[field].replace('Z', '+00:00'))
                elif not isinstance(data[field], datetime):
                    # If it's neither string nor datetime, set to None
                    data[field] = None

        # Handle nested objects
        if "email_filters" in data and isinstance(data["email_filters"], dict):
            data["email_filters"] = EmailFilters.from_dict(data["email_filters"])
        elif "email_filters" not in data:
            data["email_filters"] = EmailFilters()

        if "ai_preferences" in data and isinstance(data["ai_preferences"], dict):
            data["ai_preferences"] = AIPreferences.from_dict(data["ai_preferences"])
        elif "ai_preferences" not in data:
            data["ai_preferences"] = AIPreferences()

        return cls(**data)

    def to_dict(self) -> Dict[str, Any]:
        """Convert UserSettings to dictionary"""
        data = asdict(self)
        
        # Convert UUID to string for JSON serialization
        data["user_id"] = str(data["user_id"])
        
        # Convert datetime to ISO strings
        for field in ["created_at", "updated_at", "last_processed_at"]:
            if data[field]:
                data[field] = data[field].isoformat() if isinstance(data[field], datetime) else data[field]
        
        return data


@dataclass
class UserStatistics:
    """Domain model for user statistics"""
    total_users: int
    active_users: int
    inactive_users: int
    average_processing_frequency: float
    timezone_distribution: Dict[str, int]
    email_domain_distribution: Dict[str, int]

    @classmethod
    def from_user_settings(cls, users: List[UserSettings]) -> "UserStatistics":
        """Calculate statistics from user settings"""
        total_users = len(users)
        active_users = len([u for u in users if u.bot_enabled])
        inactive_users = total_users - active_users
        
        # Processing frequency distribution
        frequencies = [u.processing_frequency_minutes for u in users]
        avg_frequency = sum(frequencies) / len(frequencies) if frequencies else 0
        
        # Timezone distribution
        timezones = {}
        for user in users:
            tz = user.timezone or "Unknown"
            timezones[tz] = timezones.get(tz, 0) + 1
        
        # Email domain distribution
        domains = {}
        for user in users:
            if user.email and "@" in user.email:
                domain = user.email.split("@")[-1]
                domains[domain] = domains.get(domain, 0) + 1
        
        return cls(
            total_users=total_users,
            active_users=active_users,
            inactive_users=inactive_users,
            average_processing_frequency=round(avg_frequency, 2),
            timezone_distribution=timezones,
            email_domain_distribution=domains
        )


# ========== REPOSITORY ==========

class UserRepository:
    """
    ZERO COMPROMISE USER REPOSITORY
    
    Manages user settings and preferences ONLY.
    NEVER touches credits - that's BillingRepository's job.
    Always includes email - we're an email bot, users always have email.
    
    Architecture:
    - Production: Uses Supabase client with RLS
    - Testing: Pure in-memory storage
    - Maps to public.user_settings + auth.users (for email)
    - UUID-first everywhere
    """

    # Valid configuration values - enforced by database constraints too
    VALID_TIMEZONES = {
        "UTC", "US/Eastern", "US/Central", "US/Mountain", "US/Pacific",
        "Europe/London", "Europe/Paris", "Europe/Berlin", "Asia/Tokyo",
        "Asia/Shanghai", "Australia/Sydney"
    }
    VALID_SUMMARY_STYLES = {"concise", "detailed", "bullet_points"}
    VALID_SUMMARY_LENGTHS = {"short", "medium", "long"}
    VALID_LANGUAGES = {"en", "es", "fr", "de", "it", "pt", "ja", "zh"}

    def __init__(self, supabase_client: Optional[SupabaseClient] = None):
        """
        Initialize repository.
        
        Args:
            supabase_client: Supabase client for production, None for testing
        """
        if supabase_client:
            self.client = supabase_client
            self._use_database = True
        else:
            # Pure in-memory storage for testing
            self._user_settings: Dict[UUID, Dict[str, Any]] = {}
            self._use_database = False

    # ========== CREATE OPERATIONS ==========

    async def create_user_settings(self, user_data: Dict[str, Any]) -> UserSettings:
        """
        Create user settings.
        Core CREATE operation with validation and deduplication.
        
        Args:
            user_data: Dictionary with user_id (required) and optional settings
                      For testing: should include 'email' field
            
        Returns:
            UserSettings domain model
            
        Raises:
            ValidationError: Invalid data
            UserProfileExistsError: User already exists
            InvalidTimezoneError: Invalid timezone
        """
        # Validation
        user_id_raw = user_data.get("user_id")
        if not user_id_raw:
            raise ValidationError("user_id is required")

        # Convert to UUID
        try:
            user_id = UUID(user_id_raw) if isinstance(user_id_raw, str) else user_id_raw
        except (ValueError, TypeError):
            raise ValidationError("user_id must be a valid UUID")

        # Validate timezone
        timezone = user_data.get("timezone", "UTC")
        if timezone not in self.VALID_TIMEZONES:
            raise InvalidTimezoneError(timezone)

        # Validate AI preferences
        ai_prefs = user_data.get("ai_preferences", {})
        self._validate_ai_preferences(ai_prefs)

        # Check for duplicates
        existing = await self.get_user_settings(user_id)
        if existing:
            raise UserProfileExistsError(str(user_id))

        # Create settings with defaults - RESPECT INPUT DATA
        now = datetime.utcnow()
        settings_data = {
            "user_id": user_id,
            "display_name": user_data.get("display_name"),
            "timezone": timezone,
            "bot_enabled": user_data.get("bot_enabled", False),
            "processing_frequency_minutes": user_data.get("processing_frequency_minutes", 60),
            "last_processed_at": user_data.get("last_processed_at"),  # RESPECT PROVIDED VALUE
            "email_filters": user_data.get("email_filters", {}),
            "ai_preferences": ai_prefs,
            "created_at": user_data.get("created_at", now),  # RESPECT PROVIDED VALUE
            "updated_at": user_data.get("updated_at", now),  # RESPECT PROVIDED VALUE
        }

        if self._use_database:
            # Insert into user_settings table
            db_data = self._prepare_for_database(settings_data)
            response = await self.client.insert(
                table="user_settings",
                data=db_data,
                user_id=str(user_id)
            )
            
            if not response:
                raise DatabaseError("Failed to create user settings")
            
            # Get the created record with email
            created_settings = await self.get_user_settings(user_id)
            if not created_settings:
                raise DatabaseError("Failed to retrieve created user settings")
            
            logger.info(f"Created user settings for {user_id}")
            return created_settings
        else:
            # ZERO COMPROMISE: In-memory storage must behave EXACTLY like production
            # RESPECT the provided email - don't generate fake data!
            email = user_data.get("email")
            if not email:
                raise ValidationError("email is required for testing mode")
            
            settings_data["email"] = email  # RESPECT PROVIDED EMAIL
            self._user_settings[user_id] = settings_data
            user_settings = UserSettings.from_dict(settings_data)
            logger.info(f"Created user settings in memory for {user_id}")
            return user_settings

    async def create_bulk_user_settings(self, users_data: List[Dict[str, Any]]) -> List[UserSettings]:
        """
        Create multiple user settings in bulk.
        Skips invalid entries and continues processing.
        """
        results = []
        for user_data in users_data:
            try:
                user_settings = await self.create_user_settings(user_data)
                results.append(user_settings)
            except (ValidationError, UserProfileExistsError) as e:
                logger.warning(f"Failed to create user settings: {e}")
                continue
        return results

    # ========== READ OPERATIONS ==========

    async def get_user_settings(self, user_id: UUID) -> Optional[UserSettings]:
        """
        Get user settings by user_id.
        ALWAYS includes email (joins with auth.users).
        
        Args:
            user_id: User UUID
            
        Returns:
            UserSettings with email included, or None if not found
        """
        if self._use_database:
            # Join user_settings with auth.users to get email
            query = """
            SELECT 
                us.*,
                au.email
            FROM user_settings us
            JOIN auth.users au ON au.id = us.user_id
            WHERE us.user_id = $1
            """
            
            response = await self.client.execute_sql(
                query=query,
                params=[str(user_id)],
                user_id=str(user_id)
            )
            
            if not response or len(response) == 0:
                return None
            
            settings_data = response[0]
            return UserSettings.from_dict(settings_data)
        else:
            # In-memory storage
            if user_id not in self._user_settings:
                return None
            settings_data = self._user_settings[user_id].copy()
            return UserSettings.from_dict(settings_data)

    async def find_user_by_email(self, email: str) -> Optional[UserSettings]:
        """
        Find user by email address.
        Searches auth.users table and returns settings if found.
        
        Args:
            email: Email address to search for
            
        Returns:
            UserSettings for the user with that email, or None
        """
        if self._use_database:
            query = """
            SELECT 
                us.*,
                au.email
            FROM auth.users au
            JOIN user_settings us ON us.user_id = au.id
            WHERE LOWER(au.email) = LOWER($1)
            """
            
            response = await self.client.execute_sql(
                query=query,
                params=[email]
            )
            
            if not response or len(response) == 0:
                return None
            
            settings_data = response[0]
            return UserSettings.from_dict(settings_data)
        else:
            # In-memory storage - search by email
            for settings_data in self._user_settings.values():
                if settings_data.get("email", "").lower() == email.lower():
                    return UserSettings.from_dict(settings_data)
            return None

    async def list_user_settings(
        self,
        limit: Optional[int] = None,
        offset: int = 0,
        order_by: str = "created_at",
        descending: bool = False,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[UserSettings]:
        """
        List user settings with filtering, pagination, and sorting.
        ALWAYS includes email for each user.
        """
        if self._use_database:
            # Build query with join
            query = """
            SELECT 
                us.*,
                au.email
            FROM user_settings us
            JOIN auth.users au ON au.id = us.user_id
            WHERE 1=1
            """
            params = []
            param_count = 0
            
            # Apply filters
            if filters:
                if "bot_enabled" in filters:
                    param_count += 1
                    query += f" AND us.bot_enabled = ${param_count}"
                    params.append(filters["bot_enabled"])
                
                if "timezone" in filters:
                    param_count += 1
                    query += f" AND us.timezone = ${param_count}"
                    params.append(filters["timezone"])
                
                if "email_domain" in filters:
                    param_count += 1
                    query += f" AND au.email LIKE ${param_count}"
                    params.append(f"%@{filters['email_domain']}")
            
            # Add ordering
            order_direction = "DESC" if descending else "ASC"
            if order_by in ["created_at", "updated_at", "last_processed_at", "processing_frequency_minutes"]:
                query += f" ORDER BY us.{order_by} {order_direction}"
            elif order_by == "email":
                query += f" ORDER BY au.email {order_direction}"
            else:
                query += f" ORDER BY us.created_at {order_direction}"
            
            # Add pagination
            if limit:
                param_count += 1
                query += f" LIMIT ${param_count}"
                params.append(limit)
            
            if offset > 0:
                param_count += 1
                query += f" OFFSET ${param_count}"
                params.append(offset)
            
            response = await self.client.execute_sql(
                query=query,
                params=params
            )
            
            return [UserSettings.from_dict(data) for data in (response or [])]
        else:
            # In-memory storage with filtering
            all_settings = list(self._user_settings.values())
            
            # Apply filters
            if filters:
                if "bot_enabled" in filters:
                    all_settings = [s for s in all_settings if s.get("bot_enabled") == filters["bot_enabled"]]
                if "timezone" in filters:
                    all_settings = [s for s in all_settings if s.get("timezone") == filters["timezone"]]
                if "email_domain" in filters:
                    domain = filters["email_domain"]
                    all_settings = [s for s in all_settings if s.get("email", "").endswith(f"@{domain}")]
            
            # Sort
            reverse = descending
            if order_by == "email":
                all_settings.sort(key=lambda x: x.get("email", ""), reverse=reverse)
            elif order_by in ["created_at", "updated_at", "last_processed_at"]:
                all_settings.sort(key=lambda x: x.get(order_by) or datetime.min, reverse=reverse)
            else:
                all_settings.sort(key=lambda x: x.get(order_by, 0), reverse=reverse)
            
            # Paginate
            start = offset
            end = start + limit if limit else None
            paginated_settings = all_settings[start:end]
            
            return [UserSettings.from_dict(data) for data in paginated_settings]

    async def count_user_settings(self, filters: Optional[Dict[str, Any]] = None) -> int:
        """
        Count user settings with optional filtering.
        """
        if self._use_database:
            query = "SELECT COUNT(*) as count FROM user_settings us"
            params = []
            param_count = 0
            
            if filters:
                conditions = []
                if "bot_enabled" in filters:
                    param_count += 1
                    conditions.append(f"us.bot_enabled = ${param_count}")
                    params.append(filters["bot_enabled"])
                
                if "timezone" in filters:
                    param_count += 1
                    conditions.append(f"us.timezone = ${param_count}")
                    params.append(filters["timezone"])
                
                if conditions:
                    query += " WHERE " + " AND ".join(conditions)
            
            response = await self.client.execute_sql(
                query=query,
                params=params
            )
            
            return response[0]["count"] if response else 0
        else:
            # In-memory storage
            settings_list = await self.list_user_settings(filters=filters, limit=None)
            return len(settings_list)

    async def find_active_users(self) -> List[UserSettings]:
        """
        Find users with bot enabled.
        """
        return await self.list_user_settings(filters={"bot_enabled": True})

    async def find_users_due_for_processing(self) -> List[UserSettings]:
        """
        Find users who are due for email processing.
        Users where:
        - bot_enabled = true
        - last_processed_at is null OR last_processed_at + frequency < now
        """
        if self._use_database:
            query = """
            SELECT 
                us.*,
                au.email
            FROM user_settings us
            JOIN auth.users au ON au.id = us.user_id
            WHERE us.bot_enabled = true
            AND (
                us.last_processed_at IS NULL 
                OR us.last_processed_at + (us.processing_frequency_minutes || ' minutes')::interval < NOW()
            )
            ORDER BY us.last_processed_at ASC NULLS FIRST
            """
            
            response = await self.client.execute_sql(query=query, params=[])
            return [UserSettings.from_dict(data) for data in (response or [])]
        else:
            # ZERO COMPROMISE: In-memory logic must match database logic exactly
            now = datetime.utcnow()
            due_users = []
            
            for settings_data in self._user_settings.values():
                # Check bot_enabled first
                if not settings_data.get("bot_enabled", False):
                    continue
                
                last_processed = settings_data.get("last_processed_at")
                frequency_minutes = settings_data.get("processing_frequency_minutes", 60)
                
                # Handle both None and missing key cases
                if last_processed is None:
                    # Never processed - due now
                    due_users.append(UserSettings.from_dict(settings_data))
                    continue
                
                # Parse datetime if it's a string (consistent with from_dict logic)
                if isinstance(last_processed, str):
                    try:
                        last_processed = datetime.fromisoformat(last_processed.replace('Z', '+00:00'))
                    except (ValueError, AttributeError):
                        # If parsing fails, treat as due for processing
                        due_users.append(UserSettings.from_dict(settings_data))
                        continue
                
                # Check if enough time has passed
                if isinstance(last_processed, datetime):
                    next_processing_time = last_processed + timedelta(minutes=frequency_minutes)
                    if now >= next_processing_time:
                        due_users.append(UserSettings.from_dict(settings_data))
            
            # Sort by last_processed_at (nulls first) to match database behavior
            due_users.sort(key=lambda u: u.last_processed_at or datetime.min)
            return due_users

    # ========== UPDATE OPERATIONS ==========

    async def update_user_settings(self, user_id: UUID, updates: Dict[str, Any]) -> UserSettings:
        """
        Update user settings.
        Core UPDATE operation with validation.
        
        Args:
            user_id: User UUID
            updates: Dictionary of fields to update
            
        Returns:
            Updated UserSettings
            
        Raises:
            UserProfileNotFoundError: User not found
            ValidationError: Invalid update data
        """
        # Validate user exists
        existing = await self.get_user_settings(user_id)
        if not existing:
            raise UserProfileNotFoundError(str(user_id))

        # Validate updates
        if "timezone" in updates and updates["timezone"] not in self.VALID_TIMEZONES:
            raise InvalidTimezoneError(updates["timezone"])
        
        if "ai_preferences" in updates:
            self._validate_ai_preferences(updates["ai_preferences"])
        
        if "processing_frequency_minutes" in updates:
            freq = updates["processing_frequency_minutes"]
            if not isinstance(freq, int) or freq < 15 or freq > 240:
                raise ValidationError("processing_frequency_minutes must be between 15 and 240")

        # Add updated timestamp
        updates["updated_at"] = datetime.utcnow()

        if self._use_database:
            # Update in database
            db_updates = self._prepare_for_database(updates)
            
            response = await self.client.update(
                table="user_settings",
                data=db_updates,
                filters={"user_id": str(user_id)},
                user_id=str(user_id)
            )
            
            if not response:
                raise DatabaseError("Failed to update user settings")
            
            # Return updated settings
            updated_settings = await self.get_user_settings(user_id)
            if not updated_settings:
                raise DatabaseError("Failed to retrieve updated user settings")
            
            logger.info(f"Updated user settings for {user_id}")
            return updated_settings
        else:
            # In-memory storage
            if user_id not in self._user_settings:
                raise UserProfileNotFoundError(str(user_id))
            
            self._user_settings[user_id].update(updates)
            updated_data = self._user_settings[user_id].copy()
            logger.info(f"Updated user settings in memory for {user_id}")
            return UserSettings.from_dict(updated_data)

    async def update_last_processed(self, user_id: UUID, processed_at: Optional[datetime] = None) -> UserSettings:
        """
        Update the last processed timestamp for a user.
        Convenience method for email processing jobs.
        """
        if processed_at is None:
            processed_at = datetime.utcnow()
        
        return await self.update_user_settings(user_id, {"last_processed_at": processed_at})

    async def enable_bot(self, user_id: UUID) -> UserSettings:
        """Enable bot for user."""
        return await self.update_user_settings(user_id, {"bot_enabled": True})

    async def disable_bot(self, user_id: UUID) -> UserSettings:
        """Disable bot for user."""
        return await self.update_user_settings(user_id, {"bot_enabled": False})

    # ========== DELETE OPERATIONS ==========

    async def delete_user_settings(self, user_id: UUID) -> bool:
        """
        Delete user settings.
        
        Args:
            user_id: User UUID
            
        Returns:
            True if deleted, False if not found
        """
        if self._use_database:
            response = await self.client.delete(
                table="user_settings",
                filters={"user_id": str(user_id)},
                user_id=str(user_id)
            )
            
            success = bool(response)
            if success:
                logger.info(f"Deleted user settings for {user_id}")
            return success
        else:
            # In-memory storage
            if user_id in self._user_settings:
                del self._user_settings[user_id]
                logger.info(f"Deleted user settings from memory for {user_id}")
                return True
            return False

    # ========== ANALYTICS AND REPORTING ==========

    async def get_user_statistics(self) -> UserStatistics:
        """Get user statistics."""
        users = await self.list_user_settings(limit=None)
        return UserStatistics.from_user_settings(users)

    async def get_users_by_timezone(self, timezone: str) -> List[UserSettings]:
        """Get users in a specific timezone."""
        return await self.list_user_settings(filters={"timezone": timezone})

    # ========== HEALTH CHECK ==========

    async def health_check(self) -> Dict[str, Any]:
        """Perform health check on user repository."""
        try:
            if self._use_database:
                # Test database connectivity
                response = await self.client.select(
                    table="user_settings",
                    columns="user_id",
                    limit=1
                )
                
                return {
                    "healthy": True,
                    "storage_type": "supabase",
                    "timestamp": datetime.utcnow().isoformat(),
                    "valid_timezones": list(self.VALID_TIMEZONES),
                    "valid_summary_styles": list(self.VALID_SUMMARY_STYLES),
                    "valid_languages": list(self.VALID_LANGUAGES)
                }
            else:
                total_settings = len(self._user_settings)
                
                return {
                    "healthy": True,
                    "storage_type": "in_memory",
                    "total_settings": total_settings,
                    "timestamp": datetime.utcnow().isoformat(),
                    "valid_timezones": list(self.VALID_TIMEZONES),
                    "valid_summary_styles": list(self.VALID_SUMMARY_STYLES),
                    "valid_languages": list(self.VALID_LANGUAGES)
                }
                
        except Exception as e:
            logger.error(f"User repository health check failed: {e}")
            return {
                "healthy": False,
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }

    # ========== HELPER METHODS ==========

    def _validate_ai_preferences(self, ai_prefs: Dict[str, Any]) -> None:
        """Validate AI preferences dictionary."""
        if "summary_style" in ai_prefs and ai_prefs["summary_style"] not in self.VALID_SUMMARY_STYLES:
            raise ValidationError(f"Invalid summary_style: {ai_prefs['summary_style']}")
        
        if "summary_length" in ai_prefs and ai_prefs["summary_length"] not in self.VALID_SUMMARY_LENGTHS:
            raise ValidationError(f"Invalid summary_length: {ai_prefs['summary_length']}")
        
        if "language" in ai_prefs and ai_prefs["language"] not in self.VALID_LANGUAGES:
            raise ValidationError(f"Invalid language: {ai_prefs['language']}")

    def _prepare_for_database(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Prepare data for database insertion/update."""
        db_data = data.copy()
        
        # Convert UUID to string
        if "user_id" in db_data and isinstance(db_data["user_id"], UUID):
            db_data["user_id"] = str(db_data["user_id"])
        
        # Convert datetime to ISO string
        for field in ["created_at", "updated_at", "last_processed_at"]:
            if field in db_data and isinstance(db_data[field], datetime):
                db_data[field] = db_data[field].isoformat()
        
        # Ensure JSONB fields are dictionaries
        if "email_filters" in db_data and not isinstance(db_data["email_filters"], dict):
            if hasattr(db_data["email_filters"], 'to_dict'):
                db_data["email_filters"] = db_data["email_filters"].to_dict()
        
        if "ai_preferences" in db_data and not isinstance(db_data["ai_preferences"], dict):
            if hasattr(db_data["ai_preferences"], 'to_dict'):
                db_data["ai_preferences"] = db_data["ai_preferences"].to_dict()
        
        return db_data

    # ========== LEGACY COMPATIBILITY (for tests) ==========

    async def get_user_profile(self, user_id: UUID) -> Optional[UserSettings]:
        """Legacy method name - redirects to get_user_settings."""
        return await self.get_user_settings(user_id)

    async def create_user_profile(self, user_data: Dict[str, Any]) -> UserSettings:
        """Legacy method name - redirects to create_user_settings."""
        return await self.create_user_settings(user_data)

    async def update_user_profile(self, user_id: UUID, updates: Dict[str, Any]) -> UserSettings:
        """Legacy method name - redirects to update_user_settings."""
        return await self.update_user_settings(user_id, updates)

    async def delete_user_profile(self, user_id: UUID) -> bool:
        """Legacy method name - redirects to delete_user_settings."""
        return await self.delete_user_settings(user_id)


# ========== FACTORY METHODS ==========

def create_user_repository(env: str = "production") -> UserRepository:
    """
    Factory method for creating UserRepository.
    
    Args:
        env: Environment - "production" or "test"
        
    Returns:
        UserRepository instance
    """
    if env == "production":
        from app.external.supabase_client import SupabaseClient
        return UserRepository(supabase_client=SupabaseClient())
    else:
        # Testing mode - in-memory storage
        return UserRepository()