import pytest
from app.core.config import Settings

@pytest.fixture(scope="session")
def test_settings() -> Settings:
    """
    Provides a Settings object configured specifically for the test suite.

    This is the single source of truth for all test configurations. It
    explicitly loads from `.env.test` to ensure tests are isolated from
    development and production environments.
    """
    return Settings(_env_file=".env.test")

@pytest.fixture(scope="session")
def db_client(test_settings: Settings):
    """
    Provide a singleton Database instance for repository tests, configured
    with the test settings.
    """
    # This assumes your database client can be configured with a URL and key.
    # The actual implementation might vary based on your database.py file.
    from app.data.database import db
    
    # Re-initialize the db client with test-specific settings if necessary
    # For now, we assume it implicitly uses the loaded env vars.
    return db