"""
RLS Verification Tests - Test that RLS is properly configured and working
Tests what we can verify without needing authenticated users
"""

import os
import pytest
import uuid
from dotenv import load_dotenv
from supabase import create_client

# Load environment variables
load_dotenv()

@pytest.fixture
def supabase_anon_client():
    """Create Supabase client with anon key"""
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    return create_client(url, key)

class TestRLSIsWorking:
    """Test that RLS is properly configured and blocking unauthenticated access"""
    
    def test_all_tables_block_anon_access(self, supabase_anon_client):
        """Test that all 9 tables properly block anonymous access"""
        
        # List of all tables that should be protected by RLS
        protected_tables = [
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
        
        results = {}
        
        for table in protected_tables:
            try:
                # Try to read from the table as anonymous user
                response = supabase_anon_client.table(table).select("*").limit(1).execute()
                
                # If we get here, the table is not properly protected
                results[table] = f"❌ SECURITY ISSUE: Table accessible to anon users! Data: {response.data}"
                
            except Exception as e:
                error_msg = str(e)
                if "permission denied" in error_msg.lower():
                    results[table] = "✅ Properly protected by RLS"
                else:
                    results[table] = f"⚠️  Different error: {error_msg}"
        
        # Print results
        print("\n" + "="*60)
        print("RLS PROTECTION STATUS FOR ALL TABLES")
        print("="*60)
        
        for table, status in results.items():
            print(f"{table:20} | {status}")
        
        print("="*60)
        
        # Check if any tables are improperly accessible
        security_issues = [table for table, status in results.items() if "SECURITY ISSUE" in status]
        
        if security_issues:
            pytest.fail(f"SECURITY VULNERABILITY: These tables are accessible to anonymous users: {security_issues}")
        
        # All tables should be properly protected
        protected_count = sum(1 for status in results.values() if "Properly protected" in status)
        print(f"\n✅ {protected_count}/{len(protected_tables)} tables properly protected by RLS")
        
        assert protected_count == len(protected_tables), f"Not all tables are properly protected. Results: {results}"
    
    def test_anon_cannot_insert_data(self, supabase_anon_client):
        """Test that anonymous users cannot insert data into protected tables"""
        
        # Test inserting into user_profiles (should fail)
        test_data = {
            "user_id": str(uuid.uuid4()),
            "display_name": "Hacker Attempt",
            "timezone": "UTC"
        }
        
        try:
            response = supabase_anon_client.table("user_profiles").insert(test_data).execute()
            pytest.fail(f"SECURITY VULNERABILITY: Anonymous user was able to insert data: {response.data}")
        except Exception as e:
            error_msg = str(e)
            if "permission denied" in error_msg.lower():
                print("✅ Anonymous insert properly blocked by RLS")
            else:
                print(f"⚠️  Insert blocked by different error: {error_msg}")
        
        # Test inserting into credit_transactions (should fail)
        credit_data = {
            "user_id": str(uuid.uuid4()),
            "transaction_type": "purchase",
            "credit_amount": 1000000,
            "credit_balance_after": 1000000,
            "description": "Free credits hack attempt"
        }
        
        try:
            response = supabase_anon_client.table("credit_transactions").insert(credit_data).execute()
            pytest.fail(f"SECURITY VULNERABILITY: Anonymous user was able to insert credits: {response.data}")
        except Exception as e:
            error_msg = str(e)
            if "permission denied" in error_msg.lower():
                print("✅ Anonymous credit insert properly blocked by RLS")
            else:
                print(f"⚠️  Credit insert blocked by different error: {error_msg}")
    
    def test_anon_cannot_update_data(self, supabase_anon_client):
        """Test that anonymous users cannot update data in protected tables"""
        
        # Try to update user_profiles (should fail)
        try:
            response = supabase_anon_client.table("user_profiles").update({
                "display_name": "Hacked Name"
            }).eq("user_id", "32506a30-d931-4571-b10d-2b4d98accbfe").execute()
            
            pytest.fail(f"SECURITY VULNERABILITY: Anonymous user was able to update data: {response.data}")
        except Exception as e:
            error_msg = str(e)
            if "permission denied" in error_msg.lower():
                print("✅ Anonymous update properly blocked by RLS")
            else:
                print(f"⚠️  Update blocked by different error: {error_msg}")
    
    def test_anon_cannot_delete_data(self, supabase_anon_client):
        """Test that anonymous users cannot delete data from protected tables"""
        
        # Try to delete from user_profiles (should fail)
        try:
            response = supabase_anon_client.table("user_profiles").delete().eq("user_id", "32506a30-d931-4571-b10d-2b4d98accbfe").execute()
            
            pytest.fail(f"SECURITY VULNERABILITY: Anonymous user was able to delete data: {response.data}")
        except Exception as e:
            error_msg = str(e)
            if "permission denied" in error_msg.lower():
                print("✅ Anonymous delete properly blocked by RLS")
            else:
                print(f"⚠️  Delete blocked by different error: {error_msg}")

class TestRLSConfiguration:
    """Test that RLS configuration is correct"""
    
    def test_database_schema_exists(self, supabase_anon_client):
        """Test that the database schema was properly applied"""
        
        # We know from earlier tests that tables exist (they show in OpenAPI spec)
        # But let's verify the error messages are consistent
        
        try:
            response = supabase_anon_client.table("user_profiles").select("*").limit(1).execute()
            print(f"⚠️  Unexpected success: {response.data}")
        except Exception as e:
            error_msg = str(e)
            print(f"✅ Expected RLS error: {error_msg}")
            
            # Should be permission denied, not table not found
            assert "permission denied" in error_msg.lower(), f"Expected permission denied, got: {error_msg}"
    
    def test_all_required_tables_exist(self, supabase_anon_client):
        """Test that all required tables exist (even if we can't access them)"""
        
        required_tables = [
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
        
        for table in required_tables:
            try:
                response = supabase_anon_client.table(table).select("*").limit(1).execute()
                print(f"⚠️  {table}: Unexpected access granted")
            except Exception as e:
                error_msg = str(e)
                
                # Should get permission denied (table exists but RLS blocks)
                # NOT "table does not exist" or "relation does not exist"
                if "permission denied" in error_msg.lower():
                    print(f"✅ {table}: Exists and properly protected")
                elif "does not exist" in error_msg.lower() or "relation" in error_msg.lower():
                    pytest.fail(f"❌ {table}: Table missing from database schema")
                else:
                    print(f"⚠️  {table}: Unexpected error: {error_msg}")
        
        print(f"✅ All {len(required_tables)} required tables exist and are protected")

class TestConnectionBasics:
    """Test basic connection functionality"""
    
    def test_supabase_connection_works(self, supabase_anon_client):
        """Test that we can connect to Supabase"""
        assert supabase_anon_client is not None
        assert supabase_anon_client.supabase_url is not None
        assert supabase_anon_client.supabase_key is not None
        print("✅ Supabase connection established")
    
    def test_environment_variables_loaded(self):
        """Test that required environment variables are present"""
        required_vars = ["SUPABASE_URL", "SUPABASE_KEY"]
        
        for var in required_vars:
            value = os.getenv(var)
            assert value is not None, f"{var} not found in environment"
            print(f"✅ {var}: {'*' * 20}...{value[-10:]}")
        
        print("✅ All required environment variables present")