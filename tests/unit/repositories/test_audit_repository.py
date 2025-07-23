import pytest
from datetime import datetime
from uuid import uuid4

from app.data.repositories.audit_repository import AuditRepository
from app.core.exceptions import ValidationError


class MockResponse:
    def __init__(self, data=None, error=None):
        self.data = data or []
        self.error = error


class DummyTable:
    def __init__(self):
        self._data = []
        self._query = {}
        self._last_insert = None
        self._limit = None

    def insert(self, record):
        self._data.append(record)
        self._last_insert = record
        return self

    def select(self, *args):
        # Reset query state for new query
        self._query = {}
        self._limit = None
        return self

    def eq(self, col, val):
        self._query[col] = val
        return self

    def order(self, col, desc=False):
        return self

    def limit(self, n):
        self._limit = n
        return self

    def execute(self):
        if self._last_insert is not None:
            result = MockResponse(data=[self._last_insert])
            self._last_insert = None  # Reset after returning
            return result
        results = self._data.copy()
        for col, val in self._query.items():
            results = [r for r in results if r.get(col) == val]
        if self._limit is not None:
            results = results[:self._limit]
        return MockResponse(data=results)


@pytest.fixture(autouse=True)
def patch_db_table(monkeypatch):
    import app.data.database as dbmod
    dummy = DummyTable()
    monkeypatch.setattr(dbmod.db, 'table', lambda name: dummy)
    return dummy


@pytest.mark.asyncio
async def test_log_event_success(patch_db_table):
    repo = AuditRepository()
    user_id = str(uuid4())
    event_type = 'test_event'
    metadata = {'key': 'value'}

    entry = await repo.log_event(user_id, event_type, metadata)

    assert entry['user_id'] == user_id
    assert entry['event_type'] == event_type
    assert entry['metadata'] == metadata
    assert 'id' in entry and 'timestamp' in entry


@pytest.mark.asyncio
async def test_log_event_failure(patch_db_table):
    # simulate insert error
    class Err(Exception):
        def __init__(self):
            self.message = 'Insert failed'
        def __str__(self):
            return self.message
    dummy = patch_db_table
    dummy.insert = lambda rec: dummy
    dummy.execute = lambda : MockResponse(data=None, error=Err())

    repo = AuditRepository()
    with pytest.raises(ValidationError) as exc:
        await repo.log_event(str(uuid4()), 'evt', {})
    assert 'Insert failed' in str(exc.value)


@pytest.mark.asyncio
async def test_get_user_audit_logs(patch_db_table):
    repo = AuditRepository()
    user_id = str(uuid4())
    # seed logs
    await repo.log_event(user_id, 'e1', {})
    await repo.log_event(user_id, 'e2', {})
    logs = await repo.get_user_audit_logs(user_id, limit=1)
    assert isinstance(logs, list)
    assert len(logs) == 1
    assert logs[0]['user_id'] == user_id


@pytest.mark.asyncio
async def test_get_security_audit_logs(patch_db_table):
    repo = AuditRepository()
    # seed logs
    await repo.log_event(None, 'login_failure', {'error': 'bad'})
    await repo.log_event(None, 'login_success', {})
    logs = await repo.get_security_audit_logs(event_type='login_failure', limit=5)
    assert all(log['event_type'] == 'login_failure' for log in logs)
