from datetime import datetime, timedelta
from uuid import uuid4
from typing import Any, Dict, List, Optional

from app.core.exceptions import ValidationError, NotFoundError


class JobRepository:
    """
    In-memory repository for background job queue management.
    """
    VALID_JOB_TYPES = {"email_processing", "user_cleanup", "system_maintenance"}
    VALID_PRIORITIES = {"low", "normal", "high"}
    VALID_STATUSES = {"pending", "running", "completed", "failed", "cancelled", "retrying"}
    DEFAULT_MAX_RETRIES = 3

    def __init__(self):
        # Internal storage for job records
        self._jobs: Dict[str, Dict[str, Any]] = {}

    def create_job(self, job_data: Dict[str, Any]) -> Dict[str, Any]:
        # Required fields
        user_id = job_data.get("user_id")
        if not user_id:
            raise ValidationError("user_id is required")
        job_type = job_data.get("job_type")
        if not job_type:
            raise ValidationError("job_type is required")
        if job_type not in self.VALID_JOB_TYPES:
            raise ValidationError("invalid job type")

        # Optional fields with defaults
        priority = job_data.get("priority", "normal")
        if priority not in self.VALID_PRIORITIES:
            raise ValidationError("invalid priority")
        status = job_data.get("status", "pending")
        if status not in self.VALID_STATUSES:
            raise ValidationError("invalid status")

        # Schedule
        sched = job_data.get("scheduled_for")
        if sched:
            try:
                # Accept ISO strings - convert to UTC if needed
                if isinstance(sched, str):
                    scheduled_for = sched
                else:
                    scheduled_for = sched.isoformat()
            except Exception:
                raise ValidationError("invalid scheduled_for format")
        else:
            scheduled_for = datetime.utcnow().isoformat()

        # Recurring
        recurring = bool(job_data.get("recurring", False))
        interval = job_data.get("interval") if recurring else None

        # Metadata
        metadata = dict(job_data.get("metadata", {}))

        # Build record
        job_id = uuid4().hex
        now = datetime.utcnow().isoformat()
        record: Dict[str, Any] = {
            "id": job_id,
            "user_id": str(user_id),
            "job_type": job_type,
            "priority": priority,
            "status": status,
            "attempts": 0,
            "worker_id": None,
            "started_at": None,
            "completed_at": None,
            "result": {},
            "metadata": metadata,
            "scheduled_for": scheduled_for,
            "recurring": recurring,
            "interval": interval,
            "created_at": now,
            "updated_at": now,
        }
        self._jobs[job_id] = record
        return record.copy()

    def get_pending_jobs(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        now = datetime.utcnow()
        # Filter ready pending jobs
        pending = []
        for r in self._jobs.values():
            if r["status"] == "pending":
                scheduled_time = datetime.fromisoformat(r["scheduled_for"])
                if scheduled_time <= now:
                    pending.append(r.copy())
        # Sort by priority (high, normal, low) and scheduled time
        priority_order = {"high": 0, "normal": 1, "low": 2}
        pending.sort(key=lambda r: (priority_order.get(r["priority"], 1), r["scheduled_for"]))
        return pending[:limit] if limit is not None else pending

    def claim_job(self, job_id: str, worker_id: str) -> Dict[str, Any]:
        rec = self._jobs.get(job_id)
        if not rec:
            raise NotFoundError("job not found")
        if rec["status"] != "pending":
            raise ValidationError("job already claimed")
        rec["status"] = "running"
        rec["worker_id"] = worker_id
        rec["started_at"] = datetime.utcnow().isoformat()
        rec["attempts"] += 1
        rec["updated_at"] = datetime.utcnow().isoformat()
        return rec.copy()

    def mark_job_completed(self, job_id: str, result: Dict[str, Any]) -> Dict[str, Any]:
        rec = self._jobs.get(job_id)
        if not rec:
            raise NotFoundError("job not found")
        if rec["status"] != "running":
            raise ValidationError("job not running")
        rec["status"] = "completed"
        rec["completed_at"] = datetime.utcnow().isoformat()
        rec["result"] = result.copy()
        rec["updated_at"] = datetime.utcnow().isoformat()
        return rec.copy()

    def mark_job_failed(self, job_id: str, error_data: Dict[str, Any]) -> Dict[str, Any]:
        rec = self._jobs.get(job_id)
        if not rec:
            raise NotFoundError("job not found")
        if rec["status"] != "running":
            raise ValidationError("job not running")
        rec["status"] = "failed"
        rec["completed_at"] = datetime.utcnow().isoformat()
        rec["result"] = error_data.copy()
        rec["updated_at"] = datetime.utcnow().isoformat()
        return rec.copy()

    def retry_job(self, job_id: str, delay: timedelta) -> Dict[str, Any]:
        rec = self._jobs.get(job_id)
        if not rec:
            raise NotFoundError("job not found")
        if rec["status"] != "failed":
            raise ValidationError("job not failed")
        if rec["attempts"] >= self.DEFAULT_MAX_RETRIES:
            raise ValidationError("maximum retry attempts exceeded")
        # Reset for retry
        rec["status"] = "pending"
        rec["scheduled_for"] = (datetime.utcnow() + delay).isoformat()
        rec["worker_id"] = None
        rec["started_at"] = None
        rec["updated_at"] = datetime.utcnow().isoformat()
        return rec.copy()

    def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        rec = self._jobs.get(job_id)
        return rec.copy() if rec else None

    def get_user_jobs(self, user_id: Any, status: Optional[str] = None) -> List[Dict[str, Any]]:
        uid = str(user_id)
        results = [r.copy() for r in self._jobs.values() if r["user_id"] == uid]
        if status:
            results = [r for r in results if r["status"] == status]
        return results

    def get_running_jobs(self) -> List[Dict[str, Any]]:
        return [r.copy() for r in self._jobs.values() if r["status"] == "running"]

    def get_stale_jobs(self, minutes: int) -> List[Dict[str, Any]]:
        cutoff = datetime.utcnow() - timedelta(minutes=minutes)
        stale: List[Dict[str, Any]] = []
        for r in self._jobs.values():
            if r["status"] == "running" and r.get("started_at"):
                started = datetime.fromisoformat(r["started_at"])
                if started < cutoff:
                    stale.append(r.copy())
        return stale

    def cancel_stale_job(self, job_id: str) -> Dict[str, Any]:
        rec = self._jobs.get(job_id)
        if not rec:
            raise NotFoundError("job not found")
        if rec["status"] != "running":
            raise ValidationError("job not running")
        rec["status"] = "failed"
        rec["completed_at"] = datetime.utcnow().isoformat()
        rec["result"] = {"error": "job_timeout", "timeout": True}
        rec["updated_at"] = datetime.utcnow().isoformat()
        return rec.copy()

    def create_next_recurring_job(self, job_id: str) -> Dict[str, Any]:
        original = self._jobs.get(job_id)
        if not original:
            raise NotFoundError("job not found")
        if not original.get("recurring"):
            raise ValidationError("job not recurring")
        # Determine next run based on interval
        interval = original.get("interval")
        delta = None
        if interval == "hourly":
            delta = timedelta(hours=1)
        elif interval == "daily":
            delta = timedelta(days=1)
        elif interval == "weekly":
            delta = timedelta(weeks=1)
        else:
            raise ValidationError("invalid interval")
        next_time = datetime.utcnow() + delta
        new_data = {
            "user_id": original["user_id"],
            "job_type": original["job_type"],
            "recurring": True,
            "interval": interval,
            "scheduled_for": next_time.isoformat(),
            "metadata": dict(original.get("metadata", {})),
        }
        return self.create_job(new_data)

    def get_job_statistics(self, user_id: Any) -> Dict[str, Any]:
        uid = str(user_id)
        jobs = [r for r in self._jobs.values() if r["user_id"] == uid]
        total = len(jobs)
        completed = len([r for r in jobs if r["status"] == "completed"]);
        failed = len([r for r in jobs if r["status"] == "failed"]);
        pending = len([r for r in jobs if r["status"] == "pending"]);
        running = len([r for r in jobs if r["status"] == "running"]);
        success_rate = (completed / total) if total > 0 else 0.0
        # Average processing time
        times = [r["result"].get("processing_time") or r["result"].get("execution_time")
                 for r in jobs if r["status"] == "completed"]
        times = [t for t in times if isinstance(t, (int, float))]
        avg_time = sum(times) / len(times) if times else 0.0
        return {
            "user_id": uid,
            "total_jobs": total,
            "completed_jobs": completed,
            "failed_jobs": failed,
            "pending_jobs": pending,
            "running_jobs": running,
            "success_rate": round(success_rate, 2),
            "average_processing_time": avg_time,
        }

    def get_system_job_statistics(self) -> Dict[str, Any]:
        jobs = list(self._jobs.values())
        total = len(jobs)
        completed = len([r for r in jobs if r["status"] == "completed"]);
        failed = len([r for r in jobs if r["status"] == "failed"]);
        pending = len([r for r in jobs if r["status"] == "pending"]);
        running = len([r for r in jobs if r["status"] == "running"]);
        success_rate = (completed / total) if total > 0 else 0.0
        # Jobs by type
        jobs_by_type: Dict[str, int] = {}
        for r in jobs:
            jtype = r["job_type"]
            jobs_by_type[jtype] = jobs_by_type.get(jtype, 0) + 1
        return {
            "total_jobs": total,
            "completed_jobs": completed,
            "failed_jobs": failed,
            "pending_jobs": pending,
            "running_jobs": running,
            "success_rate": round(success_rate, 2),
            "jobs_by_type": jobs_by_type,
        }

    def cleanup_old_jobs(self, days: int) -> int:
        cutoff = datetime.utcnow() - timedelta(days=days)
        to_delete: List[str] = []
        for jid, r in self._jobs.items():
            if r.get("completed_at") and datetime.fromisoformat(r["completed_at"]) < cutoff:
                to_delete.append(jid)
        for jid in to_delete:
            self._jobs.pop(jid, None)
        return len(to_delete)

    def delete_user_jobs(self, user_id: Any) -> int:
        uid = str(user_id)
        to_delete = [jid for jid, r in self._jobs.items() if r["user_id"] == uid]
        for jid in to_delete:
            self._jobs.pop(jid, None)
        return len(to_delete)
