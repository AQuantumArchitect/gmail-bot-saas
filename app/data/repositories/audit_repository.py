import logging
from uuid import uuid4
from datetime import datetime
from typing import Optional, List

from app.data.database import db
from app.core.exceptions import ValidationError

logger = logging.getLogger(__name__)


class AuditRepository:
    """
    Repository for audit log entries. Provides methods to record and retrieve audit events.
    """
    def __init__(self):
        self.table = db.table("audit_logs")

    async def log_event(self, user_id: str, event_type: str, metadata: dict) -> dict:
        """
        Record an audit event.
        :param user_id: UUID string of the user (or None for system events)
        :param event_type: Identifier for the event (e.g., 'purchase_completed')
        :param metadata: Arbitrary JSON-serializable dict with event details
        :return: The created audit record
        """
        record = {
            "id": str(uuid4()),
            "user_id": user_id,
            "event_type": event_type,
            "metadata": metadata,
            "timestamp": datetime.utcnow().isoformat(),
        }
        try:
            resp = self.table.insert(record).select("*").execute()
            if resp.error:
                raise resp.error
            # Supabase returns a list of inserted rows
            return resp.data[0]
        except Exception as e:
            logger.error("Failed to log audit event: %s", e)
            raise ValidationError(f"Failed to log audit event: {e}")

    async def get_user_audit_logs(self, user_id: str, limit: int = 50) -> List[dict]:
        """
        Retrieve recent audit events for a specific user.
        """
        try:
            query = self.table.select("*").eq("user_id", user_id).order("timestamp", desc=True).limit(limit)
            resp = query.execute()
            if resp.error:
                raise resp.error
            return resp.data
        except Exception as e:
            logger.error("Failed to fetch user audit logs: %s", e)
            raise ValidationError(f"Failed to fetch user audit logs: {e}")

    async def get_security_audit_logs(self, event_type: Optional[str] = None, limit: int = 50) -> List[dict]:
        """
        Retrieve security-related audit events, optionally filtered by event_type.
        """
        try:
            query = self.table.select("*")
            if event_type:
                query = query.eq("event_type", event_type)
            resp = query.order("timestamp", desc=True).limit(limit).execute()
            if resp.error:
                raise resp.error
            return resp.data
        except Exception as e:
            logger.error("Failed to fetch security audit logs: %s", e)
            raise ValidationError(f"Failed to fetch security audit logs: {e}")
