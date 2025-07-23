# tests/unit/services/test_gmail_service.py
"""
Test-first driver for GmailService implementation.
Handles email discovery, processing, rate limiting, and error recovery.
"""
import pytest
from uuid import uuid4
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from app.services.gmail_service import GmailService
from app.core.exceptions import ValidationError, NotFoundError, AuthenticationError, RateLimitError, APIError
from app.data.repositories.gmail_repository import GmailRepository
from app.data.repositories.user_repository import UserRepository
from app.data.repositories.email_repository import EmailRepository
from app.data.repositories.job_repository import JobRepository
from app.services.gmail_oauth_service import GmailOAuthService

class TestGmailService:
    """Test-driven development for GmailService"""
    
    @pytest.fixture
    def mock_gmail_repo(self):
        """Mock GmailRepository"""
        return Mock(spec=GmailRepository)
    
    @pytest.fixture
    def mock_user_repo(self):
        """Mock UserRepository"""
        return Mock(spec=UserRepository)
    
    @pytest.fixture
    def mock_email_repo(self):
        """Mock EmailRepository"""
        return Mock(spec=EmailRepository)
    
    @pytest.fixture
    def mock_job_repo(self):
        """Mock JobRepository"""
        return Mock(spec=JobRepository)
    
    @pytest.fixture
    def mock_oauth_service(self):
        """Mock GmailOAuthService"""
        return Mock(spec=GmailOAuthService)
    
    @pytest.fixture
    def mock_gmail_api(self):
        """Mock Gmail API client"""
        return Mock()
    
    @pytest.fixture
    def gmail_service(self, mock_gmail_repo, mock_user_repo, mock_email_repo, mock_job_repo, mock_oauth_service):
        """Create GmailService instance - this doesn't exist yet!"""
        return GmailService(
            gmail_repository=mock_gmail_repo,
            user_repository=mock_user_repo,
            email_repository=mock_email_repo,
            job_repository=mock_job_repo,
            oauth_service=mock_oauth_service
        )
    
    @pytest.fixture
    def sample_user_profile(self):
        """Sample user profile with Gmail connection"""
        return {
            "id": str(uuid4()),
            "email": "user@example.com",
            "name": "John Doe",
            "credits_remaining": 25,
            "bot_enabled": True,
            "processing_frequency": 15,
            "email_filters": {
                "exclude_senders": ["noreply@example.com"],
                "exclude_domains": ["spam.com"],
                "include_keywords": ["important"],
                "exclude_keywords": ["newsletter"],
                "min_email_length": 50
            }
        }
    
    @pytest.fixture
    def sample_gmail_message(self):
        """Sample Gmail message structure"""
        return {
            "id": "message_123",
            "threadId": "thread_123",
            "labelIds": ["INBOX", "UNREAD"],
            "payload": {
                "headers": [
                    {"name": "From", "value": "sender@example.com"},
                    {"name": "Subject", "value": "Important Email"},
                    {"name": "Date", "value": "Mon, 1 Jan 2024 12:00:00 +0000"}
                ],
                "body": {
                    "data": "VGhpcyBpcyBhIHRlc3QgZW1haWwgY29udGVudCB0aGF0IGlzIGxvbmcgZW5vdWdoIGZvciBwcm9jZXNzaW5n"
                },
                "parts": []
            },
            "internalDate": "1704110400000",
            "historyId": "12345"
        }
    
    @pytest.mark.asyncio
    async def test_get_gmail_service_success(self, gmail_service, mock_oauth_service, sample_user_profile):
        """Test getting Gmail service instance with valid credentials"""
        user_id = sample_user_profile["id"]
        
        # Mock OAuth tokens
        mock_oauth_service.get_connection_info.return_value = {
            "connection_status": "connected",
            "scopes": ["gmail.readonly", "gmail.modify", "gmail.send"]
        }
        
        mock_gmail_repo = gmail_service.gmail_repository
        mock_gmail_repo.get_oauth_tokens.return_value = {
            "access_token": "valid_access_token",
            "refresh_token": "valid_refresh_token",
            "expires_in": 3600
        }
        
        # Mock Gmail API service creation
        with patch('app.services.gmail_service.build') as mock_build:
            mock_gmail_api = Mock()
            mock_build.return_value = mock_gmail_api
            
            result = await gmail_service.get_gmail_service(user_id)
            
            assert result == mock_gmail_api
            mock_build.assert_called_once_with('gmail', 'v1', credentials=mock_build.call_args[1]['credentials'])
    
    @pytest.mark.asyncio
    async def test_get_gmail_service_no_connection(self, gmail_service, mock_oauth_service):
        """Test getting Gmail service when no connection exists"""
        user_id = str(uuid4())
        
        mock_oauth_service.get_connection_info.return_value = None
        
        with pytest.raises(NotFoundError) as exc_info:
            await gmail_service.get_gmail_service(user_id)
        
        assert "gmail connection not found" in str(exc_info.value).lower()
    
    @pytest.mark.asyncio
    async def test_get_gmail_service_expired_token(self, gmail_service, mock_oauth_service):
        """Test getting Gmail service with expired token triggers refresh"""
        user_id = str(uuid4())
        
        # Mock connection exists but token is expired
        mock_oauth_service.get_connection_info.return_value = {
            "connection_status": "connected",
            "scopes": ["gmail.readonly", "gmail.modify", "gmail.send"]
        }
        
        mock_gmail_repo = gmail_service.gmail_repository
        mock_gmail_repo.get_oauth_tokens.return_value = {
            "access_token": "expired_access_token",
            "refresh_token": "valid_refresh_token",
            "expires_in": -1  # Expired
        }
        
        # Mock successful token refresh - need to make it async
        mock_oauth_service.refresh_access_token = AsyncMock(return_value={
            "access_token": "new_access_token",
            "expires_in": 3600
        })
        
        with patch('app.services.gmail_service.build') as mock_build:
            mock_gmail_api = Mock()
            mock_build.return_value = mock_gmail_api
            
            result = await gmail_service.get_gmail_service(user_id)
            
            assert result == mock_gmail_api
            mock_oauth_service.refresh_access_token.assert_called_once_with(user_id)
    
    @pytest.mark.asyncio
    async def test_discover_emails_success(self, gmail_service, mock_gmail_api, sample_user_profile, sample_gmail_message):
        """Test successful email discovery"""
        user_id = sample_user_profile["id"]
        
        # Mock Gmail service
        with patch.object(gmail_service, 'get_gmail_service', return_value=mock_gmail_api):
            # Mock user repository
            mock_user_repo = gmail_service.user_repository
            mock_user_repo.get_user_profile.return_value = sample_user_profile
            
            # Mock Gmail API responses
            mock_gmail_api.users().getProfile().execute.return_value = {
                "emailAddress": "user@example.com"
            }
            
            mock_gmail_api.users().messages().list().execute.return_value = {
                "messages": [{"id": "message_123"}]
            }
            
            mock_gmail_api.users().messages().get().execute.return_value = sample_gmail_message
            
            # Mock email repository
            mock_email_repo = gmail_service.email_repository
            mock_email_repo.get_processing_status.return_value = None  # Not processed yet
            mock_email_repo.mark_discovered.return_value = {
                "id": str(uuid4()),
                "message_id": "message_123",
                "status": "discovered"
            }
            
            result = await gmail_service.discover_emails(user_id)
            
            assert result["success"] == True
            assert result["user_id"] == user_id
            assert result["emails_discovered"] == 1
            assert result["new_emails"] == 1
            assert len(result["discovered_emails"]) == 1
            assert result["discovered_emails"][0]["message_id"] == "message_123"
    
    @pytest.mark.asyncio
    async def test_discover_emails_with_filters(self, gmail_service, mock_gmail_api, sample_user_profile, sample_gmail_message):
        """Test email discovery with user filters applied"""
        user_id = sample_user_profile["id"]
        
        # Update user profile with filters
        sample_user_profile["email_filters"]["exclude_senders"] = ["sender@example.com"]
        
        with patch.object(gmail_service, 'get_gmail_service', return_value=mock_gmail_api):
            with patch.object(gmail_service.user_repository, 'get_user_profile', return_value=sample_user_profile):
                with patch.object(gmail_service.email_repository, 'get_processing_status', return_value=None):
                    with patch.object(gmail_service, '_parse_email_message', return_value={
                        "id": "message_123",
                        "subject": "Important Email",
                        "sender": "sender@example.com",  # Should be filtered out
                        "content": "This is email content that is long enough",
                        "thread_id": "thread_123"
                    }):
                        mock_gmail_api.users().getProfile().execute.return_value = {
                            "emailAddress": "user@example.com"
                        }
                        
                        mock_gmail_api.users().messages().list().execute.return_value = {
                            "messages": [{"id": "message_123"}]
                        }
                        
                        mock_gmail_api.users().messages().get().execute.return_value = sample_gmail_message
                        
                        result = await gmail_service.discover_emails(user_id, apply_filters=True)
                        
                        assert result["success"] == True
                        assert result["emails_discovered"] == 1
                        assert result["new_emails"] == 0  # Filtered out
                        assert result["filtered_emails"] == 1
    
    @pytest.mark.asyncio
    async def test_discover_emails_rate_limit(self, gmail_service, mock_gmail_api, sample_user_profile):
        """Test email discovery with rate limiting"""
        user_id = sample_user_profile["id"]
        
        with patch.object(gmail_service, 'get_gmail_service', return_value=mock_gmail_api):
            with patch.object(gmail_service.user_repository, 'get_user_profile', return_value=sample_user_profile):
                # Mock rate limit exceeded
                mock_gmail_api.users().messages().list().execute.side_effect = Exception("quotaExceeded")
                
                with pytest.raises(RateLimitError) as exc_info:
                    await gmail_service.discover_emails(user_id)
                
                assert "rate limit exceeded" in str(exc_info.value).lower()
    
    @pytest.mark.asyncio
    async def test_discover_emails_invalid_token(self, gmail_service, mock_gmail_api, sample_user_profile):
        """Test email discovery with invalid token"""
        user_id = sample_user_profile["id"]
        
        with patch.object(gmail_service, 'get_gmail_service', return_value=mock_gmail_api):
            with patch.object(gmail_service.user_repository, 'get_user_profile', return_value=sample_user_profile):
                # Mock invalid grant error
                mock_gmail_api.users().messages().list().execute.side_effect = Exception("invalid_grant")
                
                with pytest.raises(AuthenticationError) as exc_info:
                    await gmail_service.discover_emails(user_id)
                
                assert "invalid token" in str(exc_info.value).lower()
    
    @pytest.mark.asyncio
    async def test_process_email_success(self, gmail_service, mock_gmail_api, sample_user_profile, sample_gmail_message):
        """Test successful email processing"""
        user_id = sample_user_profile["id"]
        message_id = "message_123"
        
        with patch.object(gmail_service, 'get_gmail_service', return_value=mock_gmail_api):
            # Mock Gmail API responses
            mock_gmail_api.users().messages().get().execute.return_value = sample_gmail_message
            
            # Mock email parsing
            with patch.object(gmail_service, '_parse_email_message', return_value={
                "id": message_id,
                "subject": "Important Email",
                "sender": "sender@example.com",
                "content": "This is email content that needs processing",
                "thread_id": "thread_123"
            }):
                # Mock AI summary generation
                with patch.object(gmail_service, '_generate_ai_summary', return_value={
                    "summary": "Email summary",
                    "keywords": ["important", "urgent"],
                    "action_items": ["Review document"],
                    "cost": 0.01,
                    "tokens_used": 150
                }):
                    # Mock reply sending
                    with patch.object(gmail_service, '_send_summary_reply', return_value={"success": True}):
                        # Mock mark as read
                        with patch.object(gmail_service, '_mark_as_read', return_value=True):
                            # Mock email repository updates
                            mock_email_repo = gmail_service.email_repository
                            mock_email_repo.get_processing_status.return_value = None  # Not processed yet
                            mock_email_repo.mark_processing_started.return_value = {
                                "id": str(uuid4()),
                                "message_id": message_id,
                                "status": "processing"
                            }
                            mock_email_repo.mark_processing_completed.return_value = {
                                "id": str(uuid4()),
                                "message_id": message_id,
                                "status": "completed"
                            }
                            
                            # Mock user repository
                            mock_user_repo = gmail_service.user_repository
                            mock_user_repo.get_user_profile.return_value = sample_user_profile
                            
                            result = await gmail_service.process_email(user_id, message_id)
                            
                            assert result["success"] == True
                            assert result["message_id"] == message_id
                            assert result["summary_sent"] == True
                            assert result["processing_time"] > 0
                            assert result["credits_used"] == 1
    
    @pytest.mark.asyncio
    async def test_process_email_insufficient_credits(self, gmail_service, sample_user_profile):
        """Test email processing with insufficient credits"""
        user_id = sample_user_profile["id"]
        message_id = "message_123"
        
        # Update user profile with zero credits
        sample_user_profile["credits_remaining"] = 0
        
        mock_user_repo = gmail_service.user_repository
        mock_user_repo.get_user_profile.return_value = sample_user_profile
        
        mock_email_repo = gmail_service.email_repository
        mock_email_repo.get_processing_status.return_value = None  # Not processed yet
        
        with pytest.raises(ValidationError) as exc_info:
            await gmail_service.process_email(user_id, message_id)
        
        assert "insufficient credits" in str(exc_info.value).lower()
    
    @pytest.mark.asyncio
    async def test_process_email_bot_disabled(self, gmail_service, sample_user_profile):
        """Test email processing when bot is disabled"""
        user_id = sample_user_profile["id"]
        message_id = "message_123"
        
        # Update user profile with bot disabled
        sample_user_profile["bot_enabled"] = False
        
        mock_user_repo = gmail_service.user_repository
        mock_user_repo.get_user_profile.return_value = sample_user_profile
        
        mock_email_repo = gmail_service.email_repository
        mock_email_repo.get_processing_status.return_value = None  # Not processed yet
        
        with pytest.raises(ValidationError) as exc_info:
            await gmail_service.process_email(user_id, message_id)
        
        assert "bot is disabled" in str(exc_info.value).lower()
    
    @pytest.mark.asyncio
    async def test_process_email_already_processed(self, gmail_service, sample_user_profile):
        """Test processing email that's already been processed"""
        user_id = sample_user_profile["id"]
        message_id = "message_123"
        
        # Mock email already processed
        mock_email_repo = gmail_service.email_repository
        mock_email_repo.get_processing_status.return_value = {
            "message_id": message_id,
            "status": "completed"
        }
        
        with pytest.raises(ValidationError) as exc_info:
            await gmail_service.process_email(user_id, message_id)
        
        assert "already processed" in str(exc_info.value).lower()
    
    @pytest.mark.asyncio
    async def test_process_user_emails_batch_success(self, gmail_service, sample_user_profile):
        """Test batch processing of user emails"""
        user_id = sample_user_profile["id"]
        
        # Mock unprocessed emails
        mock_email_repo = gmail_service.email_repository
        mock_email_repo.get_unprocessed_emails.return_value = [
            {"message_id": "msg_1", "subject": "Email 1"},
            {"message_id": "msg_2", "subject": "Email 2"},
            {"message_id": "msg_3", "subject": "Email 3"}
        ]
        
        # Mock successful processing
        with patch.object(gmail_service, 'process_email') as mock_process:
            mock_process.return_value = {
                "success": True,
                "message_id": "msg_1",
                "credits_used": 1,
                "processing_time": 2.5
            }
            
            result = await gmail_service.process_user_emails(user_id, max_emails=5)
            
            assert result["success"] == True
            assert result["user_id"] == user_id
            assert result["emails_processed"] == 3
            assert result["credits_used"] == 3
            assert result["failed_emails"] == 0
            assert mock_process.call_count == 3
    
    @pytest.mark.asyncio
    async def test_process_user_emails_partial_failure(self, gmail_service, sample_user_profile):
        """Test batch processing with some failures"""
        user_id = sample_user_profile["id"]
        
        # Mock unprocessed emails
        mock_email_repo = gmail_service.email_repository
        mock_email_repo.get_unprocessed_emails.return_value = [
            {"message_id": "msg_1", "subject": "Email 1"},
            {"message_id": "msg_2", "subject": "Email 2"}
        ]
        
        # Mock mixed success/failure
        with patch.object(gmail_service, 'process_email') as mock_process:
            mock_process.side_effect = [
                {"success": True, "message_id": "msg_1", "credits_used": 1},
                APIError("Processing failed")
            ]
            
            result = await gmail_service.process_user_emails(user_id, max_emails=5)
            
            assert result["success"] == True  # Partial success
            assert result["emails_processed"] == 1
            assert result["failed_emails"] == 1
            assert len(result["errors"]) == 1
    
    @pytest.mark.asyncio
    async def test_process_user_emails_credit_limit(self, gmail_service, sample_user_profile):
        """Test batch processing stops when credits run out"""
        user_id = sample_user_profile["id"]
        
        # Set user to have only 1 credit
        sample_user_profile["credits_remaining"] = 1
        
        # Mock unprocessed emails
        mock_email_repo = gmail_service.email_repository
        mock_email_repo.get_unprocessed_emails.return_value = [
            {"message_id": "msg_1", "subject": "Email 1"},
            {"message_id": "msg_2", "subject": "Email 2"}
        ]
        
        # Mock successful processing that uses credits, then fails due to insufficient credits
        with patch.object(gmail_service, 'process_email') as mock_process:
            # First call succeeds, second call fails due to insufficient credits
            mock_process.side_effect = [
                {
                    "success": True,
                    "message_id": "msg_1",
                    "credits_used": 1
                },
                ValidationError("Insufficient credits")
            ]
            
            result = await gmail_service.process_user_emails(user_id, max_emails=5)
            
            assert result["emails_processed"] == 1
            assert result["credits_used"] == 1
            assert "insufficient credits" in result["stop_reason"]
    
    def test_apply_email_filters_exclude_sender(self, gmail_service, sample_user_profile):
        """Test email filtering by sender"""
        email_data = {
            "id": "msg_1",
            "sender": "noreply@example.com",
            "subject": "Test Email",
            "content": "This is test content"
        }
        
        filters = sample_user_profile["email_filters"]
        filters["exclude_senders"] = ["noreply@example.com"]
        
        result = gmail_service.apply_email_filters(email_data, filters)
        
        assert result["should_process"] == False
        assert result["filter_reason"] == "sender_excluded"
    
    def test_apply_email_filters_exclude_domain(self, gmail_service, sample_user_profile):
        """Test email filtering by domain"""
        email_data = {
            "id": "msg_1",
            "sender": "user@spam.com",
            "subject": "Test Email",
            "content": "This is test content"
        }
        
        filters = sample_user_profile["email_filters"]
        filters["exclude_domains"] = ["spam.com"]
        
        result = gmail_service.apply_email_filters(email_data, filters)
        
        assert result["should_process"] == False
        assert result["filter_reason"] == "domain_excluded"
    
    def test_apply_email_filters_include_keywords(self, gmail_service, sample_user_profile):
        """Test email filtering by include keywords"""
        email_data = {
            "id": "msg_1",
            "sender": "user@example.com",
            "subject": "Important Business Email",
            "content": "This is important business content that is long enough to pass the minimum length filter requirements"
        }
        
        filters = sample_user_profile["email_filters"]
        filters["include_keywords"] = ["important", "urgent"]
        
        result = gmail_service.apply_email_filters(email_data, filters)
        
        assert result["should_process"] == True
        assert result["filter_reason"] is None
    
    def test_apply_email_filters_exclude_keywords(self, gmail_service, sample_user_profile):
        """Test email filtering by exclude keywords"""
        email_data = {
            "id": "msg_1",
            "sender": "user@example.com",
            "subject": "Newsletter Update",
            "content": "This is newsletter content that is long enough to pass the minimum length filter requirements"
        }
        
        filters = sample_user_profile["email_filters"].copy()
        filters["exclude_keywords"] = ["newsletter", "unsubscribe"]
        # Remove include_keywords to test exclude_keywords specifically
        filters.pop("include_keywords", None)
        
        result = gmail_service.apply_email_filters(email_data, filters)
        
        assert result["should_process"] == False
        assert result["filter_reason"] == "keyword_excluded"
    
    def test_apply_email_filters_min_length(self, gmail_service, sample_user_profile):
        """Test email filtering by minimum length"""
        email_data = {
            "id": "msg_1",
            "sender": "user@example.com",
            "subject": "Short",
            "content": "Short"
        }
        
        filters = sample_user_profile["email_filters"].copy()
        filters["min_email_length"] = 50
        # Remove include_keywords to test min_length specifically
        filters.pop("include_keywords", None)
        
        result = gmail_service.apply_email_filters(email_data, filters)
        
        assert result["should_process"] == False
        assert result["filter_reason"] == "content_too_short"
    
    def test_parse_email_message_success(self, gmail_service, sample_gmail_message):
        """Test parsing Gmail message into usable format"""
        result = gmail_service._parse_email_message(sample_gmail_message)
        
        assert result["id"] == "message_123"
        assert result["subject"] == "Important Email"
        assert result["sender"] == "sender@example.com"
        assert result["thread_id"] == "thread_123"
        assert len(result["content"]) > 0
        assert result["received_at"] is not None
    
    def test_parse_email_message_malformed(self, gmail_service):
        """Test parsing malformed Gmail message"""
        malformed_message = {
            "id": "message_123",
            # Missing payload
        }
        
        result = gmail_service._parse_email_message(malformed_message)
        
        assert result is None
    
    def test_parse_email_message_empty_content(self, gmail_service):
        """Test parsing message with empty content"""
        empty_message = {
            "id": "message_123",
            "payload": {
                "headers": [
                    {"name": "From", "value": "sender@example.com"},
                    {"name": "Subject", "value": "Empty Email"}
                ],
                "body": {"data": ""},
                "parts": []
            }
        }
        
        result = gmail_service._parse_email_message(empty_message)
        
        assert result is None
    
    @pytest.mark.asyncio
    async def test_send_summary_reply_success(self, gmail_service, mock_gmail_api):
        """Test sending summary reply"""
        email_data = {
            "id": "message_123",
            "subject": "Important Email",
            "sender": "sender@example.com",
            "thread_id": "thread_123"
        }
        
        summary_data = {
            "summary": "This is the email summary",
            "keywords": ["important", "urgent"],
            "action_items": ["Review document"]
        }
        
        # Mock Gmail API response
        mock_gmail_api.users().messages().send().execute.return_value = {
            "id": "reply_123",
            "threadId": "thread_123"
        }
        
        result = await gmail_service._send_summary_reply(
            mock_gmail_api, email_data, summary_data, "user@example.com"
        )
        
        assert result["success"] == True
        assert result["reply_id"] == "reply_123"
        assert result["thread_id"] == "thread_123"
    
    @pytest.mark.asyncio
    async def test_send_summary_reply_failure(self, gmail_service, mock_gmail_api):
        """Test sending summary reply with API failure"""
        email_data = {
            "id": "message_123",
            "subject": "Important Email",
            "sender": "sender@example.com",
            "thread_id": "thread_123"
        }
        
        summary_data = {
            "summary": "This is the email summary",
            "keywords": ["important", "urgent"]
        }
        
        # Mock Gmail API failure
        mock_gmail_api.users().messages().send().execute.side_effect = Exception("Send failed")
        
        result = await gmail_service._send_summary_reply(
            mock_gmail_api, email_data, summary_data, "user@example.com"
        )
        
        assert result["success"] == False
        assert "Send failed" in result["error"]
    
    @pytest.mark.asyncio
    async def test_mark_as_read_success(self, gmail_service, mock_gmail_api):
        """Test marking email as read"""
        message_id = "message_123"
        
        # Create a fresh mock for the modify call
        mock_modify_call = Mock()
        mock_modify_call.execute.return_value = {
            "id": message_id,
            "labelIds": ["INBOX"]  # UNREAD removed
        }
        mock_gmail_api.users().messages().modify.return_value = mock_modify_call
        
        result = await gmail_service._mark_as_read(mock_gmail_api, message_id)
        
        assert result == True
        mock_gmail_api.users().messages().modify.assert_called_once_with(
            userId='me',
            id=message_id,
            body={'removeLabelIds': ['UNREAD']}
        )
    
    @pytest.mark.asyncio
    async def test_mark_as_read_failure(self, gmail_service, mock_gmail_api):
        """Test marking email as read with API failure"""
        message_id = "message_123"
        
        # Mock Gmail API failure
        mock_gmail_api.users().messages().modify().execute.side_effect = Exception("Modify failed")
        
        result = await gmail_service._mark_as_read(mock_gmail_api, message_id)
        
        assert result == False
    
    def test_get_queue_status_success(self, gmail_service):
        """Test getting queue status"""
        # Mock email repository
        mock_email_repo = gmail_service.email_repository
        mock_email_repo.get_processing_stats.return_value = {
            "total_pending": 5,
            "total_processing": 2,
            "total_completed": 100,
            "total_failed": 3,
            "average_processing_time": 2.5
        }
        
        result = gmail_service.get_queue_status()
        
        assert result["queue_status"] == "healthy"
        assert result["pending_jobs"] == 5
        assert result["processing_jobs"] == 2
        assert result["average_processing_time"] == 2.5
        assert "timestamp" in result
    
    def test_get_queue_status_overloaded(self, gmail_service):
        """Test getting queue status when overloaded"""
        # Mock overloaded queue
        mock_email_repo = gmail_service.email_repository
        mock_email_repo.get_processing_stats.return_value = {
            "total_pending": 100,  # High pending count
            "total_processing": 20,
            "total_completed": 50,
            "total_failed": 10,
            "average_processing_time": 10.0  # High processing time
        }
        
        result = gmail_service.get_queue_status()
        
        assert result["queue_status"] == "overloaded"
        assert result["pending_jobs"] == 100
        assert result["processing_jobs"] == 20
    
    def test_get_user_gmail_statistics(self, gmail_service, sample_user_profile):
        """Test getting user Gmail statistics"""
        user_id = sample_user_profile["id"]
        
        # Mock email repository stats
        mock_email_repo = gmail_service.email_repository
        mock_email_repo.get_processing_stats.return_value = {
            "user_id": user_id,
            "total_discovered": 50,
            "total_processed": 45,
            "total_successful": 40,
            "total_failed": 5,
            "success_rate": 0.89,
            "total_credits_used": 40,
            "average_processing_time": 2.3
        }
        
        # Mock Gmail repository connection info
        mock_gmail_repo = gmail_service.gmail_repository
        mock_gmail_repo.get_connection_info.return_value = {
            "connection_status": "connected",
            "email_address": "user@example.com",
            "created_at": "2024-01-01T00:00:00Z"
        }
        
        result = gmail_service.get_user_gmail_statistics(user_id)
        
        assert result["user_id"] == user_id
        assert result["total_discovered"] == 50
        assert result["total_processed"] == 45
        assert result["success_rate"] == 0.89
        assert result["connection_status"] == "connected"
        assert result["email_address"] == "user@example.com"
    
    def test_get_user_gmail_statistics_no_connection(self, gmail_service):
        """Test getting statistics when no Gmail connection"""
        user_id = str(uuid4())
        
        # Mock no connection
        mock_gmail_repo = gmail_service.gmail_repository
        mock_gmail_repo.get_connection_info.return_value = None
        
        result = gmail_service.get_user_gmail_statistics(user_id)
        
        assert result["user_id"] == user_id
        assert result["connection_status"] == "not_connected"
        assert result["email_address"] is None
    
    @pytest.mark.asyncio
    async def test_validate_gmail_connection_success(self, gmail_service, mock_oauth_service):
        """Test validating Gmail connection"""
        user_id = str(uuid4())
        
        # Mock successful validation
        mock_oauth_service.validate_connection.return_value = {
            "valid": True,
            "user_id": user_id,
            "validated_at": datetime.now().isoformat(),
            "error": None
        }
        
        result = await gmail_service.validate_gmail_connection(user_id)
        
        assert result["valid"] == True
        assert result["user_id"] == user_id
        assert result["error"] is None
    
    @pytest.mark.asyncio
    async def test_validate_gmail_connection_invalid(self, gmail_service, mock_oauth_service):
        """Test validating invalid Gmail connection"""
        user_id = str(uuid4())
        
        # Mock invalid validation
        mock_oauth_service.validate_connection.return_value = {
            "valid": False,
            "user_id": user_id,
            "error": "Invalid token"
        }
        
        result = await gmail_service.validate_gmail_connection(user_id)
        
        assert result["valid"] == False
        assert result["user_id"] == user_id
        assert result["error"] == "Invalid token"
    
    def test_rate_limit_check_success(self, gmail_service):
        """Test rate limit checking allows request"""
        user_id = str(uuid4())
        
        # Test first request - should be allowed with 99 remaining
        result = gmail_service.check_rate_limit(user_id, "email_discovery")
        
        assert result["allowed"] == True
        assert result["remaining"] == 99  # 100 - 1 = 99 remaining after first request
        assert result["reset_time"] is not None
    
    def test_rate_limit_check_exceeded(self, gmail_service):
        """Test rate limit checking when limit exceeded"""
        user_id = str(uuid4())
        
        # Make 100 requests to exhaust the rate limit
        for i in range(100):
            gmail_service.check_rate_limit(user_id, "email_discovery")
        
        # 101st request should be blocked
        result = gmail_service.check_rate_limit(user_id, "email_discovery")
        
        assert result["allowed"] == False
        assert result["remaining"] == 0
        assert result["reset_time"] is not None
    
    @pytest.mark.asyncio
    async def test_retry_with_backoff_success(self, gmail_service):
        """Test retry mechanism with exponential backoff"""
        # Mock function that succeeds on second try
        attempts = 0
        async def mock_function():
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise Exception("Temporary failure")
            return {"success": True}
        
        result = await gmail_service._retry_with_backoff(mock_function, max_retries=3)
        
        assert result["success"] == True
        assert attempts == 2
    
    @pytest.mark.asyncio
    async def test_retry_with_backoff_max_retries(self, gmail_service):
        """Test retry mechanism exceeds max retries"""
        # Mock function that always fails
        async def mock_function():
            raise Exception("Persistent failure")
        
        with pytest.raises(Exception) as exc_info:
            await gmail_service._retry_with_backoff(mock_function, max_retries=2)
        
        assert "Persistent failure" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_open(self, gmail_service):
        """Test circuit breaker opens after failures"""
        user_id = str(uuid4())
        
        # Mock circuit breaker in open state
        with patch.object(gmail_service, '_check_circuit_breaker', return_value={
            "state": "open",
            "failure_count": 5,
            "last_failure": datetime.now().isoformat()
        }):
            with pytest.raises(APIError) as exc_info:
                await gmail_service.discover_emails(user_id)
            
            assert "circuit breaker is open" in str(exc_info.value).lower()
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_half_open(self, gmail_service, mock_gmail_api, sample_user_profile):
        """Test circuit breaker in half-open state"""
        user_id = sample_user_profile["id"]
        
        # Mock circuit breaker in half-open state
        with patch.object(gmail_service, '_check_circuit_breaker', return_value={
            "state": "half_open",
            "failure_count": 3,
            "last_failure": (datetime.now() - timedelta(minutes=10)).isoformat()
        }):
            with patch.object(gmail_service, 'get_gmail_service', return_value=mock_gmail_api):
                with patch.object(gmail_service.user_repository, 'get_user_profile', return_value=sample_user_profile):
                    # Mock successful discovery
                    mock_gmail_api.users().getProfile().execute.return_value = {
                        "emailAddress": "user@example.com"
                    }
                    mock_gmail_api.users().messages().list().execute.return_value = {
                        "messages": []
                    }
                    
                    result = await gmail_service.discover_emails(user_id)
                    
                    assert result["success"] == True
                    # Circuit breaker should be closed after success
    
    def test_gmail_service_configuration_validation(self, gmail_service):
        """Test Gmail service configuration validation"""
        config = gmail_service.get_configuration()
        
        assert "max_emails_per_run" in config
        assert "rate_limit_requests_per_minute" in config
        assert "circuit_breaker_failure_threshold" in config
        assert "retry_max_attempts" in config
        assert "retry_backoff_multiplier" in config
        assert config["max_emails_per_run"] > 0
        assert config["rate_limit_requests_per_minute"] > 0
    
    def test_gmail_service_health_check(self, gmail_service):
        """Test Gmail service health check"""
        result = gmail_service.health_check()
        
        assert "status" in result
        assert "timestamp" in result
        assert "version" in result
        assert "dependencies" in result
        assert result["status"] in ["healthy", "degraded", "unhealthy"]
    
    @pytest.mark.asyncio
    async def test_cleanup_stale_jobs(self, gmail_service):
        """Test cleaning up stale processing jobs"""
        # Mock stale jobs
        mock_email_repo = gmail_service.email_repository
        mock_email_repo.get_stale_processing_emails.return_value = [
            {"message_id": "msg_1", "user_id": str(uuid4())},
            {"message_id": "msg_2", "user_id": str(uuid4())}
        ]
        
        mock_email_repo.mark_processing_timeout.return_value = {
            "status": "failed",
            "processing_result": {"error": "processing_timeout"}
        }
        
        result = await gmail_service.cleanup_stale_jobs()
        
        assert result["cleaned_jobs"] == 2
        assert result["success"] == True
        assert mock_email_repo.mark_processing_timeout.call_count == 2
    
    @pytest.mark.asyncio
    async def test_bulk_user_processing(self, gmail_service):
        """Test bulk processing for multiple users"""
        user_ids = [str(uuid4()) for _ in range(3)]
        
        # Mock successful processing for all users
        with patch.object(gmail_service, 'process_user_emails') as mock_process:
            mock_process.return_value = {
                "success": True,
                "emails_processed": 2,
                "credits_used": 2
            }
            
            result = await gmail_service.bulk_process_users(user_ids)
            
            assert result["total_users"] == 3
            assert result["successful_users"] == 3
            assert result["failed_users"] == 0
            assert result["total_emails_processed"] == 6
            assert result["total_credits_used"] == 6
    
    @pytest.mark.asyncio
    async def test_bulk_user_processing_partial_failure(self, gmail_service):
        """Test bulk processing with some user failures"""
        user_ids = [str(uuid4()) for _ in range(3)]
        
        # Mock mixed success/failure
        with patch.object(gmail_service, 'process_user_emails') as mock_process:
            mock_process.side_effect = [
                {"success": True, "emails_processed": 2, "credits_used": 2},
                APIError("Processing failed"),
                {"success": True, "emails_processed": 1, "credits_used": 1}
            ]
            
            result = await gmail_service.bulk_process_users(user_ids)
            
            assert result["total_users"] == 3
            assert result["successful_users"] == 2
            assert result["failed_users"] == 1
            assert result["total_emails_processed"] == 3
            assert result["total_credits_used"] == 3
    
    def test_generate_gmail_query_basic(self, gmail_service):
        """Test generating basic Gmail query"""
        filters = {
            "exclude_senders": [],
            "exclude_domains": [],
            "include_keywords": [],
            "exclude_keywords": []
        }
        
        result = gmail_service._generate_gmail_query(filters)
        
        assert "is:unread" in result
        assert "-subject:\"🤖 AI Summary:\"" in result
    
    def test_generate_gmail_query_with_filters(self, gmail_service):
        """Test generating Gmail query with filters"""
        filters = {
            "exclude_senders": ["noreply@example.com"],
            "exclude_domains": ["spam.com"],
            "include_keywords": ["important"],
            "exclude_keywords": ["newsletter"]
        }
        
        result = gmail_service._generate_gmail_query(filters)
        
        assert "is:unread" in result
        assert "-from:noreply@example.com" in result
        assert "-from:*@spam.com" in result
        assert "(important)" in result
        assert "-newsletter" in result
    
    @pytest.mark.parametrize("error_type", ["quotaExceeded", "rateLimitExceeded", "userRateLimitExceeded"])
    def test_handle_gmail_api_errors(self, gmail_service, error_type):
        """Test handling different Gmail API errors"""
        error = Exception(error_type)
        
        result = gmail_service._handle_gmail_api_error(error)
        
        assert result["error_type"] == "rate_limit"
        assert result["retry_after"] > 0
        assert result["permanent"] == False
    
    @pytest.mark.parametrize("error_type", ["invalid_grant", "unauthorized", "forbidden"])
    def test_handle_gmail_auth_errors(self, gmail_service, error_type):
        """Test handling Gmail authentication errors"""
        error = Exception(error_type)
        
        result = gmail_service._handle_gmail_api_error(error)
        
        assert result["error_type"] == "authentication"
        assert result["permanent"] == True
        assert result["action"] == "reauth_required"
    
    def test_email_content_extraction_html(self, gmail_service):
        """Test extracting content from HTML email"""
        html_content = "<html><body><p>This is <b>HTML</b> content</p></body></html>"
        
        result = gmail_service._extract_email_content(html_content, "text/html")
        
        assert "This is HTML content" in result
        assert "<html>" not in result
        assert "<b>" not in result
    
    def test_email_content_extraction_plain(self, gmail_service):
        """Test extracting content from plain text email"""
        plain_content = "This is plain text content"
        
        result = gmail_service._extract_email_content(plain_content, "text/plain")
        
        assert result == "This is plain text content"
    
    def test_email_content_extraction_long(self, gmail_service):
        """Test extracting content from very long email"""
        long_content = "This is a very long email content. " * 1000
        
        result = gmail_service._extract_email_content(long_content, "text/plain")
        
        # Should be truncated
        assert len(result) <= 5000  # Assuming max content length
        assert result.endswith("...")
    
    @pytest.mark.asyncio
    async def test_concurrent_processing_safety(self, gmail_service, sample_user_profile):
        """Test concurrent processing doesn't cause race conditions"""
        user_id = sample_user_profile["id"]
        
        # Mock concurrent processing attempts
        with patch.object(gmail_service, 'process_email') as mock_process:
            mock_process.return_value = {
                "success": True,
                "message_id": "msg_1",
                "credits_used": 1
            }
            
            # Start multiple processing tasks
            import asyncio
            tasks = [
                gmail_service.process_user_emails(user_id, max_emails=1)
                for _ in range(3)
            ]
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Only one should succeed, others should be blocked
            successful_results = [r for r in results if not isinstance(r, Exception)]
            assert len(successful_results) <= 1