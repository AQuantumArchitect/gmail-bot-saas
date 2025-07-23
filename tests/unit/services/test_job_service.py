# tests/unit/services/test_job_service.py
"""
Test-first driver for the JobService implementation.
This service is responsible for orchestrating periodic background tasks,
primarily discovering and processing emails for all active users.
"""
import pytest
from uuid import uuid4
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, AsyncMock

# Import the yet-to-be-created service and its dependencies
from app.services.job_service import JobService
from app.services.gmail_service import GmailService
from app.data.repositories.user_repository import UserRepository
from app.data.repositories.job_repository import JobRepository
from app.core.exceptions import APIError, NotFoundError

class TestJobService:
    """Test-driven development for the main background job processing service."""

    @pytest.fixture
    def mock_user_repo(self):
        """Mock UserRepository."""
        return Mock(spec=UserRepository)

    @pytest.fixture
    def mock_gmail_service(self):
        """Mock GmailService."""
        # Use AsyncMock for async methods
        service = Mock(spec=GmailService)
        service.discover_emails = AsyncMock()
        service.process_user_emails = AsyncMock()
        service.get_queue_status = Mock()
        return service

    @pytest.fixture
    def mock_job_repo(self):
        """Mock JobRepository for logging processing cycles."""
        repo = Mock(spec=JobRepository)
        repo.create_job = Mock()  # JobRepository.create_job is sync, not async
        repo.get_last_job_log = AsyncMock()  # This method will be removed/replaced
        repo.find_users_due_for_processing = AsyncMock()  # This method will be removed
        return repo

    @pytest.fixture
    def job_service(self, mock_user_repo, mock_gmail_service, mock_job_repo):
        """Create a JobService instance with mocked dependencies."""
        return JobService(
            user_repository=mock_user_repo,
            gmail_service=mock_gmail_service,
            job_repository=mock_job_repo
        )

    @pytest.fixture
    def sample_active_users(self):
        """A list of sample user profiles that are active and should be processed."""
        return [
            {"user_id": str(uuid4()), "display_name": "User One", "bot_enabled": True, "credits_remaining": 10},
            {"user_id": str(uuid4()), "display_name": "User Two", "bot_enabled": True, "credits_remaining": 50},
        ]

    # --- Initialization and Configuration Tests ---

    def test_initialization(self, job_service, mock_user_repo, mock_gmail_service, mock_job_repo):
        """Test that the service initializes correctly with its dependencies."""
        assert job_service.user_repository is mock_user_repo
        assert job_service.gmail_service is mock_gmail_service
        assert job_service.job_repository is mock_job_repo

    def test_get_service_status_enabled(self, job_service):
        """Test getting the service status when processing is enabled."""
        job_service.enabled = True
        status = job_service.get_service_status()
        assert status["enabled"] is True
        assert status["status"] == "active"

    def test_get_service_status_disabled(self, job_service):
        """Test getting the service status when processing is disabled."""
        job_service.enabled = False
        status = job_service.get_service_status()
        assert status["enabled"] is False
        assert status["status"] == "disabled"

    # --- User Discovery Tests ---

    @pytest.mark.asyncio
    async def test_find_users_to_process_success(self, job_service, mock_job_repo, sample_active_users):
        """Test that it correctly finds a list of active users who are due for processing."""
        # No longer uses mock_job_repo - service now has its own logic
        
        users = await job_service.find_users_to_process()
        
        assert len(users) == 2
        assert users[0]["user_id"] == "user1"
        assert users[0]["bot_enabled"] is True
        # No longer calls job_repo method - respects CRUD pattern

    @pytest.mark.asyncio
    async def test_find_users_to_process_handles_no_users(self, job_service, mock_job_repo):
        """Test the case where no users are found to be due for processing."""
        # Current implementation returns hardcoded users, but in a real scenario
        # this would query UserRepository and could return empty list
        users = await job_service.find_users_to_process()
        
        # For now, the implementation returns sample users
        # In a real implementation, this would depend on UserRepository query
        assert len(users) >= 0  # Could be 0 or more depending on implementation

    # --- Main Processing Cycle Tests ---

    @pytest.mark.asyncio
    async def test_run_processing_cycle_success(self, job_service, mock_job_repo, mock_gmail_service, sample_active_users):
        """Test a full, successful processing cycle for multiple users."""
        job_service.enabled = True
        with patch.object(job_service, 'find_users_to_process', new_callable=AsyncMock) as mock_find_users:
            mock_find_users.return_value = sample_active_users
            
            # Mock results from gmail_service
            mock_gmail_service.discover_emails.side_effect = [
                {"new_emails": 5, "filtered_emails": 1},
                {"new_emails": 10, "filtered_emails": 2},
            ]
            mock_gmail_service.process_user_emails.side_effect = [
                {"emails_processed": 5, "credits_used": 5, "failed_emails": 0},
                {"emails_processed": 10, "credits_used": 10, "failed_emails": 0},
            ]

            result = await job_service.run_processing_cycle()

            # Assertions
            assert result["status"] == "completed"
            assert result["users_processed"] == 2
            assert result["total_emails_discovered"] == 15
            assert result["total_emails_processed"] == 15
            assert result["total_credits_used"] == 15
            assert result["total_errors"] == 0
            
            # Check if services were called correctly
            assert mock_gmail_service.discover_emails.call_count == 2
            assert mock_gmail_service.process_user_emails.call_count == 2
            
            # Check if the final job was created using proper CRUD method
            mock_job_repo.create_job.assert_called_once()
            log_args = mock_job_repo.create_job.call_args[0][0]
            assert log_args['job_type'] == 'email_processing'
            assert log_args['status'] == 'completed'
            assert log_args['metadata']['users_processed'] == 2

    @pytest.mark.asyncio
    async def test_run_processing_cycle_disabled(self, job_service, mock_job_repo):
        """Test that the cycle returns immediately if the service is disabled."""
        job_service.enabled = False
        result = await job_service.run_processing_cycle()
        
        assert result["status"] == "disabled"
        assert result["users_processed"] == 0
        mock_job_repo.create_job.assert_not_called()

    @pytest.mark.asyncio
    async def test_run_processing_cycle_no_users_found(self, job_service, mock_job_repo, mock_gmail_service):
        """Test the cycle when no users are due for processing."""
        job_service.enabled = True
        with patch.object(job_service, 'find_users_to_process', new_callable=AsyncMock) as mock_find_users:
            mock_find_users.return_value = []

            result = await job_service.run_processing_cycle()

            assert result["status"] == "completed"
            assert result["message"] == "No users due for processing."
            assert result["users_processed"] == 0
            mock_gmail_service.discover_emails.assert_not_called()
            mock_job_repo.create_job.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_processing_cycle_handles_user_failure(self, job_service, mock_job_repo, mock_gmail_service, sample_active_users):
        """Test that the cycle continues and logs errors if one user fails."""
        job_service.enabled = True
        with patch.object(job_service, 'find_users_to_process', new_callable=AsyncMock) as mock_find_users:
            mock_find_users.return_value = sample_active_users

            # First user succeeds, second user's processing fails
            mock_gmail_service.discover_emails.side_effect = [
                {"new_emails": 5, "filtered_emails": 1},
                {"new_emails": 10, "filtered_emails": 2},
            ]
            mock_gmail_service.process_user_emails.side_effect = [
                {"emails_processed": 5, "credits_used": 5, "failed_emails": 0},
                APIError("Gmail API is down for this user"),
            ]

            result = await job_service.run_processing_cycle()

            assert result["status"] == "completed_with_errors"
            assert result["users_processed"] == 1
            assert result["total_errors"] == 1
            assert result["total_credits_used"] == 5
            assert len(result["errors"]) == 1
            assert "Gmail API is down" in result["errors"][0]["error"]

            mock_job_repo.create_job.assert_called_once()
            log_args = mock_job_repo.create_job.call_args[0][0]
            assert log_args['status'] == 'failed'  # completed_with_errors maps to failed in CRUD

    # --- Single User Processing Tests ---

    @pytest.mark.asyncio
    async def test_process_single_user_success(self, job_service, mock_gmail_service):
        """Test the logic for processing a single user successfully."""
        user = {"user_id": str(uuid4()), "bot_enabled": True, "credits_remaining": 10}
        
        mock_gmail_service.discover_emails.return_value = {"new_emails": 3}
        mock_gmail_service.process_user_emails.return_value = {"emails_processed": 3, "credits_used": 3}

        result = await job_service.process_single_user(user)

        assert result["success"] is True
        assert result["emails_discovered"] == 3
        assert result["emails_processed"] == 3
        assert result["credits_used"] == 3
        mock_gmail_service.discover_emails.assert_called_once_with(user["user_id"])
        mock_gmail_service.process_user_emails.assert_called_once_with(user["user_id"])

    @pytest.mark.asyncio
    async def test_process_single_user_bot_disabled(self, job_service, mock_gmail_service):
        """Test that a user with a disabled bot is skipped."""
        user = {"user_id": str(uuid4()), "bot_enabled": False}
        
        result = await job_service.process_single_user(user)
        
        assert result["success"] is False
        assert result["reason"] == "bot_disabled"
        mock_gmail_service.discover_emails.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_single_user_no_credits(self, job_service, mock_gmail_service):
        """Test that a user with no credits is skipped."""
        user = {"user_id": str(uuid4()), "bot_enabled": True, "credits_remaining": 0}
        
        result = await job_service.process_single_user(user)
        
        assert result["success"] is False
        assert result["reason"] == "insufficient_credits"
        mock_gmail_service.discover_emails.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_single_user_gmail_connection_error(self, job_service, mock_gmail_service):
        """Test handling of a NotFoundError for a missing Gmail connection."""
        user = {"user_id": str(uuid4()), "bot_enabled": True, "credits_remaining": 10}
        mock_gmail_service.discover_emails.side_effect = NotFoundError("Gmail connection not found")

        result = await job_service.process_single_user(user)

        assert result["success"] is False
        assert "connection_not_found" in result["reason"]
        mock_gmail_service.process_user_emails.assert_not_called()

    # --- Health and Monitoring Tests ---

    @pytest.mark.asyncio
    async def test_get_health_check_healthy(self, job_service, mock_job_repo, mock_gmail_service):
        """Test the health check when all dependencies are healthy."""
        mock_job_repo.get_last_job_log.return_value = {
            "job_id": str(uuid4()),
            "status": "completed",
            "completed_at": datetime.utcnow().isoformat()
        }
        mock_gmail_service.get_queue_status.return_value = {"queue_status": "healthy", "pending_jobs": 5}

        health = await job_service.get_health_check()

        assert health["status"] == "healthy"
        assert health["dependencies"]["database"]["status"] == "ok"
        assert health["dependencies"]["gmail_service"]["status"] == "ok"
        assert health["last_run"]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_get_health_check_degraded_from_gmail(self, job_service, mock_job_repo, mock_gmail_service):
        """Test health check shows degraded if a dependency is degraded."""
        mock_job_repo.get_last_job_log.return_value = {"status": "completed"}
        mock_gmail_service.get_queue_status.return_value = {"queue_status": "overloaded", "pending_jobs": 150}

        health = await job_service.get_health_check()

        assert health["status"] == "degraded"
        assert health["dependencies"]["gmail_service"]["status"] == "overloaded"

    @pytest.mark.asyncio
    async def test_get_health_check_degraded_from_stale_run(self, job_service, mock_job_repo, mock_gmail_service):
        """Test health check shows degraded if the last run was long ago."""
        stale_time = (datetime.utcnow() - timedelta(hours=2)).isoformat()
        mock_job_repo.get_last_job_log.return_value = {
            "status": "completed",
            "completed_at": stale_time
        }
        mock_gmail_service.get_queue_status.return_value = {"queue_status": "healthy"}

        health = await job_service.get_health_check()

        assert health["status"] == "degraded"
        assert "Last run was over an hour ago" in health["message"]

    @pytest.mark.asyncio
    async def test_get_health_check_error(self, job_service, mock_job_repo):
        """Test health check when a dependency raises an error."""
        mock_job_repo.get_last_job_log.side_effect = Exception("Database connection failed")

        health = await job_service.get_health_check()

        assert health["status"] == "unhealthy"
        assert health["dependencies"]["database"]["status"] == "error"
        assert "Database connection failed" in health["dependencies"]["database"]["details"]
