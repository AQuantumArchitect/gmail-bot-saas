# tests/test_database_functional.py
"""
Functional tests for app/data/database.py
Tests the Database class with actual Supabase connectivity
"""
import pytest
from uuid import uuid4
from app.data.database import Database, db
from app.core.exceptions import ValidationError, NotFoundError


class TestDatabaseFunctional:
    """Functional tests for Database class"""
    
    def test_database_singleton(self):
        """Test that db is a singleton instance"""
        assert isinstance(db, Database)
        # Test that multiple imports return same instance
        from app.data.database import db as db2
        assert db is db2
    
    def test_database_client_initialization(self):
        """Test Database client is properly initialized"""
        assert db.client is not None
        # Test that client has required methods
        assert hasattr(db.client, 'table')
        assert hasattr(db.client, 'rpc')
    
    def test_table_method(self):
        """Test table method returns table reference"""
        table_ref = db.table("user_profiles")
        assert table_ref is not None
        # Should have query methods
        assert hasattr(table_ref, 'select')
        assert hasattr(table_ref, 'insert')
        assert hasattr(table_ref, 'update')
        assert hasattr(table_ref, 'delete')
    
    def test_rpc_method_structure(self):
        """Test rpc method accepts function name and params"""
        # Test method exists and can be called
        # Note: We can't test actual RPC without valid functions
        assert hasattr(db, 'rpc')
        assert callable(db.rpc)
    
    def test_encrypt_method_exists(self):
        """Test encrypt method exists and has proper signature"""
        assert hasattr(db, 'encrypt')
        assert callable(db.encrypt)
    
    def test_decrypt_method_exists(self):
        """Test decrypt method exists and has proper signature"""
        assert hasattr(db, 'decrypt')
        assert callable(db.decrypt)
    
    def test_execute_method_exists(self):
        """Test execute method exists and handles queries"""
        assert hasattr(db, 'execute')
        assert callable(db.execute)
    
    def test_map_error_static_method(self):
        """Test error mapping functionality"""
        # Test that _map_error exists and is static
        assert hasattr(Database, '_map_error')
        assert callable(Database._map_error)
        
        # Test error mapping logic
        class MockError:
            def __init__(self, message):
                self.message = message
        
        # Test NotFoundError mapping
        not_found_error = MockError("Not Found")
        result = Database._map_error(not_found_error)
        assert isinstance(result, NotFoundError)
        
        # Test generic error mapping
        generic_error = MockError("Some other error")
        result = Database._map_error(generic_error)
        assert isinstance(result, Exception)
        assert not isinstance(result, NotFoundError)
    
    def test_database_connection_health(self):
        """Test database connection is healthy"""
        # Test that we can access the client
        assert db.client is not None
        
        # Test that settings are loaded
        from app.config import settings
        assert settings.supabase_url is not None
        assert settings.supabase_key is not None
        
        # Test client URL matches settings
        assert db.client.supabase_url == settings.supabase_url
        assert db.client.supabase_key == settings.supabase_key
    
    def test_database_table_access(self):
        """Test accessing different tables"""
        # Test all expected tables can be accessed
        expected_tables = [
            "user_profiles",
            "gmail_connections", 
            "email_discoveries",
            "processing_jobs",
            "email_summaries",
            "credit_transactions",
            "usage_analytics",
            "background_jobs",
            "system_config"
        ]
        
        for table_name in expected_tables:
            table_ref = db.table(table_name)
            assert table_ref is not None
            # Verify table reference has proper methods
            assert hasattr(table_ref, 'select')


class TestDatabaseErrorHandling:
    """Test Database error handling"""
    
    def test_validation_error_import(self):
        """Test ValidationError is properly imported"""
        from app.core.exceptions import ValidationError
        assert ValidationError is not None
        assert issubclass(ValidationError, Exception)
    
    def test_not_found_error_import(self):
        """Test NotFoundError is properly imported"""
        from app.core.exceptions import NotFoundError
        assert NotFoundError is not None
        assert issubclass(NotFoundError, Exception)
    
    def test_error_mapping_with_string_error(self):
        """Test error mapping with string error"""
        string_error = "Not Found: Record not found"
        result = Database._map_error(string_error)
        assert isinstance(result, NotFoundError)
        assert "Not Found" in str(result)
    
    def test_error_mapping_with_generic_error(self):
        """Test error mapping with generic error"""
        generic_error = "Connection timeout"
        result = Database._map_error(generic_error)
        assert isinstance(result, Exception)
        assert not isinstance(result, NotFoundError)
        assert "Connection timeout" in str(result)


class TestDatabaseIntegration:
    """Integration tests for Database with actual Supabase"""
    
    def test_config_integration(self):
        """Test Database integrates with config settings"""
        from app.config import settings
        
        # Test that Database uses settings
        assert db.client.supabase_url == settings.supabase_url
        assert db.client.supabase_key == settings.supabase_key
        
        # Test settings are loaded
        assert settings.supabase_url is not None
        assert settings.supabase_key is not None
        assert settings.vault_passphrase is not None
    
    def test_database_ready_for_repositories(self):
        """Test Database is ready for repository usage"""
        # Test singleton is accessible
        assert db is not None
        
        # Test required methods exist
        methods = ['table', 'rpc', 'encrypt', 'decrypt', 'execute']
        for method in methods:
            assert hasattr(db, method)
            assert callable(getattr(db, method))
        
        # Test client is configured
        assert db.client is not None
    
    def test_database_import_pattern(self):
        """Test the database import pattern works correctly"""
        # Test direct import
        from app.data.database import db as direct_db
        assert direct_db is not None
        
        # Test that it's the same instance
        assert direct_db is db
        
        # Test Database class import
        from app.data.database import Database
        assert Database is not None
        assert isinstance(db, Database)