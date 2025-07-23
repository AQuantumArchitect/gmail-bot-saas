import asyncio
import base64
import time
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta
from uuid import uuid4

from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

from app.core.exceptions import ValidationError, NotFoundError, AuthenticationError, RateLimitError, APIError
from app.data.repositories.gmail_repository import GmailRepository
from app.data.repositories.user_repository import UserRepository
from app.data.repositories.email_repository import EmailRepository
from app.data.repositories.job_repository import JobRepository
from app.services.gmail_oauth_service import GmailOAuthService


class GmailService:
    """
    Gmail service for email discovery, processing, and management.
    
    Handles:
    - Email discovery from Gmail API
    - Email processing with AI summaries
    - Rate limiting and circuit breaker
    - Batch processing for multiple users
    - Queue management and health monitoring
    """
    
    # Configuration
    DEFAULT_MAX_EMAILS_PER_RUN = 10
    DEFAULT_RATE_LIMIT_PER_MINUTE = 100
    DEFAULT_CIRCUIT_BREAKER_THRESHOLD = 5
    DEFAULT_RETRY_MAX_ATTEMPTS = 3
    DEFAULT_RETRY_BACKOFF_MULTIPLIER = 2
    MAX_CONTENT_LENGTH = 5000
    
    def __init__(
        self,
        gmail_repository: GmailRepository,
        user_repository: UserRepository,
        email_repository: EmailRepository,
        job_repository: JobRepository,
        oauth_service: GmailOAuthService
    ):
        self.gmail_repository = gmail_repository
        self.user_repository = user_repository
        self.email_repository = email_repository
        self.job_repository = job_repository
        self.oauth_service = oauth_service
        
        # In-memory stores for demo/testing
        self._rate_limits: Dict[str, Dict[str, Any]] = {}
        self._circuit_breakers: Dict[str, Dict[str, Any]] = {}
        self._processing_locks: Dict[str, asyncio.Lock] = {}
    
    # --- Core Gmail Service Methods ---
    
    async def get_gmail_service(self, user_id: str):
        """Get authenticated Gmail service for user."""
        connection_info = self.oauth_service.get_connection_info(user_id)
        if not connection_info:
            raise NotFoundError("Gmail connection not found")
        
        tokens = self.gmail_repository.get_oauth_tokens(user_id)
        if not tokens:
            raise NotFoundError("Gmail tokens not found")
        
        # Check if token needs refresh
        if tokens.get("expires_in", 0) <= 0:
            try:
                refreshed = await self.oauth_service.refresh_access_token(user_id)
                tokens = refreshed
            except Exception as e:
                raise AuthenticationError(f"Failed to refresh token: {e}")
        
        # Create Gmail service
        return self._create_gmail_api_service(tokens["access_token"])
    
    def _create_gmail_api_service(self, access_token: str):
        """Create Gmail API service instance."""
        # Create credentials object
        credentials = Credentials(token=access_token)
        
        # Build Gmail API service
        service = build('gmail', 'v1', credentials=credentials)
        
        return service
    
    # --- Email Discovery ---
    
    async def discover_emails(self, user_id: str, apply_filters: bool = True) -> Dict[str, Any]:
        """
        Discover new emails for a user.
        
        Returns discovered emails with filtering applied.
        """
        # Check circuit breaker
        circuit_state = self._check_circuit_breaker(user_id)
        if circuit_state["state"] == "open":
            raise APIError("Circuit breaker is open - too many recent failures")
        
        # Check rate limit
        rate_limit = self.check_rate_limit(user_id, "email_discovery")
        if not rate_limit["allowed"]:
            raise RateLimitError("Rate limit exceeded for email discovery")
        
        try:
            gmail_service = await self.get_gmail_service(user_id)
            
            # Get user profile for filters
            user_profile = self.user_repository.get_user_profile(user_id)
            if not user_profile:
                raise NotFoundError("User profile not found")
            
            # Generate Gmail query
            filters = user_profile.get("email_filters", {})
            query = self._generate_gmail_query(filters)
            
            # Fetch emails from Gmail
            messages_result = gmail_service.users().messages().list(
                userId="me",
                q=query,
                maxResults=self.DEFAULT_MAX_EMAILS_PER_RUN
            ).execute()
            
            messages = messages_result.get("messages", [])
            
            discovered_emails = []
            new_emails = 0
            filtered_emails = 0
            
            for message in messages:
                message_id = message["id"]
                
                # Check if already processed
                if self.email_repository.get_processing_status(message_id):
                    continue
                
                # Get full message
                full_message = gmail_service.users().messages().get(
                    userId="me",
                    id=message_id,
                    format="full"
                ).execute()
                
                # Parse message
                parsed_email = self._parse_email_message(full_message)
                if not parsed_email:
                    continue
                
                # Apply filters
                if apply_filters:
                    filter_result = self.apply_email_filters(parsed_email, filters)
                    if not filter_result["should_process"]:
                        filtered_emails += 1
                        continue
                
                # Mark as discovered
                discovery_result = self.email_repository.mark_discovered(
                    user_id=user_id,
                    message_id=message_id,
                    email_data=parsed_email
                )
                
                discovered_emails.append(discovery_result)
                new_emails += 1
            
            # Update circuit breaker on success
            self._update_circuit_breaker(user_id, success=True)
            
            return {
                "success": True,
                "user_id": user_id,
                "emails_discovered": len(messages),
                "new_emails": new_emails,
                "filtered_emails": filtered_emails,
                "discovered_emails": discovered_emails,
                "discovery_time": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            # Update circuit breaker on failure
            self._update_circuit_breaker(user_id, success=False)
            
            # Handle specific Gmail API errors
            error_info = self._handle_gmail_api_error(e)
            
            if error_info["error_type"] == "rate_limit":
                raise RateLimitError("Rate limit exceeded")
            elif error_info["error_type"] == "authentication":
                raise AuthenticationError("Invalid token")
            else:
                raise APIError(f"Gmail API error: {str(e)}")
    
    # --- Email Processing ---
    
    async def process_email(self, user_id: str, message_id: str) -> Dict[str, Any]:
        """
        Process a single email with AI summary.
        
        Returns processing result with summary and credits used.
        """
        start_time = time.time()
        
        # Check if already processed
        status = self.email_repository.get_processing_status(message_id)
        if status and status["status"] == "completed":
            raise ValidationError("Email already processed")
        
        # Check user permissions
        user_profile = self.user_repository.get_user_profile(user_id)
        if not user_profile:
            raise NotFoundError("User profile not found")
        
        if user_profile.get("credits_remaining", 0) <= 0:
            raise ValidationError("Insufficient credits")
        
        if not user_profile.get("bot_enabled", False):
            raise ValidationError("Bot is disabled")
        
        # Mark processing started
        self.email_repository.mark_processing_started(user_id, message_id)
        
        try:
            # Get Gmail service and fetch message
            gmail_service = await self.get_gmail_service(user_id)
            message = gmail_service.users().messages().get(
                userId="me",
                id=message_id,
                format="full"
            ).execute()
            
            # Parse email
            parsed_email = self._parse_email_message(message)
            if not parsed_email:
                raise ValidationError("Could not parse email")
            
            # Generate AI summary
            summary_result = await self._generate_ai_summary(parsed_email)
            
            # Send summary reply
            reply_result = await self._send_summary_reply(
                gmail_service,
                parsed_email,
                summary_result,
                user_profile.get("email_address", "user@example.com")
            )
            
            # Mark as read
            await self._mark_as_read(gmail_service, message_id)
            
            # Mark processing completed
            self.email_repository.mark_processing_completed(
                user_id=user_id,
                message_id=message_id,
                processing_result={
                    "summary": summary_result,
                    "reply_sent": reply_result.get("success", False),
                    "credits_used": 1,
                    "processing_time": time.time() - start_time
                }
            )
            
            return {
                "success": True,
                "message_id": message_id,
                "summary_sent": reply_result.get("success", False),
                "processing_time": time.time() - start_time,
                "credits_used": 1
            }
            
        except Exception as e:
            # Mark processing failed
            self.email_repository.mark_processing_failed(
                user_id=user_id,
                message_id=message_id,
                error=str(e)
            )
            raise
    
    async def process_user_emails(self, user_id: str, max_emails: int = None) -> Dict[str, Any]:
        """
        Process multiple emails for a user in batch.
        
        Returns batch processing results.
        """
        # Prevent concurrent processing for same user
        if user_id not in self._processing_locks:
            self._processing_locks[user_id] = asyncio.Lock()
        
        if self._processing_locks[user_id].locked():
            raise ValidationError("User email processing already in progress")
        
        async with self._processing_locks[user_id]:
            max_emails = max_emails or self.DEFAULT_MAX_EMAILS_PER_RUN
            
            # Get unprocessed emails
            unprocessed_emails = self.email_repository.get_unprocessed_emails(
                user_id=user_id,
                limit=max_emails
            )
            
            if not unprocessed_emails:
                return {
                    "success": True,
                    "user_id": user_id,
                    "emails_processed": 0,
                    "credits_used": 0,
                    "failed_emails": 0,
                    "errors": []
                }
            
            # Process emails
            emails_processed = 0
            credits_used = 0
            failed_emails = 0
            errors = []
            
            for email in unprocessed_emails:
                try:
                    result = await self.process_email(user_id, email["message_id"])
                    if result["success"]:
                        emails_processed += 1
                        credits_used += result.get("credits_used", 0)
                    else:
                        failed_emails += 1
                        
                except Exception as e:
                    failed_emails += 1
                    errors.append({
                        "message_id": email["message_id"],
                        "error": str(e)
                    })
                    
                    # Stop if out of credits
                    if "insufficient credits" in str(e).lower():
                        break
            
            return {
                "success": True,
                "user_id": user_id,
                "emails_processed": emails_processed,
                "credits_used": credits_used,
                "failed_emails": failed_emails,
                "errors": errors,
                "stop_reason": "insufficient credits" if errors and "insufficient credits" in str(errors[-1]["error"]).lower() else None
            }
    
    # --- Email Filtering ---
    
    def apply_email_filters(self, email_data: Dict[str, Any], filters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Apply user filters to determine if email should be processed.
        
        Returns filter result with decision and reason.
        """
        # Check exclude senders
        sender = email_data.get("sender", "")
        if sender in filters.get("exclude_senders", []):
            return {"should_process": False, "filter_reason": "sender_excluded"}
        
        # Check exclude domains
        sender_domain = sender.split("@")[-1] if "@" in sender else ""
        if sender_domain in filters.get("exclude_domains", []):
            return {"should_process": False, "filter_reason": "domain_excluded"}
        
        # Check include keywords (if specified, at least one must match)
        include_keywords = filters.get("include_keywords", [])
        if include_keywords:
            content_text = f"{email_data.get('subject', '')} {email_data.get('content', '')}".lower()
            if not any(keyword.lower() in content_text for keyword in include_keywords):
                return {"should_process": False, "filter_reason": "include_keyword_missing"}
        
        # Check exclude keywords
        exclude_keywords = filters.get("exclude_keywords", [])
        if exclude_keywords:
            content_text = f"{email_data.get('subject', '')} {email_data.get('content', '')}".lower()
            if any(keyword.lower() in content_text for keyword in exclude_keywords):
                return {"should_process": False, "filter_reason": "keyword_excluded"}
        
        # Check minimum content length
        min_length = filters.get("min_email_length", 0)
        content_length = len(email_data.get("content", ""))
        if content_length < min_length:
            return {"should_process": False, "filter_reason": "content_too_short"}
        
        return {"should_process": True, "filter_reason": None}
    
    # --- Parsing & Content Extraction ---
    
    def _parse_email_message(self, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Parse Gmail message into structured format."""
        try:
            if "payload" not in message:
                return None
            
            payload = message["payload"]
            headers = payload.get("headers", [])
            
            # Extract headers
            header_dict = {h["name"]: h["value"] for h in headers}
            
            # Extract content
            content = self._extract_message_content(payload)
            if not content or len(content.strip()) == 0:
                return None
            
            return {
                "id": message["id"],
                "subject": header_dict.get("Subject", ""),
                "sender": header_dict.get("From", ""),
                "content": content,
                "thread_id": message.get("threadId", ""),
                "received_at": header_dict.get("Date", ""),
                "internal_date": message.get("internalDate", "")
            }
            
        except Exception:
            return None
    
    def _extract_message_content(self, payload: Dict[str, Any]) -> str:
        """Extract text content from message payload."""
        content = ""
        
        # Check body
        if "body" in payload and payload["body"].get("data"):
            content = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8")
        
        # Check parts
        elif "parts" in payload:
            for part in payload["parts"]:
                if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
                    content = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8")
                    break
        
        return self._extract_email_content(content, "text/plain")
    
    def _extract_email_content(self, content: str, mime_type: str) -> str:
        """Extract and clean email content."""
        # Handle HTML content
        if mime_type == "text/html":
            # Simple HTML stripping (would use BeautifulSoup in production)
            import re
            content = re.sub(r'<[^>]+>', '', content)
        
        # Truncate if too long
        if len(content) > self.MAX_CONTENT_LENGTH:
            content = content[:self.MAX_CONTENT_LENGTH - 3] + "..."
        
        return content.strip()
    
    # --- AI Summary Generation ---
    
    async def _generate_ai_summary(self, email_data: Dict[str, Any]) -> Dict[str, Any]:
        """Generate AI summary of email content."""
        # Mock AI summary generation
        return {
            "summary": f"Summary of email: {email_data.get('subject', 'No subject')}",
            "keywords": ["important", "email"],
            "action_items": ["Review email content"],
            "cost": 0.01,
            "tokens_used": 150
        }
    
    # --- Reply Sending ---
    
    async def _send_summary_reply(
        self,
        gmail_service,
        email_data: Dict[str, Any],
        summary_data: Dict[str, Any],
        user_email: str
    ) -> Dict[str, Any]:
        """Send AI summary as reply to original email."""
        try:
            # Create reply message
            reply_body = f"""
🤖 AI Summary: {email_data.get('subject', 'No subject')}

{summary_data.get('summary', '')}

Keywords: {', '.join(summary_data.get('keywords', []))}

Action Items:
{chr(10).join(f"• {item}" for item in summary_data.get('action_items', []))}

---
This summary was generated automatically by your Gmail Bot.
            """.strip()
            
            # Send reply
            result = gmail_service.users().messages().send(
                userId="me",
                body={
                    "raw": base64.urlsafe_b64encode(reply_body.encode()).decode(),
                    "threadId": email_data.get("thread_id")
                }
            ).execute()
            
            return {
                "success": True,
                "reply_id": result["id"],
                "thread_id": result["threadId"]
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    async def _mark_as_read(self, gmail_service, message_id: str) -> bool:
        """Mark email as read."""
        try:
            gmail_service.users().messages().modify(
                userId="me",
                id=message_id,
                body={"removeLabelIds": ["UNREAD"]}
            ).execute()
            return True
        except Exception:
            return False
    
    # --- Rate Limiting ---
    
    def check_rate_limit(self, user_id: str, action: str) -> Dict[str, Any]:
        """Check if user is within rate limits."""
        key = f"{user_id}:{action}"
        now = datetime.utcnow()
        
        if key not in self._rate_limits:
            self._rate_limits[key] = {
                "requests": 0,
                "window_start": now,
                "limit": self.DEFAULT_RATE_LIMIT_PER_MINUTE
            }
        
        rate_limit = self._rate_limits[key]
        
        # Reset window if needed
        if now - rate_limit["window_start"] > timedelta(minutes=1):
            rate_limit["requests"] = 0
            rate_limit["window_start"] = now
        
        # Check limit
        rate_limit["requests"] += 1
        allowed = rate_limit["requests"] <= rate_limit["limit"]
        remaining = max(rate_limit["limit"] - rate_limit["requests"], 0)
        
        return {
            "allowed": allowed,
            "remaining": remaining,
            "reset_time": (rate_limit["window_start"] + timedelta(minutes=1)).isoformat()
        }
    
    def _check_rate_limit(self, identifier: str, action: str) -> Dict[str, Any]:
        """Internal rate limit check."""
        key = f"{identifier}:{action}"
        now = datetime.utcnow()
        
        if key not in self._rate_limits:
            self._rate_limits[key] = {
                "requests": 0,
                "window_start": now,
                "limit": self.DEFAULT_RATE_LIMIT_PER_MINUTE
            }
        
        rate_limit = self._rate_limits[key]
        
        # Reset window if needed
        if now - rate_limit["window_start"] > timedelta(minutes=1):
            rate_limit["requests"] = 0
            rate_limit["window_start"] = now
        
        # Check limit (don't increment here, let the caller do it)
        allowed = rate_limit["requests"] < rate_limit["limit"]
        remaining = max(rate_limit["limit"] - rate_limit["requests"], 0)
        
        return {
            "allowed": allowed,
            "remaining": remaining,
            "reset_time": (rate_limit["window_start"] + timedelta(minutes=1)).isoformat()
        }
    
    # --- Circuit Breaker ---
    
    def _check_circuit_breaker(self, user_id: str) -> Dict[str, Any]:
        """Check circuit breaker state."""
        if user_id not in self._circuit_breakers:
            self._circuit_breakers[user_id] = {
                "state": "closed",
                "failure_count": 0,
                "last_failure": None,
                "last_success": None
            }
        
        breaker = self._circuit_breakers[user_id]
        now = datetime.utcnow()
        
        # Check if should transition from open to half-open
        if breaker["state"] == "open" and breaker["last_failure"]:
            last_failure = datetime.fromisoformat(breaker["last_failure"])
            if now - last_failure > timedelta(minutes=5):  # 5 minute timeout
                breaker["state"] = "half_open"
        
        return breaker
    
    def _update_circuit_breaker(self, user_id: str, success: bool) -> None:
        """Update circuit breaker state."""
        if user_id not in self._circuit_breakers:
            self._circuit_breakers[user_id] = {
                "state": "closed",
                "failure_count": 0,
                "last_failure": None,
                "last_success": None
            }
        
        breaker = self._circuit_breakers[user_id]
        now = datetime.utcnow().isoformat()
        
        if success:
            breaker["state"] = "closed"
            breaker["failure_count"] = 0
            breaker["last_success"] = now
        else:
            breaker["failure_count"] += 1
            breaker["last_failure"] = now
            
            if breaker["failure_count"] >= self.DEFAULT_CIRCUIT_BREAKER_THRESHOLD:
                breaker["state"] = "open"
    
    # --- Batch Processing ---
    
    async def bulk_process_users(self, user_ids: List[str]) -> Dict[str, Any]:
        """Process emails for multiple users in batch."""
        total_users = len(user_ids)
        successful_users = 0
        failed_users = 0
        total_emails_processed = 0
        total_credits_used = 0
        
        for user_id in user_ids:
            try:
                result = await self.process_user_emails(user_id)
                if result["success"]:
                    successful_users += 1
                    total_emails_processed += result["emails_processed"]
                    total_credits_used += result["credits_used"]
                else:
                    failed_users += 1
            except Exception:
                failed_users += 1
        
        return {
            "total_users": total_users,
            "successful_users": successful_users,
            "failed_users": failed_users,
            "total_emails_processed": total_emails_processed,
            "total_credits_used": total_credits_used
        }
    
    # --- Utilities ---
    
    def _generate_gmail_query(self, filters: Dict[str, Any]) -> str:
        """Generate Gmail search query from filters."""
        query_parts = ["is:unread", '-subject:"🤖 AI Summary:"']
        
        # Exclude senders
        for sender in filters.get("exclude_senders", []):
            query_parts.append(f"-from:{sender}")
        
        # Exclude domains
        for domain in filters.get("exclude_domains", []):
            query_parts.append(f"-from:*@{domain}")
        
        # Include keywords
        include_keywords = filters.get("include_keywords", [])
        if include_keywords:
            query_parts.append(f"({' OR '.join(include_keywords)})")
        
        # Exclude keywords
        for keyword in filters.get("exclude_keywords", []):
            query_parts.append(f"-{keyword}")
        
        return " ".join(query_parts)
    
    def _handle_gmail_api_error(self, error: Exception) -> Dict[str, Any]:
        """Handle Gmail API errors and categorize them."""
        error_str = str(error).lower()
        
        if any(term in error_str for term in ["quota", "rate", "limit"]):
            return {
                "error_type": "rate_limit",
                "retry_after": 60,
                "permanent": False
            }
        elif any(term in error_str for term in ["invalid_grant", "unauthorized", "forbidden"]):
            return {
                "error_type": "authentication",
                "permanent": True,
                "action": "reauth_required"
            }
        else:
            return {
                "error_type": "unknown",
                "permanent": False
            }
    
    # --- Retry Logic ---
    
    async def _retry_with_backoff(self, func, max_retries: int = None):
        """Retry function with exponential backoff."""
        max_retries = max_retries or self.DEFAULT_RETRY_MAX_ATTEMPTS
        
        for attempt in range(max_retries):
            try:
                return await func()
            except Exception as e:
                if attempt == max_retries - 1:
                    raise
                
                # Calculate backoff delay
                delay = (self.DEFAULT_RETRY_BACKOFF_MULTIPLIER ** attempt)
                await asyncio.sleep(delay)
    
    # --- Monitoring & Health ---
    
    def get_queue_status(self) -> Dict[str, Any]:
        """Get processing queue status."""
        stats = self.email_repository.get_processing_stats()
        
        pending = stats.get("total_pending", 0)
        processing = stats.get("total_processing", 0)
        avg_time = stats.get("average_processing_time", 0)
        
        # Determine queue health
        if pending > 50 or avg_time > 10:
            status = "overloaded"
        elif pending > 20 or avg_time > 5:
            status = "degraded"
        else:
            status = "healthy"
        
        return {
            "queue_status": status,
            "pending_jobs": pending,
            "processing_jobs": processing,
            "average_processing_time": avg_time,
            "timestamp": datetime.utcnow().isoformat()
        }
    
    def get_user_gmail_statistics(self, user_id: str) -> Dict[str, Any]:
        """Get Gmail statistics for a user."""
        email_stats = self.email_repository.get_processing_stats(user_id)
        connection_info = self.gmail_repository.get_connection_info(user_id)
        
        return {
            "user_id": user_id,
            "connection_status": connection_info.get("connection_status", "not_connected") if connection_info else "not_connected",
            "email_address": connection_info.get("email_address") if connection_info else None,
            "total_discovered": email_stats.get("total_discovered", 0),
            "total_processed": email_stats.get("total_processed", 0),
            "total_successful": email_stats.get("total_successful", 0),
            "total_failed": email_stats.get("total_failed", 0),
            "success_rate": email_stats.get("success_rate", 0.0),
            "total_credits_used": email_stats.get("total_credits_used", 0),
            "average_processing_time": email_stats.get("average_processing_time", 0.0)
        }
    
    async def validate_gmail_connection(self, user_id: str) -> Dict[str, Any]:
        """Validate Gmail connection for user."""
        return await self.oauth_service.validate_connection(user_id)
    
    def get_configuration(self) -> Dict[str, Any]:
        """Get service configuration."""
        return {
            "max_emails_per_run": self.DEFAULT_MAX_EMAILS_PER_RUN,
            "rate_limit_requests_per_minute": self.DEFAULT_RATE_LIMIT_PER_MINUTE,
            "circuit_breaker_failure_threshold": self.DEFAULT_CIRCUIT_BREAKER_THRESHOLD,
            "retry_max_attempts": self.DEFAULT_RETRY_MAX_ATTEMPTS,
            "retry_backoff_multiplier": self.DEFAULT_RETRY_BACKOFF_MULTIPLIER,
            "max_content_length": self.MAX_CONTENT_LENGTH
        }
    
    def health_check(self) -> Dict[str, Any]:
        """Perform health check."""
        return {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "version": "1.0.0",
            "dependencies": {
                "gmail_api": "available",
                "oauth_service": "available",
                "repositories": "available"
            }
        }
    
    # --- Cleanup ---
    
    async def cleanup_stale_jobs(self) -> Dict[str, Any]:
        """Clean up stale processing jobs."""
        stale_jobs = self.email_repository.get_stale_processing_emails()
        cleaned_count = 0
        
        for job in stale_jobs:
            try:
                self.email_repository.mark_processing_timeout(
                    job["user_id"],
                    job["message_id"]
                )
                cleaned_count += 1
            except Exception:
                pass
        
        return {
            "success": True,
            "cleaned_jobs": cleaned_count
        }