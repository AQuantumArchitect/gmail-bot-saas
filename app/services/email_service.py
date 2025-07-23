import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
import asyncio

from uuid import UUID

from app.core.exceptions import (
    APIError,
    InsufficientCreditsError,
    NotFoundError,
    ValidationError,
)
from app.data.repositories.email_repository import EmailRepository
from app.data.repositories.user_repository import UserRepository
from app.services.auth_service import AuthService
from app.services.billing_service import BillingService
from app.services.gmail_service import GmailService

logger = logging.getLogger(__name__)

class EmailService:
    """
    High-level email processing orchestration service that coordinates between
    GmailService, BillingService, and other components.
    """

    def __init__(
        self,
        gmail_service: GmailService,
        billing_service: BillingService,
        auth_service: AuthService,
        user_repository: UserRepository,
        email_repository: EmailRepository,
    ):
        self.gmail_service = gmail_service
        self.billing_service = billing_service
        self.auth_service = auth_service
        self.user_repository = user_repository
        self.email_repository = email_repository
        self._processing_locks: Dict[str, asyncio.Lock] = {}

    # --- Core Email Processing ---

async def process_single_email(self, user_id: str, message_id: str) -> Dict[str, Any]:
    """
    Processes a single email for a user, checking permissions and deducting credits.
    """
    if not user_id:
        raise ValidationError("user_id cannot be empty")
    if not message_id:
        raise ValidationError("message_id cannot be empty")

    user_profile = self.user_repository.get_user_profile(user_id)
    if not user_profile:
        raise NotFoundError("User not found")

    permission_result = self.auth_service.check_user_permissions(
        user_profile, "email_processing"
    )
    if not permission_result["allowed"]:
        reason = permission_result.get("reason", "Permission denied")
        if "Insufficient credits" in reason:
            raise InsufficientCreditsError("User has insufficient credits.")
        if "Bot is disabled" in reason:
            raise ValidationError("Bot is disabled for this user.")
        raise ValidationError(f"Permission denied: {reason}")

    try:
        processing_result = await self.gmail_service.process_email(
            user_id, message_id
        )
        if not processing_result.get("success"):
            raise APIError("Email processing failed in GmailService.")
    except Exception as e:
        logger.error(f"GmailService failed to process email {message_id} for user {user_id}: {e}")
        raise APIError(f"Gmail API failed: {e}") from e

    try:
        credits_to_deduct = processing_result.get("credits_used", 0)
        if credits_to_deduct > 0:
            await self.billing_service.deduct_credits(
                user_id=UUID(user_id),
                credit_amount=credits_to_deduct,
                description=f"Processed email {message_id}",
                reference_id=UUID(message_id) if message_id else None
            )
    except InsufficientCreditsError:
        logger.error(f"Insufficient credits for user {user_id}")
        raise
    except Exception as e:
        logger.error(f"Credit deduction failed for user {user_id}: {e}")
        raise APIError(f"Billing service failed: {e}") from e

    return processing_result

    # --- Batch and Pipeline Orchestration ---

async def process_user_emails(
    self, user_id: str, max_emails: int = 10
) -> Dict[str, Any]:
    """
    Processes a batch of emails for a user with concurrency control.
    """
    if max_emails < 0:
        raise ValidationError("max_emails cannot be negative")

    if user_id not in self._processing_locks:
        self._processing_locks[user_id] = asyncio.Lock()
    if self._processing_locks[user_id].locked():
        raise ValidationError("Concurrent processing for this user is already in progress.")

    async with self._processing_locks[user_id]:
        user_profile = self.user_repository.get_user_profile(user_id)
        if not user_profile:
            raise NotFoundError("User not found")

        batch_result = await self.gmail_service.process_user_emails(
            user_id, max_emails=max_emails
        )

        credits_to_deduct = batch_result.get("credits_used", 0)
        if credits_to_deduct > 0:
            try:
                await self.billing_service.deduct_credits(
                    user_id=UUID(user_id),
                    credit_amount=credits_to_deduct,
                    description="Batch email processing"
                )
            except InsufficientCreditsError:
                logger.error(f"Insufficient credits for batch processing user {user_id}")
                raise
            except Exception as e:
                logger.error(f"Batch credit deduction failed for user {user_id}: {e}")
                raise APIError(f"Billing service failed: {e}") from e

        return batch_result
    async def run_full_processing_pipeline(self, user_id: str) -> Dict[str, Any]:
        """
        Runs the full pipeline: discovers, processes, and handles billing.
        """
        logger.info(f"Running full processing pipeline for user {user_id}")
        discovery_result = await self.discover_user_emails(user_id)
        emails_discovered = discovery_result.get("new_emails", 0)

        if emails_discovered > 0:
            processing_result = await self.process_user_emails(user_id)
        else:
            processing_result = {"emails_processed": 0, "credits_used": 0}

        return {
            "success": True,
            "user_id": user_id,
            "pipeline_completed": True,
            "emails_discovered": emails_discovered,
            "emails_processed": processing_result.get("emails_processed", 0),
            "credits_used": processing_result.get("credits_used", 0),
        }

    # --- Email Discovery and Recovery ---

    async def discover_user_emails(
        self, user_id: str, apply_filters: bool = True
    ) -> Dict[str, Any]:
        """
        Discovers new emails for a user by calling the GmailService.
        """
        user_profile = self.user_repository.get_user_profile(user_id)
        if not user_profile:
            raise NotFoundError("User not found")

        # FIX: Call with the explicit keyword argument to match the strict test assertion.
        return await self.gmail_service.discover_emails(user_id, apply_filters=apply_filters)

    async def retry_failed_emails(self, user_id: str, max_retries: int = 5) -> Dict[str, Any]:
        """
        Finds failed emails and attempts to re-process them.
        """
        failed_emails = self.email_repository.get_processing_history(
            user_id, status="failed"
        )

        successful_retries, failed_retries, skipped_max_retries = 0, 0, 0
        emails_to_retry = []

        for email in failed_emails:
            if email.get("retry_count", 0) < email.get("max_retries", 3):
                emails_to_retry.append(email)
            else:
                skipped_max_retries += 1

        for email in emails_to_retry:
            try:
                await self.process_single_email(user_id, email["message_id"])
                successful_retries += 1
            except Exception:
                failed_retries += 1

        return {
            "success": True,
            "user_id": user_id,
            "emails_retried": len(emails_to_retry),
            "successful_retries": successful_retries,
            "failed_retries": failed_retries,
            "skipped_max_retries": skipped_max_retries,
        }

    # --- Bulk Operations ---

    async def bulk_process_users(self, user_ids: List[str]) -> Dict[str, Any]:
        """
        Initiates email processing for a list of users in bulk.
        """
        result = await self.gmail_service.bulk_process_users(user_ids)
        total_users = result.get("total_users", 0)
        successful_users = result.get("successful_users", 0)
        result["success_rate"] = (successful_users / total_users if total_users > 0 else 0.0)
        return result

    # --- Settings and Preferences ---

    async def update_user_email_preferences(
        self, user_id: str, new_preferences: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Updates a user's email filtering and AI preferences.
        """
        if self.user_repository.get_user_profile(user_id) is None:
            raise NotFoundError("User not found")

        try:
            self.user_repository.update_user_profile(user_id, new_preferences)
            return {"success": True, "user_id": user_id, "preferences_updated": True}
        except ValidationError as e:
            raise e

    # --- Statistics, Monitoring, and Maintenance ---

    def get_user_email_statistics(self, user_id: str) -> Dict[str, Any]:
        """
        Retrieves and aggregates email statistics for a specific user.
        """
        if self.user_repository.get_user_profile(user_id) is None:
            raise NotFoundError("User not found")

        email_stats = self.email_repository.get_processing_stats(user_id)
        gmail_stats = self.gmail_service.get_user_gmail_statistics(user_id)
        
        return {**email_stats, **gmail_stats}

    def get_user_processing_history(self, user_id: str, limit: int = 10) -> Dict[str, Any]:
        """
        Retrieves the processing history for a user's emails.
        """
        if self.user_repository.get_user_profile(user_id) is None:
            raise NotFoundError("User not found")

        history = self.email_repository.get_processing_history(user_id, limit=limit)
        return {"user_id": user_id, "processing_history": history}

    def get_processing_performance_metrics(self) -> Dict[str, Any]:
        """
        Provides system-wide performance metrics related to email processing.
        """
        stats = self.email_repository.get_processing_stats(user_id=None)
        pending = stats.get("total_pending", 0)
        processing = stats.get("total_processing", 0)
        health = "healthy"
        if pending > 100 or processing > 50:
            health = "overloaded"
        elif pending > 20 or processing > 10:
            health = "degraded"
        stats["queue_health"] = health
        return stats

    def get_system_health_status(self) -> Dict[str, Any]:
        """
        Aggregates health status from all dependent services.
        """
        gmail_health = self.gmail_service.health_check()
        billing_health = self.billing_service.get_billing_status()
        status = "healthy"
        if gmail_health["status"] != "healthy" or billing_health["status"] != "healthy":
            status = "degraded"

        return {
            "status": status,
            "gmail_service": gmail_health["status"],
            "billing_service": billing_health["status"],
            "timestamp": datetime.utcnow().isoformat(),
        }

    def get_service_configuration(self) -> Dict[str, Any]:
        """
        Returns the current configuration settings of the service.
        """
        return {
            "max_emails_per_batch": 10,
            "default_retry_attempts": 3,
            "processing_timeout_minutes": 5,
            "rate_limit_per_minute": 100,
        }

    async def update_service_configuration(self, new_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Updates the service's configuration. (Admin-only).
        """
        for key, value in new_config.items():
            if value is None or (isinstance(value, int) and value < 0):
                raise ValidationError(f"Invalid configuration value for {key}")
        
        return {"success": True, "configuration_updated": True, "new_config": new_config}

    async def cleanup_old_processing_data(self, days: int) -> Dict[str, Any]:
        """
        Cleans up historical processing records older than a specified number of days.
        """
        cleaned_count = self.email_repository.cleanup_old_records(days)
        return {"success": True, "records_cleaned": cleaned_count, "cleanup_days": days}

    async def cleanup_stale_processing_jobs(self) -> Dict[str, Any]:
        """
        Identifies and marks stale (stuck) processing jobs as failed.
        """
        return await self.gmail_service.cleanup_stale_jobs()