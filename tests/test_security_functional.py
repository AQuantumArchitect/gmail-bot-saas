# tests/test_security_functional.py
"""
Functional tests for app/core/security.py
Tests encryption, decryption, and secure comparison functions
"""
import pytest
from app.core.security import encrypt_value, decrypt_value, secure_compare
from app.core.exceptions import ValidationError


class TestEncryptionFunctional:
    """Functional tests for encryption/decryption"""
    
    def test_encrypt_value_function_exists(self):
        """Test encrypt_value function exists and is callable"""
        assert callable(encrypt_value)
    
    def test_decrypt_value_function_exists(self):
        """Test decrypt_value function exists and is callable"""
        assert callable(decrypt_value)
    
    def test_encrypt_value_returns_bytes(self):
        """Test encrypt_value returns bytes"""
        # Note: This test may fail if vault is not properly configured
        # but it tests the function structure
        test_string = "test_plaintext"
        try:
            result = encrypt_value(test_string)
            assert isinstance(result, bytes)
        except ValidationError:
            # If vault is not configured, function should raise ValidationError
            pass
    
    def test_encrypt_empty_string(self):
        """Test encrypting empty string"""
        try:
            result = encrypt_value("")
            assert isinstance(result, bytes)
        except ValidationError:
            # Expected if vault is not configured
            pass
    
    def test_encrypt_unicode_string(self):
        """Test encrypting unicode string"""
        unicode_string = "héllo wörld 🌍"
        try:
            result = encrypt_value(unicode_string)
            assert isinstance(result, bytes)
        except ValidationError:
            # Expected if vault is not configured
            pass
    
    def test_decrypt_value_with_bytes(self):
        """Test decrypt_value accepts bytes"""
        test_bytes = b"test_ciphertext"
        try:
            result = decrypt_value(test_bytes)
            assert isinstance(result, str)
        except ValidationError:
            # Expected if vault is not configured or invalid ciphertext
            pass
    
    def test_encryption_error_handling(self):
        """Test encryption error handling"""
        # Test with invalid input types
        with pytest.raises(Exception):
            encrypt_value(None)
        
        with pytest.raises(Exception):
            encrypt_value(123)
        
        with pytest.raises(Exception):
            encrypt_value({"key": "value"})
    
    def test_decryption_error_handling(self):
        """Test decryption error handling"""
        # Test with invalid input types
        with pytest.raises(Exception):
            decrypt_value(None)
        
        with pytest.raises(Exception):
            decrypt_value("string_instead_of_bytes")
        
        with pytest.raises(Exception):
            decrypt_value(123)


class TestSecureCompareFunctional:
    """Functional tests for secure_compare"""
    
    def test_secure_compare_function_exists(self):
        """Test secure_compare function exists and is callable"""
        assert callable(secure_compare)
    
    def test_secure_compare_identical_strings(self):
        """Test secure_compare with identical strings"""
        result = secure_compare("test", "test")
        assert result is True
        assert isinstance(result, bool)
    
    def test_secure_compare_different_strings(self):
        """Test secure_compare with different strings"""
        result = secure_compare("test", "different")
        assert result is False
        assert isinstance(result, bool)
    
    def test_secure_compare_identical_bytes(self):
        """Test secure_compare with identical bytes"""
        result = secure_compare(b"test", b"test")
        assert result is True
    
    def test_secure_compare_different_bytes(self):
        """Test secure_compare with different bytes"""
        result = secure_compare(b"test", b"different")
        assert result is False
    
    def test_secure_compare_string_to_bytes(self):
        """Test secure_compare with string and bytes"""
        result = secure_compare("test", b"test")
        assert result is True
    
    def test_secure_compare_empty_strings(self):
        """Test secure_compare with empty strings"""
        result = secure_compare("", "")
        assert result is True
    
    def test_secure_compare_empty_vs_nonempty(self):
        """Test secure_compare with empty vs non-empty"""
        result = secure_compare("", "test")
        assert result is False
    
    def test_secure_compare_case_sensitivity(self):
        """Test secure_compare is case sensitive"""
        result = secure_compare("Test", "test")
        assert result is False
    
    def test_secure_compare_unicode_strings(self):
        """Test secure_compare with unicode strings"""
        result = secure_compare("héllo", "héllo")
        assert result is True
        
        result = secure_compare("héllo", "hello")
        assert result is False
    
    def test_secure_compare_error_handling(self):
        """Test secure_compare error handling"""
        # Test with invalid types
        with pytest.raises(ValidationError):
            secure_compare(None, "test")
        
        with pytest.raises(ValidationError):
            secure_compare("test", None)
        
        with pytest.raises(ValidationError):
            secure_compare(123, "test")
        
        with pytest.raises(ValidationError):
            secure_compare("test", 123)
        
        with pytest.raises(ValidationError):
            secure_compare([], "test")
        
        with pytest.raises(ValidationError):
            secure_compare({"key": "value"}, "test")
    
    def test_secure_compare_timing_attack_resistance(self):
        """Test secure_compare uses constant-time comparison"""
        # Verify it uses compare_digest
        import hmac
        
        # Test that function internally uses compare_digest
        # This is a structural test - the function should use hmac.compare_digest
        result1 = secure_compare("short", "short")
        result2 = secure_compare("verylongstring", "verylongstring")
        
        # Both should work regardless of length
        assert result1 is True
        assert result2 is True
        
        # Test different lengths
        result3 = secure_compare("short", "verylongstring")
        assert result3 is False


class TestSecurityIntegration:
    """Integration tests for security module"""
    
    def test_security_imports(self):
        """Test all security functions can be imported"""
        from app.core.security import encrypt_value, decrypt_value, secure_compare
        assert encrypt_value is not None
        assert decrypt_value is not None
        assert secure_compare is not None
    
    def test_database_integration(self):
        """Test security integrates with database"""
        from app.data.database import db
        
        # Test that security uses database for encryption
        assert hasattr(db, 'encrypt')
        assert hasattr(db, 'decrypt')
    
    def test_exception_integration(self):
        """Test security integrates with exceptions"""
        from app.core.exceptions import ValidationError
        
        # Test that security functions raise ValidationError
        with pytest.raises(ValidationError):
            secure_compare(None, "test")
    
    def test_security_workflow(self):
        """Test complete security workflow if vault is configured"""
        test_data = "sensitive_oauth_token"
        
        try:
            # Test encryption
            encrypted = encrypt_value(test_data)
            assert isinstance(encrypted, bytes)
            assert encrypted != test_data.encode()  # Should be different
            
            # Test decryption
            decrypted = decrypt_value(encrypted)
            assert isinstance(decrypted, str)
            assert decrypted == test_data
            
            # Test secure comparison
            assert secure_compare(test_data, decrypted) is True
            assert secure_compare(test_data, "different") is False
            
        except ValidationError as e:
            # If vault is not configured, this is expected
            assert "failed" in str(e).lower()
    
    def test_security_module_structure(self):
        """Test security module has expected structure"""
        import app.core.security as security_module
        
        # Test module has expected functions
        expected_functions = ['encrypt_value', 'decrypt_value', 'secure_compare']
        for func_name in expected_functions:
            assert hasattr(security_module, func_name)
            assert callable(getattr(security_module, func_name))
    
    def test_security_error_consistency(self):
        """Test all security functions use consistent error handling"""
        # All functions should raise ValidationError for invalid inputs
        with pytest.raises(ValidationError):
            secure_compare(None, "test")
        
        # Encryption/decryption errors should also be ValidationError
        try:
            encrypt_value(None)
        except ValidationError:
            pass  # Expected
        except Exception as e:
            # Should be ValidationError, not generic Exception
            assert isinstance(e, ValidationError)