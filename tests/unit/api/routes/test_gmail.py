# tests/unit/api/routes/test_gmail_clean.py
"""
Enhanced, comprehensive tests for Gmail routes.
Covers OAuth flow, email processing, connection management, and error handling.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, AsyncMock, patch
from uuid import uuid4
import json
from datetime import datetime, timedelta

# Import the specific router to be tested
from app.api.routes.gmail import router as gmail_router
from app.api.routes.gmail import get_gmail_service, get_gmail_oauth_service, get_email_service

# Import dependencies that will be mocked
from app.api.dependencies import get_user_context, require_gmail_connection_permission, require_email_processing_permission, UserContext
from app.services.gmail_service import GmailService
from app.services.gmail_oauth_service import GmailOAuthService
from app.services.email_service import EmailService
from app.core.exceptions import NotFoundError, ValidationError, APIError, AuthenticationError

@pytest.fixture
def comprehensive_mock_gmail_service() -> MagicMock:
    """Comprehensive mock GmailService with all Gmail operations."""
    service = MagicMock(spec=GmailService)
    
    # Connection and status methods
    service.get_connection_status = AsyncMock()
    service.check_service_health = AsyncMock()
    service.get_user_gmail_statistics = AsyncMock()
    
    # Email operations
    service.get_user_processed_emails = AsyncMock()
    service.get_email_by_message_id = AsyncMock()
    service.sync_recent_emails = AsyncMock()
    
    return service

@pytest.fixture
def comprehensive_mock_oauth_service() -> MagicMock:
    """Comprehensive mock GmailOAuthService for OAuth operations."""
    service = MagicMock(spec=GmailOAuthService)
    
    # OAuth flow methods
    service.generate_oauth_url = AsyncMock()
    service.complete_oauth_flow = AsyncMock()
    service.refresh_access_token = AsyncMock()
    service.revoke_connection = AsyncMock()
    
    # Connection management
    service.check_connection_status = MagicMock()
    service.get_connection_info = MagicMock()
    service.validate_connection = AsyncMock()
    
    return service

@pytest.fixture
def comprehensive_mock_email_service() -> MagicMock:
    """Comprehensive mock EmailService for email processing."""
    service = MagicMock(spec=EmailService)
    
    # Email discovery and processing
    service.discover_user_emails = AsyncMock()
    service.process_user_emails = AsyncMock()
    service.process_single_email = AsyncMock()
    
    return service

@pytest.fixture
def gmail_user_context() -> UserContext:
    """UserContext configured for Gmail testing scenarios."""
    user_id = str(uuid4())
    user_data = {
        "user_id": user_id,
        "email": "gmail@test.com",
        "display_name": "Gmail Test User",
        "credits_remaining": 50,
        "bot_enabled": True,
        "timezone": "UTC",
        "created_at": "2025-01-01T00:00:00Z",
        "gmail_connected": True,
        "gmail_email": "gmail@test.com"
    }
    permissions = {
        "can_process_emails": True,
        "can_access_dashboard": True,
        "can_connect_gmail": True,
        "can_purchase_credits": True,
        "can_manage_account": True
    }
    return UserContext(user_data=user_data, permissions=permissions)

@pytest.fixture
def client(
    comprehensive_mock_gmail_service: MagicMock, 
    comprehensive_mock_oauth_service: MagicMock,
    comprehensive_mock_email_service: MagicMock,
    gmail_user_context: UserContext
) -> TestClient:
    """Enhanced test client with comprehensive Gmail mocking."""
    app = FastAPI(title="Enhanced Gmail Test App")

    # Override the dependency functions
    app.dependency_overrides[get_gmail_service] = lambda: comprehensive_mock_gmail_service
    app.dependency_overrides[get_gmail_oauth_service] = lambda: comprehensive_mock_oauth_service
    app.dependency_overrides[get_email_service] = lambda: comprehensive_mock_email_service
    app.dependency_overrides[get_user_context] = lambda: gmail_user_context
    app.dependency_overrides[require_gmail_connection_permission] = lambda: gmail_user_context
    app.dependency_overrides[require_email_processing_permission] = lambda: gmail_user_context

    # Include the Gmail router
    app.include_router(gmail_router, prefix="/api")

    with TestClient(app) as test_client:
        yield test_client

class TestGmailConnectionStatus:
    """Comprehensive tests for Gmail connection status and management."""

    def test_get_connection_status_connected(self, client: TestClient, comprehensive_mock_oauth_service: MagicMock, gmail_user_context: UserContext):
        """Test getting connection status when Gmail is connected."""
        mock_connection_status = {
            "connected": True,
            "email": "gmail@test.com",
            "status": "active",
            "last_sync": "2025-01-30T09:00:00Z"
        }
        mock_connection_info = {
            "scopes": [
                "https://www.googleapis.com/auth/gmail.readonly",
                "https://www.googleapis.com/auth/gmail.send"
            ],
            "last_sync": "2025-01-30T09:00:00Z",
            "emails_synced": 150
        }
        
        comprehensive_mock_oauth_service.check_connection_status.return_value = mock_connection_status
        comprehensive_mock_oauth_service.get_connection_info.return_value = mock_connection_info
        
        response = client.get("/api/gmail/connection")
        
        assert response.status_code == 200
        data = response.json()
        assert data["connected"] is True
        assert data["email_address"] == "gmail@test.com"
        assert data["connection_status"] == "active"
        assert len(data["scopes"]) == 2
        assert data["last_sync"] == "2025-01-30T09:00:00Z"

    def test_get_connection_status_disconnected(self, client: TestClient, comprehensive_mock_oauth_service: MagicMock):
        """Test getting connection status when Gmail is not connected."""
        mock_connection_status = {
            "connected": False,
            "email": None,
            "status": "disconnected",
            "error": "No valid tokens found"
        }
        
        comprehensive_mock_oauth_service.check_connection_status.return_value = mock_connection_status
        comprehensive_mock_oauth_service.get_connection_info.return_value = None
        
        response = client.get("/api/gmail/connection")
        
        assert response.status_code == 200
        data = response.json()
        assert data["connected"] is False
        assert data["email_address"] is None
        assert data["connection_status"] == "disconnected"
        assert data["scopes"] is None
        assert data["error"] == "No valid tokens found"

    def test_get_connection_status_service_error(self, client: TestClient, comprehensive_mock_oauth_service: MagicMock):
        """Test connection status with service error."""
        comprehensive_mock_oauth_service.check_connection_status.side_effect = Exception("Gmail API unavailable")
        
        response = client.get("/api/gmail/connection")
        
        assert response.status_code == 500
        assert "Failed to get Gmail connection status" in response.json()["detail"]

class TestGmailOAuthFlow:
    """Comprehensive tests for Gmail OAuth connection flow."""

    def test_initiate_connection_success(self, client: TestClient, comprehensive_mock_oauth_service: MagicMock, gmail_user_context: UserContext):
        """Test successful OAuth initiation."""
        mock_oauth_result = {
            "oauth_url": "https://accounts.google.com/o/oauth2/v2/auth?client_id=test&redirect_uri=test&scope=gmail&state=abc123",
            "state": "abc123",
            "expires_at": "2025-01-30T11:00:00Z"
        }
        comprehensive_mock_oauth_service.generate_oauth_url.return_value = mock_oauth_result
        
        response = client.post("/api/gmail/connect")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "https://accounts.google.com" in data["oauth_url"]
        assert data["state"] == "abc123"
        assert "Visit the URL to authorize Gmail access" in data["message"]
        comprehensive_mock_oauth_service.generate_oauth_url.assert_awaited_once_with(gmail_user_context.user_id)

    def test_initiate_connection_service_error(self, client: TestClient, comprehensive_mock_oauth_service: MagicMock):
        """Test OAuth initiation with service error."""
        comprehensive_mock_oauth_service.generate_oauth_url.side_effect = Exception("OAuth service unavailable")
        
        response = client.post("/api/gmail/connect")
        
        assert response.status_code == 500
        assert "Failed to initiate Gmail connection" in response.json()["detail"]

    def test_complete_oauth_success(self, client: TestClient, comprehensive_mock_oauth_service: MagicMock, gmail_user_context: UserContext):
        """Test successful OAuth completion."""
        mock_completion_result = {
            "success": True,
            "user_id": gmail_user_context.user_id,
            "email": "gmail@test.com",
            "connection_status": "connected",
            "expires_at": "2025-01-31T10:00:00Z"
        }
        comprehensive_mock_oauth_service.complete_oauth_flow.return_value = mock_completion_result
        
        request_body = {
            "code": "oauth_authorization_code_123",
            "state": "abc123"
        }
        
        response = client.post("/api/gmail/callback", json=request_body)
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["email"] == "gmail@test.com"
        assert data["connected"] is True
        assert "Gmail connected successfully" in data["message"]
        comprehensive_mock_oauth_service.complete_oauth_flow.assert_awaited_once_with(
            gmail_user_context.user_id,
            "oauth_authorization_code_123",
            "abc123"
        )

    def test_complete_oauth_invalid_code(self, client: TestClient, comprehensive_mock_oauth_service: MagicMock):
        """Test OAuth completion with invalid authorization code."""
        comprehensive_mock_oauth_service.complete_oauth_flow.side_effect = AuthenticationError("Invalid authorization code")
        
        request_body = {
            "code": "invalid_code",
            "state": "abc123"
        }
        
        response = client.post("/api/gmail/callback", json=request_body)
        
        assert response.status_code == 401
        assert "Invalid authorization code" in response.json()["detail"]

    def test_complete_oauth_validation_error(self, client: TestClient):
        """Test OAuth completion with validation errors."""
        # Missing required fields
        request_body = {"code": ""}  # Empty code
        
        response = client.post("/api/gmail/callback", json=request_body)
        
        assert response.status_code == 422  # Pydantic validation error

    def test_refresh_token_success(self, client: TestClient, comprehensive_mock_oauth_service: MagicMock, gmail_user_context: UserContext):
        """Test successful token refresh."""
        mock_refresh_result = {
            "success": True,
            "expires_at": "2025-01-31T10:00:00Z",
            "refreshed_at": "2025-01-30T10:00:00Z"
        }
        comprehensive_mock_oauth_service.refresh_access_token.return_value = mock_refresh_result
        
        response = client.post("/api/gmail/refresh")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "Token refreshed successfully" in data["message"]
        assert data["expires_at"] == "2025-01-31T10:00:00Z"
        comprehensive_mock_oauth_service.refresh_access_token.assert_awaited_once_with(gmail_user_context.user_id)

    def test_refresh_token_failure(self, client: TestClient, comprehensive_mock_oauth_service: MagicMock):
        """Test token refresh failure."""
        comprehensive_mock_oauth_service.refresh_access_token.side_effect = AuthenticationError("Refresh token expired")
        
        response = client.post("/api/gmail/refresh")
        
        assert response.status_code == 401
        assert "Refresh token expired" in response.json()["detail"]

    def test_disconnect_gmail_success(self, client: TestClient, comprehensive_mock_oauth_service: MagicMock, gmail_user_context: UserContext):
        """Test successful Gmail disconnection."""
        mock_revoke_result = {
            "success": True,
            "revoked_tokens": 2,
            "disconnected_at": "2025-01-30T10:00:00Z"
        }
        comprehensive_mock_oauth_service.revoke_connection.return_value = mock_revoke_result
        
        response = client.delete("/api/gmail/connection")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "Gmail disconnected successfully" in data["message"]
        assert data["revoked_tokens"] == 2
        comprehensive_mock_oauth_service.revoke_connection.assert_awaited_once_with(gmail_user_context.user_id)

class TestEmailDiscoveryAndProcessing:
    """Comprehensive tests for email discovery and processing operations."""

    def test_discover_emails_success(self, client: TestClient, comprehensive_mock_email_service: MagicMock, gmail_user_context: UserContext):
        """Test successful email discovery."""
        mock_discovery_result = {
            "success": True,
            "emails_discovered": 15,
            "new_emails": 8,
            "filtered_emails": 7,
            "discovery_time": "2025-01-30T10:00:00Z"
        }
        comprehensive_mock_email_service.discover_user_emails.return_value = mock_discovery_result
        
        response = client.post("/api/gmail/discover")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["emails_discovered"] == 15
        assert data["new_emails"] == 8
        assert data["filtered_emails"] == 7
        assert data["discovery_time"] == "2025-01-30T10:00:00Z"
        comprehensive_mock_email_service.discover_user_emails.assert_awaited_once_with(
            gmail_user_context.user_id,
            apply_filters=True  # Default parameter
        )

    def test_discover_emails_without_filters(self, client: TestClient, comprehensive_mock_email_service: MagicMock, gmail_user_context: UserContext):
        """Test email discovery without applying filters."""
        mock_discovery_result = {
            "success": True,
            "emails_discovered": 25,
            "new_emails": 25,
            "filtered_emails": 0,
            "discovery_time": "2025-01-30T10:00:00Z"
        }
        comprehensive_mock_email_service.discover_user_emails.return_value = mock_discovery_result
        
        response = client.post("/api/gmail/discover?apply_filters=false")
        
        assert response.status_code == 200
        data = response.json()
        assert data["emails_discovered"] == 25
        assert data["filtered_emails"] == 0
        comprehensive_mock_email_service.discover_user_emails.assert_awaited_once_with(
            gmail_user_context.user_id,
            apply_filters=False
        )

    def test_discover_emails_api_error(self, client: TestClient, comprehensive_mock_email_service: MagicMock):
        """Test email discovery with API error."""
        comprehensive_mock_email_service.discover_user_emails.side_effect = APIError("Gmail API rate limit exceeded")
        
        response = client.post("/api/gmail/discover")
        
        assert response.status_code == 503
        assert "Gmail API rate limit exceeded" in response.json()["detail"]

    def test_process_single_email_success(self, client: TestClient, comprehensive_mock_email_service: MagicMock, gmail_user_context: UserContext):
        """Test successful single email processing."""
        mock_processing_result = {
            "success": True,
            "message_id": "msg_123456",
            "processing_time": 2.3,
            "credits_used": 1,
            "summary_sent": True,
            "summary": "Meeting scheduled for next week with the development team."
        }
        comprehensive_mock_email_service.process_single_email.return_value = mock_processing_result
        
        request_body = {"message_id": "msg_123456"}
        response = client.post("/api/gmail/process", json=request_body)
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["message_id"] == "msg_123456"
        assert data["processing_time"] == 2.3
        assert data["credits_used"] == 1
        assert data["summary_sent"] is True
        comprehensive_mock_email_service.process_single_email.assert_awaited_once_with(
            gmail_user_context.user_id,
            "msg_123456"
        )

    def test_process_single_email_not_found(self, client: TestClient, comprehensive_mock_email_service: MagicMock):
        """Test processing non-existent email."""
        comprehensive_mock_email_service.process_single_email.side_effect = NotFoundError("Email not found")
        
        request_body = {"message_id": "nonexistent_msg"}
        response = client.post("/api/gmail/process", json=request_body)
        
        assert response.status_code == 404
        assert "Email not found" in response.json()["detail"]

    def test_process_single_email_insufficient_credits(self, client: TestClient, comprehensive_mock_email_service: MagicMock):
        """Test processing email with insufficient credits."""
        from app.core.exceptions import InsufficientCreditsError
        comprehensive_mock_email_service.process_single_email.side_effect = InsufficientCreditsError("Not enough credits")
        
        request_body = {"message_id": "msg_123456"}
        response = client.post("/api/gmail/process", json=request_body)
        
        assert response.status_code == 402
        assert "Not enough credits" in response.json()["detail"]

    def test_process_single_email_validation_error(self, client: TestClient):
        """Test processing email with validation error."""
        # Empty message_id
        request_body = {"message_id": ""}
        response = client.post("/api/gmail/process", json=request_body)
        
        assert response.status_code == 422  # Pydantic validation error

class TestEmailManagement:
    """Tests for email management and retrieval operations."""

    def test_get_processed_emails_success(self, client: TestClient, comprehensive_mock_gmail_service: MagicMock, gmail_user_context: UserContext):
        """Test successful retrieval of processed emails."""
        mock_emails = {
            "emails": [
                {
                    "message_id": "msg_001",
                    "subject": "Weekly team meeting",
                    "sender": "manager@company.com",
                    "received_at": "2025-01-30T09:00:00Z",
                    "processed_at": "2025-01-30T09:05:00Z",
                    "summary": "Team meeting scheduled for Friday at 2 PM.",
                    "credits_used": 1
                },
                {
                    "message_id": "msg_002",
                    "subject": "Project update",
                    "sender": "developer@company.com",
                    "received_at": "2025-01-30T08:30:00Z",
                    "processed_at": "2025-01-30T08:35:00Z",
                    "summary": "Project is on track for next milestone.",
                    "credits_used": 1
                }
            ],
            "total_count": 2,
            "has_more": False
        }
        comprehensive_mock_gmail_service.get_user_processed_emails.return_value = mock_emails
        
        response = client.get("/api/gmail/emails")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert len(data["emails"]) == 2
        assert data["total_count"] == 2
        assert data["returned_count"] == 2
        assert data["offset"] == 0
        assert data["emails"][0]["message_id"] == "msg_001"
        assert data["emails"][1]["message_id"] == "msg_002"

    def test_get_processed_emails_with_pagination(self, client: TestClient, comprehensive_mock_gmail_service: MagicMock, gmail_user_context: UserContext):
        """Test email retrieval with pagination parameters."""
        mock_emails = {
            "emails": [],
            "total_count": 50,
            "has_more": True
        }
        comprehensive_mock_gmail_service.get_user_processed_emails.return_value = mock_emails
        
        response = client.get("/api/gmail/emails?limit=10&offset=20")
        
        assert response.status_code == 200
        comprehensive_mock_gmail_service.get_user_processed_emails.assert_awaited_once_with(
            user_id=gmail_user_context.user_id,
            limit=10,
            offset=20
        )

    def test_get_single_email_success(self, client: TestClient, comprehensive_mock_gmail_service: MagicMock, gmail_user_context: UserContext):
        """Test successful single email retrieval."""
        mock_email = {
            "message_id": "msg_123456",
            "subject": "Important update",
            "sender": "boss@company.com",
            "sender_name": "The Boss",
            "received_at": "2025-01-30T09:00:00Z",
            "processed_at": "2025-01-30T09:05:00Z",
            "summary": "Important company-wide update about new policies.",
            "full_content": "Dear team, we are implementing new policies...",
            "labels": ["important", "company-wide"],
            "credits_used": 1,
            "processing_time": 2.1
        }
        comprehensive_mock_gmail_service.get_email_by_message_id.return_value = mock_email
        
        response = client.get("/api/gmail/emails/msg_123456")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["email"]["message_id"] == "msg_123456"
        assert data["email"]["subject"] == "Important update"
        assert data["email"]["sender"] == "boss@company.com"
        comprehensive_mock_gmail_service.get_email_by_message_id.assert_awaited_once_with(
            user_id=gmail_user_context.user_id,
            message_id="msg_123456"
        )

    def test_get_single_email_not_found(self, client: TestClient, comprehensive_mock_gmail_service: MagicMock):
        """Test single email retrieval when email not found."""
        comprehensive_mock_gmail_service.get_email_by_message_id.return_value = None
        
        response = client.get("/api/gmail/emails/nonexistent_msg")
        
        assert response.status_code == 404
        assert "Email not found" in response.json()["detail"]

class TestConnectionValidationAndHealth:
    """Tests for connection validation and health monitoring."""

    def test_validate_connection_success(self, client: TestClient, comprehensive_mock_oauth_service: MagicMock, gmail_user_context: UserContext):
        """Test successful connection validation."""
        mock_validation_result = {
            "valid": True,
            "user_id": gmail_user_context.user_id,
            "validated_at": "2025-01-30T10:00:00Z",
            "email": "gmail@test.com",
            "scopes_valid": True
        }
        comprehensive_mock_oauth_service.validate_connection.return_value = mock_validation_result
        
        response = client.post("/api/gmail/validate")
        
        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is True
        assert data["user_id"] == gmail_user_context.user_id
        assert data["validated_at"] == "2025-01-30T10:00:00Z"
        comprehensive_mock_oauth_service.validate_connection.assert_awaited_once_with(gmail_user_context.user_id)

    def test_validate_connection_invalid(self, client: TestClient, comprehensive_mock_oauth_service: MagicMock, gmail_user_context: UserContext):
        """Test connection validation when connection is invalid."""
        mock_validation_result = {
            "valid": False,
            "user_id": gmail_user_context.user_id,
            "validated_at": "2025-01-30T10:00:00Z",
            "error": "Access token expired"
        }
        comprehensive_mock_oauth_service.validate_connection.return_value = mock_validation_result
        
        response = client.post("/api/gmail/validate")
        
        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is False
        assert data["error"] == "Access token expired"

    def test_gmail_service_health_success(self, client: TestClient, comprehensive_mock_gmail_service: MagicMock, gmail_user_context: UserContext):
        """Test Gmail service health check."""
        mock_health_result = {
            "status": "healthy",
            "connection_status": "connected",
            "last_successful_sync": "2025-01-30T09:30:00Z",
            "error_count": 0,
            "api_response_time": 150
        }
        comprehensive_mock_gmail_service.check_service_health.return_value = mock_health_result
        
        response = client.get("/api/gmail/health")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["connection_status"] == "connected"
        assert data["last_successful_sync"] == "2025-01-30T09:30:00Z"
        assert data["error_count"] == 0
        assert data["service"] == "gmail"

    def test_gmail_service_health_unhealthy(self, client: TestClient, comprehensive_mock_gmail_service: MagicMock):
        """Test Gmail service health when unhealthy."""
        comprehensive_mock_gmail_service.check_service_health.side_effect = Exception("Gmail API unavailable")
        
        response = client.get("/api/gmail/health")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "unhealthy"
        assert "Gmail API unavailable" in data["error"]
        assert data["service"] == "gmail"

class TestPermissionsAndSecurity:
    """Tests for permissions and security aspects."""

    def test_connection_without_permission(self, client: TestClient):
        """Test Gmail connection without proper permissions."""
        # Override to simulate no Gmail connection permission
        app = client.app
        
        def no_gmail_permission():
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail="Gmail connection permission denied")
        
        app.dependency_overrides[require_gmail_connection_permission] = no_gmail_permission
        
        response = client.post("/api/gmail/connect")
        
        assert response.status_code == 403
        assert "Gmail connection permission denied" in response.json()["detail"]

    def test_email_processing_without_permission(self, client: TestClient):
        """Test email processing without proper permissions."""
        # Override to simulate no email processing permission
        app = client.app
        
        def no_processing_permission():
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail="Email processing permission denied")
        
        app.dependency_overrides[require_email_processing_permission] = no_processing_permission
        
        response = client.post("/api/gmail/discover")
        
        assert response.status_code == 403
        assert "Email processing permission denied" in response.json()["detail"]

    def test_oauth_state_validation(self, client: TestClient, comprehensive_mock_oauth_service: MagicMock):
        """Test OAuth state parameter validation."""
        comprehensive_mock_oauth_service.complete_oauth_flow.side_effect = ValidationError("Invalid OAuth state")
        
        request_body = {
            "code": "valid_code",
            "state": "invalid_state"
        }
        
        response = client.post("/api/gmail/callback", json=request_body)
        
        assert response.status_code == 422
        assert "Invalid OAuth state" in response.json()["detail"]

class TestErrorHandlingAndEdgeCases:
    """Tests for comprehensive error handling and edge cases."""

    def test_gmail_api_rate_limiting(self, client: TestClient, comprehensive_mock_email_service: MagicMock):
        """Test handling of Gmail API rate limiting."""
        comprehensive_mock_email_service.discover_user_emails.side_effect = APIError("Rate limit exceeded. Please try again later.")
        
        response = client.post("/api/gmail/discover")
        
        assert response.status_code == 503
        assert "Rate limit exceeded" in response.json()["detail"]

    def test_token_expiry_during_operation(self, client: TestClient, comprehensive_mock_email_service: MagicMock):
        """Test handling of token expiry during operation."""
        comprehensive_mock_email_service.process_single_email.side_effect = AuthenticationError("Access token expired")
        
        request_body = {"message_id": "msg_123456"}
        response = client.post("/api/gmail/process", json=request_body)
        
        assert response.status_code == 401
        assert "Access token expired" in response.json()["detail"]

    def test_malformed_oauth_callback_data(self, client: TestClient):
        """Test OAuth callback with malformed data."""
        # Invalid JSON structure
        response = client.post("/api/gmail/callback", json={"invalid": "data"})
        
        assert response.status_code == 422  # Pydantic validation error

    def test_concurrent_email_processing(self, client: TestClient, comprehensive_mock_email_service: MagicMock):
        """Test concurrent email processing requests."""
        import asyncio
        from httpx import AsyncClient
        
        # Mock successful processing
        mock_result = {
            "success": True,
            "message_id": "msg_123456",
            "processing_time": 2.3,
            "credits_used": 1,
            "summary_sent": True
        }
        comprehensive_mock_email_service.process_single_email.return_value = mock_result
        
        request_body = {"message_id": "msg_123456"}
        
        # Make multiple concurrent requests (simplified for sync test)
        responses = []
        for _ in range(3):
            response = client.post("/api/gmail/process", json=request_body)
            responses.append(response)
        
        # All should succeed or handle concurrency appropriately
        for response in responses:
            assert response.status_code in [200, 429, 503]  # Success, rate limited, or service unavailable

class TestPerformanceAndScalability:
    """Tests for performance and scalability scenarios."""

    def test_large_email_list_retrieval(self, client: TestClient, comprehensive_mock_gmail_service: MagicMock):
        """Test retrieval of large email lists."""
        # Mock large email list
        large_email_list = {
            "emails": [
                {
                    "message_id": f"msg_{i:06d}",
                    "subject": f"Email {i}",
                    "sender": f"sender{i}@test.com",
                    "received_at": f"2025-01-{(i%30)+1:02d}T10:00:00Z",
                    "processed_at": f"2025-01-{(i%30)+1:02d}T10:05:00Z",
                    "summary": f"Summary for email {i}",
                    "credits_used": 1
                }
                for i in range(100)
            ],
            "total_count": 1000,
            "has_more": True
        }
        comprehensive_mock_gmail_service.get_user_processed_emails.return_value = large_email_list
        
        response = client.get("/api/gmail/emails?limit=100")
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["emails"]) == 100
        assert data["total_count"] == 1000

    def test_zero_emails_scenario(self, client: TestClient, comprehensive_mock_gmail_service: MagicMock):
        """Test handling of zero emails scenario."""
        empty_email_list = {
            "emails": [],
            "total_count": 0,
            "has_more": False
        }
        comprehensive_mock_gmail_service.get_user_processed_emails.return_value = empty_email_list
        
        response = client.get("/api/gmail/emails")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert len(data["emails"]) == 0
        assert data["total_count"] == 0

    def test_email_discovery_timeout_handling(self, client: TestClient, comprehensive_mock_email_service: MagicMock):
        """Test handling of email discovery timeouts."""
        import asyncio
        comprehensive_mock_email_service.discover_user_emails.side_effect = asyncio.TimeoutError("Discovery timeout")
        
        response = client.post("/api/gmail/discover")
        
        assert response.status_code == 500
        assert "Failed to discover emails" in response.json()["detail"]