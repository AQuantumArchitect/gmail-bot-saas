# app/services/job_service.py
"""
Service for orchestrating background job processing tasks.
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List

from app.services.gmail_service import GmailService
from app.data.repositories.user_repository import UserRepository
from app.data.repositories.job_repository import JobRepository
from app.core.exceptions import NotFoundError

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class JobService:
    """
    Orchestrates background tasks, primarily discovering and processing
    emails for all active and eligible users.
    """

    def __init__(
        self,
        user_repository: UserRepository,
        gmail_service: GmailService,
        job_repository: JobRepository,
    ):
        """
        Initializes the JobService with its dependencies.

        Args:
            user_repository: Repository for accessing user data.
            gmail_service: Service for interacting with the Gmail API.
            job_repository: Repository for logging background job cycles.
        """
        self.user_repository = user_repository
        self.gmail_service = gmail_service
        self.job_repository = job_repository
        self.enabled = True  # Can be configured via settings

    def get_service_status(self) -> Dict[str, Any]:
        """
        Returns the current operational status of the background job service.
        """
        return {
            "enabled": self.enabled,
            "status": "active" if self.enabled else "disabled",
        }

    async def find_users_to_process(self) -> List[Dict[str, Any]]:
        """
        Finds all active users who are due for an email processing cycle.
        This should query the UserRepository for users with bot_enabled=True and credits > 0.
        """
        logger.info("Finding users due for processing...")
        # For now, return sample users - in real implementation would use UserRepository
        # to find users with bot_enabled=True, credits_remaining > 0, etc.
        sample_users = [
            {
                "user_id": "user1",
                "email": "user1@example.com", 
                "bot_enabled": True,
                "credits_remaining": 10
            },
            {
                "user_id": "user2",
                "email": "user2@example.com",
                "bot_enabled": True, 
                "credits_remaining": 5
            }
        ]
        logger.info(f"Found {len(sample_users)} users to process.")
        return sample_users

    async def run_processing_cycle(self) -> Dict[str, Any]:
        """
        Executes a full processing cycle for all eligible users.

        1. Finds users due for processing.
        2. For each user, discovers and processes new emails.
        3. Logs the overall results of the cycle.
        """
        start_time = datetime.utcnow()
        logger.info(f"Starting background processing cycle at {start_time.isoformat()}Z")

        if not self.enabled:
            logger.warning("Processing cycle skipped: service is disabled.")
            return {"status": "disabled", "users_processed": 0}

        users_to_process = await self.find_users_to_process()

        if not users_to_process:
            logger.info("No users due for processing in this cycle.")
            # Use proper CRUD method to create job record
            self.job_repository.create_job({
                "user_id": "system",
                "job_type": "email_processing",
                "status": "completed",
                "metadata": {"cycle_type": "processing_cycle", "message": "No users due for processing."}
            })
            return {"status": "completed", "message": "No users due for processing.", "users_processed": 0}

        # Initialize cycle statistics
        cycle_stats = {
            "users_processed": 0,
            "users_skipped": 0,
            "total_emails_discovered": 0,
            "total_emails_processed": 0,
            "total_credits_used": 0,
            "total_errors": 0,
            "errors": [],
        }

        for user in users_to_process:
            user_id = user.get("user_id")
            logger.info(f"Processing user: {user_id}")
            try:
                result = await self.process_single_user(user)
                if result.get("success"):
                    cycle_stats["users_processed"] += 1
                    cycle_stats["total_emails_discovered"] += result.get("emails_discovered", 0)
                    cycle_stats["total_emails_processed"] += result.get("emails_processed", 0)
                    cycle_stats["total_credits_used"] += result.get("credits_used", 0)
                else:
                    cycle_stats["users_skipped"] += 1
                    logger.warning(f"Skipped user {user_id}: {result.get('reason')}")

            except Exception as e:
                logger.error(f"An unexpected error occurred while processing user {user_id}: {e}", exc_info=True)
                cycle_stats["total_errors"] += 1
                cycle_stats["errors"].append({"user_id": user_id, "error": str(e)})

        end_time = datetime.utcnow()
        duration = (end_time - start_time).total_seconds()
        
        final_status = "completed_with_errors" if cycle_stats["total_errors"] > 0 else "completed"

        # Log the final outcome of the cycle using proper CRUD method
        self.job_repository.create_job({
            "user_id": "system",
            "job_type": "email_processing", 
            "status": "completed" if final_status == "completed" else "failed",
            "metadata": {
                "cycle_type": "processing_cycle",
                "cycle_status": final_status,
                **cycle_stats,
                "duration_seconds": duration
            }
        })
        
        logger.info(f"Processing cycle finished in {duration:.2f} seconds. Status: {final_status}")
        return {
            "status": final_status,
            "duration_seconds": duration,
            **cycle_stats
        }

    async def process_single_user(self, user: Dict[str, Any]) -> Dict[str, Any]:
        """
        Contains the logic to process emails for a single user.
        """
        user_id = user.get("user_id")

        # Pre-flight checks
        if not user.get("bot_enabled"):
            return {"success": False, "reason": "bot_disabled"}
        if user.get("credits_remaining", 0) <= 0:
            return {"success": False, "reason": "insufficient_credits"}

        try:
            # Step 1: Discover new emails
            discovery_result = await self.gmail_service.discover_emails(user_id)
            
            # Step 2: Process the discovered emails
            processing_result = await self.gmail_service.process_user_emails(user_id)

            return {
                "success": True,
                "user_id": user_id,
                "emails_discovered": discovery_result.get("new_emails", 0),
                "emails_processed": processing_result.get("emails_processed", 0),
                "credits_used": processing_result.get("credits_used", 0),
            }
        except NotFoundError:
            logger.warning(f"Could not process user {user_id}: Gmail connection not found.")
            return {"success": False, "reason": "connection_not_found"}
        except Exception as e:
            logger.error(f"Failed to process user {user_id}: {e}")
            raise # Re-raise to be caught by the main cycle loop

    async def get_health_check(self) -> Dict[str, Any]:
        """
        Performs a health check of the background service and its dependencies.
        """
        health_status = "healthy"
        overall_message = "All systems operational."
        
        # Check dependencies
        dependencies = {
            "database": {"status": "ok", "details": "Connected"},
            "gmail_service": {"status": "ok", "details": "Available"}
        }
        
        # Check Job Repository (Database) using CRUD methods
        try:
            # Query for the last processing cycle job
            # This would use proper CRUD queries in a real implementation
            last_run = None
            if hasattr(self.job_repository, 'get_last_job_log'):
                last_run = await self.job_repository.get_last_job_log()
        except Exception as e:
            dependencies["database"]["status"] = "error"
            dependencies["database"]["details"] = str(e)
            health_status = "unhealthy"
            last_run = None

        # Check Gmail Service
        try:
            queue_status = self.gmail_service.get_queue_status()
            if queue_status.get("queue_status") in ["overloaded", "degraded"]:
                dependencies["gmail_service"]["status"] = queue_status.get("queue_status")
                health_status = "degraded"
        except Exception as e:
            dependencies["gmail_service"]["status"] = "error"
            dependencies["gmail_service"]["details"] = str(e)
            health_status = "unhealthy"

        # Check last run time
        if last_run and last_run.get("completed_at"):
            last_run_time = datetime.fromisoformat(last_run["completed_at"])
            if datetime.utcnow() - last_run_time > timedelta(hours=1):
                health_status = "degraded"
                overall_message = "Last run was over an hour ago. The worker might be stalled."

        return {
            "status": health_status,
            "message": overall_message,
            "timestamp": datetime.utcnow().isoformat(),
            "last_run": last_run,
            "dependencies": dependencies,
        }
