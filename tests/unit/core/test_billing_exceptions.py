import pytest

# Import all the exceptions and the utility function to be tested
from app.core.billing_exceptions import (
    BillingError,
    InsufficientCreditsError,
    InvalidPackageError,
    DuplicateTransactionError,
    get_http_status_for_billing_error
)


class TestBillingExceptions:
    """Tests for custom billing exceptions."""

    def test_base_billing_error(self):
        """
        Tests that the base BillingError can be raised and stores its message.
        """
        with pytest.raises(BillingError) as exc_info:
            raise BillingError("A generic billing error occurred", error_code="generic_error")

        assert exc_info.value.message == "A generic billing error occurred"
        assert exc_info.value.error_code == "generic_error"

    @pytest.mark.parametrize(
        "exception_class, args, expected_attribute, expected_value",
        [
            (InsufficientCreditsError, (100, 50), "required", 100),
            (InvalidPackageError, ("pro_plus",), "package_key", "pro_plus"),
            (DuplicateTransactionError, ("ref_12345",), "reference_id", "ref_12345"),
        ]
    )
    def test_specific_exception_attributes(self, exception_class, args, expected_attribute, expected_value):
        """
        Tests that specific exception types correctly store their unique attributes.
        """
        # --- Act ---
        exc = exception_class(*args)

        # --- Assert ---
        assert hasattr(exc, expected_attribute)
        assert getattr(exc, expected_attribute) == expected_value

    @pytest.mark.parametrize(
        "exception_instance, expected_status_code",
        [
            (InsufficientCreditsError(100, 50), 402),
            (InvalidPackageError("pro_plus"), 404),
            (DuplicateTransactionError("ref_12345"), 409),
            (BillingError("generic"), 500), # Test fallback to the base class
        ]
    )
    def test_get_http_status_for_billing_error(self, exception_instance, expected_status_code):
        """
        Tests that the utility function correctly maps exceptions to HTTP status codes.
        """
        # --- Act ---
        status_code = get_http_status_for_billing_error(exception_instance)

        # --- Assert ---
        assert status_code == expected_status_code