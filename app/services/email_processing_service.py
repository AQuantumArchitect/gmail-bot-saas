# app/services/email_processing_service.py
"""
EmailProcessingService - Business logic layer for email processing operations.
Orchestrates email discovery, processing, and state management.
All business logic extracted from EmailRepository.
"""
import logging
import asyncio
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from uuid import UUID

from app.core.exceptions import (
    ValidationError, 
    NotFoundError, 
    InsufficientCreditsError,
    APIError
)
from app.data.repositories.email_repository import (
    EmailRepository, 
    EmailRecord, 
    EmailStatus, 
    ProcessingStats,
    EmailRecordNotFoundError
)
from app.data.repositories.user_repository import UserRepository
from app.services.billing_service import BillingService

logger = logging.getLogger(__name__)


class EmailProcessingService:
    """
    Business logic layer for email processing operations.
    Handles email discovery, processing workflows, and state management.
    """
    
    def __init__(
        self,
        email_repository: EmailRepository,
        user_repository: UserRepository,
        billing_service: BillingService
    ):
        """Initialize service with required dependencies"""
        self.email_repository = email_repository
        self.user_repository = user_repository
        self.billing_service = billing_service
        
        # Processing locks to prevent concurrent processing
        self._processing_locks: Dict[str, asyncio.Lock] = {}

    # ========== EMAIL DISCOVERY OPERATIONS ==========

    async def mark_email_discovered(
        self,
        user_id: str,
        message_id: str,
        subject: str = "",
        sender: str = "",
        received_at: Optional[str] = None,
        discovery_method: str = "api_scan",
        filter_results: Optional[Dict[str, Any]] = None
    ) -> EmailRecord:
        """
        Mark email as discovered. Business logic: if exists, increment count.
        This is the business rule that was in the repository.
        """
        try:
            # Try to get existing record
            existing = await self.email_repository.get_email_record(user_id, message_id)
            
            if existing:
                # Business rule: Update existing record, increment discovery count
                return await self.email_repository.update_email_record(
                    user_id,
                    message_id,
                    discovery_count=existing.discovery_count + 1,
                    discovered_at=datetime.utcnow(),
                    metadata={**existing.metadata, **(filter_results or {})}
                )
            else:
                # Business rule: Create new record
                return await self.email_repository.create_email_record(
                    user_id=user_id,
                    message_id=message_id,
                    subject=subject,
                    sender=sender,
                    received_at=received_at,
                    discovery_method=discovery_method,
                    metadata=filter_results or {}
                )
                
        except Exception as e:
            logger.error(f"Failed to mark email as discovered {message_id} for user {user_id}: {e}")
            raise APIError(f"Email discovery failed: {str(e)}")

    async def discover_emails_for_user(
        self,
        user_id: str,
        gmail_service,  # Would be GmailService when implemented
        filters: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Discover new emails for a user using Gmail API.
        Business orchestration method.
        """
        try:
            # Get user profile for filtering preferences
            user_profile = await self.user_repository.get_user_profile(user_id)
            if not user_profile:
                raise NotFoundError(f"User profile not found: {user_id}")
            
            # Business rule: Check if user has bot enabled
            if not user_profile.bot_enabled:
                return {
                    "success": False,
                    "reason": "bot_disabled",
                    "discovered_count": 0
                }
            
            # Use Gmail service to get new emails (mock for now)
            discovered_emails = await self._get_new_emails_from_gmail(
                gmail_service, 
                user_profile.email, 
                filters or {}
            )
            
            # Mark each email as discovered
            discovered_count = 0
            for email_data in discovered_emails:
                try:
                    await self.mark_email_discovered(
                        user_id=user_id,
                        message_id=email_data["message_id"],
                        subject=email_data.get("subject", ""),
                        sender=email_data.get("sender", ""),
                        received_at=email_data.get("received_at"),
                        discovery_method="api_scan"
                    )
                    discovered_count += 1
                except Exception as e:
                    logger.warning(f"Failed to mark email {email_data['message_id']} as discovered: {e}")
                    continue
            
            logger.info(f"Discovered {discovered_count} emails for user {user_id}")
            return {
                "success": True,
                "discovered_count": discovered_count,
                "emails": discovered_emails
            }
            
        except Exception as e:
            logger.error(f"Email discovery failed for user {user_id}: {e}")
            raise APIError(f"Email discovery failed: {str(e)}")

    # ========== EMAIL PROCESSING STATE MACHINE ==========

    async def start_email_processing(
        self,
        user_id: str,
        message_id: str
    ) -> EmailRecord:
        """
        Start processing an email. Business logic: only start if DISCOVERED.
        This is the state machine logic that was in the repository.
        """
        # Get the email record
        email_record = await self.email_repository.get_email_record(user_id, message_id)
        if not email_record:
            raise EmailRecordNotFoundError(message_id)
        
        # Business rule: Can only start processing if status is DISCOVERED
        if email_record.status != EmailStatus.DISCOVERED:
            if email_record.status == EmailStatus.PROCESSING:
                raise ValidationError("Email is already being processed")
            else:
                raise ValidationError(f"Cannot start processing email in status: {email_record.status.value}")
        
        # Business rule: Check if user has sufficient credits
        try:
            balance = await self.billing_service.get_credit_balance(UUID(user_id))
            if not balance.can_afford(1):  # 1 credit per email
                raise InsufficientCreditsError(
                    f"Insufficient credits: need 1, have {balance.credits_remaining}",
                    balance=balance.credits_remaining,
                    requested=1
                )
        except Exception as e:
            logger.error(f"Credit check failed for user {user_id}: {e}")
            raise APIError(f"Credit check failed: {str(e)}")
        
        # Update status to PROCESSING
        try:
            return await self.email_repository.update_email_record(
                user_id,
                message_id,
                status=EmailStatus.PROCESSING,
                processing_started_at=datetime.utcnow(),
                processing_attempts=email_record.processing_attempts + 1
            )
        except Exception as e:
            logger.error(f"Failed to start processing for email {message_id}: {e}")
            raise APIError(f"Failed to start email processing: {str(e)}")

    async def complete_email_processing(
        self,
        user_id: str,
        message_id: str,
        processing_result: Dict[str, Any],
        success: bool = True
    ) -> EmailRecord:
        """
        Complete email processing. Business logic: only complete if PROCESSING.
        This is the state machine logic that was in the repository.
        """
        # Get the email record
        email_record = await self.email_repository.get_email_record(user_id, message_id)
        if not email_record:
            raise EmailRecordNotFoundError(message_id)
        
        # Business rule: Can only complete if status is PROCESSING
        if email_record.status != EmailStatus.PROCESSING:
            raise ValidationError(f"Cannot complete email not in processing state: {email_record.status.value}")
        
        # Business rule: Deduct credits if successful
        if success:
            try:
                await self.billing_service.deduct_credits(
                    user_id=UUID(user_id),
                    credit_amount=1,
                    description=f"Email processing: {message_id}",
                    reference_id=message_id,
                    reference_type="email_processing"
                )
            except Exception as e:
                logger.error(f"Credit deduction failed for user {user_id}: {e}")
                # Don't fail the processing, but log the issue
                processing_result["billing_error"] = str(e)
        
        # Merge processing results with existing data
        updated_result = {**email_record.processing_result, **processing_result}
        
        # Update status to COMPLETED or FAILED
        try:
            return await self.email_repository.update_email_record(
                user_id,
                message_id,
                status=EmailStatus.COMPLETED if success else EmailStatus.FAILED,
                processing_completed_at=datetime.utcnow(),
                processing_result=updated_result,
                success=success
            )
        except Exception as e:
            logger.error(f"Failed to complete processing for email {message_id}: {e}")
            raise APIError(f"Failed to complete email processing: {str(e)}")

    async def retry_email_processing(
        self,
        user_id: str,
        message_id: str
    ) -> EmailRecord:
        """
        Retry processing a failed email. Business logic for retry workflow.
        """
        # Get the email record
        email_record = await self.email_repository.get_email_record(user_id, message_id)
        if not email_record:
            raise EmailRecordNotFoundError(message_id)
        
        # Business rule: Can only retry failed emails
        if email_record.status != EmailStatus.FAILED:
            raise ValidationError(f"Cannot retry email not in failed state: {email_record.status.value}")
        
        # Business rule: Check retry limits
        if email_record.processing_attempts >= email_record.max_retries:
            raise ValidationError(f"Email has exceeded max retries ({email_record.max_retries})")
        
        # Update status to RETRYING
        try:
            return await self.email_repository.update_email_record(
                user_id,
                message_id,
                status=EmailStatus.RETRYING,
                last_retry_at=datetime.utcnow()
            )
        except Exception as e:
            logger.error(f"Failed to retry processing for email {message_id}: {e}")
            raise APIError(f"Failed to retry email processing: {str(e)}")

    # ========== PROCESSING ORCHESTRATION ==========

    async def process_single_email(
        self,
        user_id: str,
        message_id: str,
        gmail_service=None,  # Would be GmailService
        ai_service=None      # Would be AIService
    ) -> Dict[str, Any]:
        """
        Complete processing workflow for a single email.
        Business orchestration method.
        """
        # Get processing lock for this user
        if user_id not in self._processing_locks:
            self._processing_locks[user_id] = asyncio.Lock()
        
        async with self._processing_locks[user_id]:
            start_time = datetime.utcnow()
            
            try:
                # Step 1: Start processing (state machine + credit check)
                email_record = await self.start_email_processing(user_id, message_id)
                
                # Step 2: Get email content from Gmail (mocked)
                email_content = await self._get_email_content(gmail_service, message_id)
                
                # Step 3: Generate AI summary (mocked)
                ai_result = await self._generate_ai_summary(ai_service, email_content)
                
                # Step 4: Send summary back to Gmail (mocked)
                delivery_result = await self._send_summary_to_gmail(gmail_service, email_content, ai_result)
                
                # Step 5: Complete processing
                processing_time = (datetime.utcnow() - start_time).total_seconds()
                processing_result = {
                    "processing_time": processing_time,
                    "credits_used": 1,
                    "ai_confidence": ai_result.get("confidence", 0.95),
                    "summary_length": len(ai_result.get("summary", "")),
                    "delivery_status": delivery_result.get("status", "unknown")
                }
                
                await self.complete_email_processing(
                    user_id, 
                    message_id, 
                    processing_result, 
                    success=True
                )
                
                logger.info(f"Successfully processed email {message_id} for user {user_id}")
                return {
                    "success": True,
                    "processing_time": processing_time,
                    "credits_used": 1,
                    "summary": ai_result.get("summary")
                }
                
            except Exception as e:
                # If we started processing, mark as failed
                try:
                    processing_time = (datetime.utcnow() - start_time).total_seconds()
                    await self.complete_email_processing(
                        user_id,
                        message_id,
                        {
                            "processing_time": processing_time,
                            "error": str(e),
                            "error_type": type(e).__name__
                        },
                        success=False
                    )
                except:
                    pass  # Best effort
                
                logger.error(f"Failed to process email {message_id} for user {user_id}: {e}")
                raise APIError(f"Email processing failed: {str(e)}")

    async def process_user_emails(
        self,
        user_id: str,
        limit: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Process all discovered emails for a user.
        Business orchestration method.
        """
        try:
            # Get discovered emails
            discovered_emails = await self.email_repository.list_email_records(
                user_id, 
                status=EmailStatus.DISCOVERED,
                limit=limit
            )
            
            if not discovered_emails:
                return {
                    "success": True,
                    "processed_count": 0,
                    "message": "No emails to process"
                }
            
            # Process each email
            processed_count = 0
            failed_count = 0
            
            for email_record in discovered_emails:
                try:
                    await self.process_single_email(user_id, email_record.message_id)
                    processed_count += 1
                except Exception as e:
                    logger.warning(f"Failed to process email {email_record.message_id}: {e}")
                    failed_count += 1
                    continue
            
            logger.info(f"Processed {processed_count} emails for user {user_id}, {failed_count} failed")
            return {
                "success": True,
                "processed_count": processed_count,
                "failed_count": failed_count,
                "total_discovered": len(discovered_emails)
            }
            
        except Exception as e:
            logger.error(f"Batch email processing failed for user {user_id}: {e}")
            raise APIError(f"Batch email processing failed: {str(e)}")

    # ========== ANALYTICS AND MONITORING ==========

    async def get_processing_stats(self, user_id: str) -> ProcessingStats:
        """
        Get processing statistics for a user.
        Business analytics method that was in the repository.
        """
        try:
            records = await self.email_repository.list_email_records(user_id, limit=None)
            return ProcessingStats.from_records(user_id, records)
        except Exception as e:
            logger.error(f"Failed to get processing stats for user {user_id}: {e}")
            raise APIError(f"Failed to get processing stats: {str(e)}")

    async def get_user_processing_status(self, user_id: str) -> Dict[str, Any]:
        """
        Get current processing status for a user.
        """
        try:
            # Check if processing is active
            is_processing = user_id in self._processing_locks and self._processing_locks[user_id].locked()
            
            # Get statistics
            stats = await self.get_processing_stats(user_id)
            
            return {
                "user_id": user_id,
                "processing_active": is_processing,
                "stats": {
                    "total_discovered": stats.total_discovered,
                    "total_processed": stats.total_processed,
                    "total_successful": stats.total_successful,
                    "total_failed": stats.total_failed,
                    "total_pending": stats.total_pending,
                    "success_rate": stats.success_rate,
                    "total_credits_used": stats.total_credits_used,
                    "average_processing_time": stats.average_processing_time
                },
                "status": "processing" if is_processing else "idle"
            }
            
        except Exception as e:
            logger.error(f"Failed to get processing status for user {user_id}: {e}")
            return {
                "user_id": user_id,
                "processing_active": False,
                "status": "error",
                "error": str(e)
            }

    # ========== MOCK IMPLEMENTATIONS ==========
    # These would be replaced with real service calls

    async def _get_new_emails_from_gmail(
        self, 
        gmail_service, 
        user_email: str, 
        filters: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Mock implementation - would use real GmailService"""
        await asyncio.sleep(0.1)  # Simulate API call
        return [
            {
                "message_id": "msg_001",
                "subject": "Test Email 1",
                "sender": "test@example.com",
                "received_at": datetime.utcnow().isoformat()
            }
        ]

    async def _get_email_content(self, gmail_service, message_id: str) -> Dict[str, Any]:
        """Mock implementation - would use real GmailService"""
        await asyncio.sleep(0.1)  # Simulate API call
        return {
            "message_id": message_id,
            "subject": "Test Email",
            "body": "This is a test email body.",
            "sender": "test@example.com"
        }

    async def _generate_ai_summary(self, ai_service, email_content: Dict[str, Any]) -> Dict[str, Any]:
        """Mock implementation - would use real AIService"""
        await asyncio.sleep(0.2)  # Simulate AI processing
        return {
            "summary": f"AI Summary of: {email_content.get('subject', 'Unknown')}",
            "confidence": 0.95,
            "key_points": ["Point 1", "Point 2"],
            "action_items": ["Action 1"]
        }

    async def _send_summary_to_gmail(
        self, 
        gmail_service, 
        email_content: Dict[str, Any], 
        ai_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Mock implementation - would use real GmailService"""
        await asyncio.sleep(0.1)  # Simulate API call
        return {
            "status": "delivered",
            "message_id": "summary_msg_001",
            "delivery_time": datetime.utcnow().isoformat()
        }


# ========== EXAMPLE ROUTE USAGE ==========
"""
Example of how routes would use EmailProcessingService:

from app.core.container import get_email_processing_service

@router.post("/discover")
async def discover_emails(
    context: UserContext = Depends(get_user_context),
    email_service: EmailProcessingService = Depends(get_email_processing_service)
):
    result = await email_service.discover_emails_for_user(
        user_id=context.user_id,
        gmail_service=gmail_service
    )
    return result

@router.post("/process/{message_id}")
async def process_email(
    message_id: str,
    context: UserContext = Depends(get_user_context),
    email_service: EmailProcessingService = Depends(get_email_processing_service)
):
    result = await email_service.process_single_email(
        user_id=context.user_id,
        message_id=message_id
    )
    return result
"""