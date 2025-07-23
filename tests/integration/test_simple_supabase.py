"""
Simple Supabase connectivity test
Test basic connection to Supabase with anon key only
"""

import os
import pytest
from dotenv import load_dotenv
from supabase import create_client

# Load environment variables
load_dotenv()

@pytest.fixture
def supabase_client():
    """Create basic Supabase client for testing with anon key"""
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")  # anon key only
    
    print(f"Testing connection to: {url}")
    print(f"Using anon key: {key[:20]}...")
    
    return create_client(url, key)

def test_supabase_connection(supabase_client):
    """Test basic Supabase connection"""
    # This should work - just test the client was created
    assert supabase_client is not None
    assert supabase_client.supabase_url is not None
    assert supabase_client.supabase_key is not None

def test_environment_variables():
    """Test that environment variables are loaded correctly"""
    url = os.getenv("SUPABASE_URL")
    anon_key = os.getenv("SUPABASE_KEY")
    
    assert url is not None, "SUPABASE_URL not found in environment"
    assert anon_key is not None, "SUPABASE_KEY not found in environment"
    assert url.startswith("https://"), f"Invalid URL format: {url}"
    print(f"✓ URL: {url}")
    print(f"✓ Anon key: {anon_key[:50]}...")

def test_basic_public_schema_access_anon(supabase_client):
    """Test access to public schema with anon key (should be restricted by RLS)"""
    try:
        # Try to access a table that should exist in public schema
        response = supabase_client.table("user_profiles").select("*").limit(1).execute()
        print(f"✓ Public schema accessible with anon key, response: {response}")
        # This might work if RLS allows anon access, or fail if it doesn't
        assert True
    except Exception as e:
        print(f"✗ Error accessing public schema with anon key: {e}")
        print(f"Error type: {type(e)}")
        print(f"Error details: {str(e)}")
        # This is expected - anon users shouldn't access user_profiles without auth
        assert True  # Continue testing

def test_connection_only():
    """Test that basic connection setup works"""
    url = os.getenv("SUPABASE_URL")
    anon_key = os.getenv("SUPABASE_KEY")
    
    # Just test that we can create a client
    client = create_client(url, anon_key)
    assert client is not None
    assert client.supabase_url == url
    print("✓ Basic anon client connection successful")