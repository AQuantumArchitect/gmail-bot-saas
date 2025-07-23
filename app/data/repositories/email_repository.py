from datetime import datetime, timedelta
from uuid import uuid4
from typing import Any, Dict, List, Optional, Tuple

from app.core.exceptions import ValidationError


class EmailRepository:
    """
    In-memory repository for managing email processing lifecycle:
    - Discovery of emails
    - Processing start and completion
    - Retries and timeouts
    - Stats and cleanup
    """

    def __init__(self):
        # Records stored by internal ID
        self._records: Dict[str, Dict[str, Any]] = {}
        # Index mapping (user_id, message_id) -> record_id
        self._index: Dict[Tuple[str, str], str] = {}
        # Default maximum retries
        self._default_max_retries = 3

    def mark_discovered(
        self,
        user_id: Any,
        message_id: str,
        filter_results: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Mark an email as discovered. If already discovered, increment discovery_count.
        """
        if not message_id:
            raise ValidationError("message_id cannot be empty")
        if " " in message_id:
            raise ValidationError("invalid message_id format")

        uid = str(user_id)
        key = (uid, message_id)
        now = datetime.utcnow()

        if key in self._index:
            rec = self._records[self._index[key]]
            rec["discovery_count"] += 1
            rec["discovered_at"] = now
        else:
            rec_id = str(uuid4())
            rec = {
                "id": rec_id,
                "user_id": uid,
                "message_id": message_id,
                "status": "discovered",
                "filter_results": filter_results or {},
                "discovery_count": 1,
                "discovered_at": now,
                "processing_started_at": None,
                "processing_completed_at": None,
                "processing_attempts": 0,
                "processing_result": {},
                "last_retry_at": None,
                "max_retries": self._default_max_retries,
                "success": None,
            }
            self._records[rec_id] = rec
            self._index[key] = rec_id

        return rec.copy()

    def bulk_mark_discovered(
        self,
        user_id: Any,
        discoveries: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Bulk discovery of multiple emails.
        """
        results: List[Dict[str, Any]] = []
        for disc in discoveries:
            msg_id = disc.get("message_id")
            filter_res = disc.get("filter_results") or {}
            res = self.mark_discovered(user_id, msg_id, filter_res)
            results.append(res)
        return results

    def mark_discovered_batch(
        self,
        user_id: Any,
        message_ids: List[str],
    ) -> List[Dict[str, Any]]:
        """
        Mark multiple emails as discovered by message_id list.
        """
        results: List[Dict[str, Any]] = []
        for msg_id in message_ids:
            res = self.mark_discovered(user_id, msg_id)
            results.append(res)
        return results

    def mark_processing_started(
        self,
        user_id: Any,
        message_id: str,
    ) -> Dict[str, Any]:
        """
        Mark a discovered email as processing.
        """
        uid = str(user_id)
        key = (uid, message_id)
        if key not in self._index:
            raise ValidationError("Email not discovered")

        rec = self._records[self._index[key]]
        if rec["status"] == "processing":
            raise ValidationError("Email already processing")

        rec["status"] = "processing"
        rec["processing_started_at"] = datetime.utcnow()
        rec["processing_attempts"] += 1
        return rec.copy()

    def mark_processing_completed(
        self,
        user_id: Any,
        message_id: str,
        processing_result: Dict[str, Any],
        success: bool = True,
    ) -> Dict[str, Any]:
        """
        Mark a processing email as completed (success or failure).
        """
        uid = str(user_id)
        key = (uid, message_id)
        if key not in self._index:
            raise ValidationError("Email not discovered")

        rec = self._records[self._index[key]]
        if rec["status"] != "processing":
            raise ValidationError("Email not in processing state")

        rec["status"] = "completed" if success else "failed"
        rec["processing_completed_at"] = datetime.utcnow()
        # Merge processing_result
        rec["processing_result"].update(processing_result)
        rec["success"] = success
        return rec.copy()

    def mark_for_retry(
        self,
        user_id: Any,
        message_id: str,
    ) -> Dict[str, Any]:
        """
        After a failed processing, mark email to retry if below max retries.
        """
        uid = str(user_id)
        key = (uid, message_id)
        if key not in self._index:
            raise ValidationError("Email not discovered")

        rec = self._records[self._index[key]]
        attempts = rec.get("processing_attempts", 0)
        max_retries = rec.get("max_retries", self._default_max_retries)
        if attempts >= max_retries:
            raise ValidationError("Maximum retry attempts exceeded")

        rec["status"] = "discovered"
        rec["last_retry_at"] = datetime.utcnow()
        # can_retry flag is dynamic
        rec["can_retry"] = attempts < max_retries
        return rec.copy()

    def get_processing_status(
        self,
        user_id: Any,
        message_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Return the latest status for a given email or None.
        """
        uid = str(user_id)
        key = (uid, message_id)
        if key not in self._index:
            return None
        return self._records[self._index[key]].copy()

    def get_unprocessed_emails(
        self,
        user_id: Any,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get discovered emails that haven't been completed or failed.
        Ordered by discovered_at ascending.
        """
        uid = str(user_id)
        pending = [rec.copy() for rec in self._records.values()
                   if rec["user_id"] == uid and rec["status"] == "discovered"]
        pending.sort(key=lambda x: x["discovered_at"])  # oldest first
        return pending[:limit] if limit is not None else pending

    def get_processing_history(
        self,
        user_id: Any,
        limit: Optional[int] = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get history of completed/failed processing for a user.
        Ordered by processing_completed_at descending.
        """
        uid = str(user_id)
        hist = [rec.copy() for rec in self._records.values()
                if rec["user_id"] == uid
                and rec["status"] in ("completed", "failed")]
        if status:
            hist = [rec for rec in hist if rec["status"] == status]
        hist.sort(key=lambda x: x["processing_completed_at"], reverse=True)
        if limit is not None:
            hist = hist[:limit]
        return hist

    def get_processing_stats(
        self,
        user_id: Any,
    ) -> Dict[str, Any]:
        """
        Aggregate processing statistics for a user.
        """
        uid = str(user_id)
        recs = [rec for rec in self._records.values() if rec["user_id"] == uid]
        total_discovered = len(recs)
        processed = [r for r in recs if r["status"] in ("completed", "failed")]
        total_processed = len(processed)
        successes = [r for r in processed if r["status"] == "completed"]
        failures = [r for r in processed if r["status"] == "failed"]
        total_successful = len(successes)
        total_failed = len(failures)
        pending = total_discovered - total_processed
        total_credits_used = sum(r["processing_result"].get("credits_used", 0) for r in successes)
        avg_time = (sum(r["processing_result"].get("processing_time", 0) for r in successes) /
                    total_successful) if total_successful > 0 else 0.0
        success_rate = (total_successful / total_processed) if total_processed > 0 else 0.0

        return {
            "user_id": uid,
            "total_discovered": total_discovered,
            "total_processed": total_processed,
            "total_successful": total_successful,
            "total_failed": total_failed,
            "total_pending": pending,
            "success_rate": round(success_rate, 2),
            "total_credits_used": total_credits_used,
            "average_processing_time": avg_time,
        }

    def cleanup_old_records(self, days: int) -> int:
        """
        Delete completed/failed records older than specified days.
        Returns number deleted.
        """
        cutoff = datetime.utcnow() - timedelta(days=days)
        to_delete = [rid for rid, rec in self._records.items()
                     if rec.get("processing_completed_at") and rec["processing_completed_at"] < cutoff]
        for rid in to_delete:
            rec = self._records.pop(rid)
            key = (rec["user_id"], rec["message_id"])
            self._index.pop(key, None)
        return len(to_delete)

    def get_stale_processing_emails(self, minutes: int) -> List[Dict[str, Any]]:
        """
        Get emails stuck in processing longer than given minutes.
        """
        cutoff = datetime.utcnow() - timedelta(minutes=minutes)
        stale = [rec.copy() for rec in self._records.values()
                 if rec["status"] == "processing"
                 and rec.get("processing_started_at")
                 and rec["processing_started_at"] < cutoff]
        return stale

    def mark_processing_timeout(
        self,
        user_id: Any,
        message_id: str,
    ) -> Dict[str, Any]:
        """
        Mark a stale processing email as failed due to timeout.
        """
        uid = str(user_id)
        key = (uid, message_id)
        if key not in self._index:
            raise ValidationError("Email not discovered")
        rec = self._records[self._index[key]]
        if rec["status"] != "processing":
            raise ValidationError("Email not in processing state")

        rec["status"] = "failed"
        rec["processing_completed_at"] = datetime.utcnow()
        rec["processing_result"].update({"error": "processing_timeout", "timeout": True})
        rec["success"] = False
        return rec.copy()

    def get_duplicate_message_ids(self, user_id: Any) -> List[Dict[str, Any]]:
        """
        Return messages with discovery_count > 1 for a user.
        """
        uid = str(user_id)
        duplicates = [rec.copy() for rec in self._records.values()
                      if rec["user_id"] == uid and rec.get("discovery_count", 0) > 1]
        return duplicates

    def delete_user_email_data(self, user_id: Any) -> int:
        """
        Remove all email records for a given user.
        Returns count deleted.
        """
        uid = str(user_id)
        to_delete = [rid for rid, rec in self._records.items() if rec["user_id"] == uid]
        for rid in to_delete:
            rec = self._records.pop(rid)
            self._index.pop((rec["user_id"], rec["message_id"]), None)
        return len(to_delete)
