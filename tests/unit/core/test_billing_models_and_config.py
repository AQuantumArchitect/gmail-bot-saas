import pytest
from uuid import uuid4, UUID
from datetime import datetime, timezone

# Import the new classes to be tested
from app.core.billing_config import BillingConfig, CreditPackage
from app.models.billing import TransactionRecord, BillingHistory

# Import the global settings object to be patched
from app.core import config as app_config


class TestBillingConfig:
    """Tests for the BillingConfig and CreditPackage classes."""

    def test_credit_package_properties(self):
        """
        Tests the calculated properties of the CreditPackage dataclass.
        """
        package = CreditPackage(key="pro", name="Pro Pack", credits=1000, price_cents=4000)
        assert package.price_usd == 40.00
        assert package.price_per_credit_usd == 0.04

    def test_credit_package_savings_calculation(self):
        """
        Tests the savings calculation between credit packages.
        """
        starter = CreditPackage(key="starter", name="Starter", credits=100, price_cents=500) # $0.05/credit
        pro = CreditPackage(key="pro", name="Pro", credits=1000, price_cents=4000) # $0.04/credit

        savings = pro.calculate_savings_percent(starter)
        
        assert savings == 20.0 # (0.05 - 0.04) / 0.05 = 0.2
        assert starter.calculate_savings_percent(starter) is None

    def test_billing_config_from_settings(self, monkeypatch):
        """
        Tests that the BillingConfig class correctly loads its values from settings.
        """
        monkeypatch.setattr(app_config.settings, "stripe_secret_key", "sk_test_123")
        monkeypatch.setattr(app_config.settings, "stripe_webhook_secret", "whsec_test_123")
        monkeypatch.setattr(app_config.settings, "stripe_publishable_key", "pk_test_123")
        monkeypatch.setattr(app_config.settings, "enable_stripe", True)
        monkeypatch.setattr(app_config.settings, "webapp_url", "http://localhost:3000")

        billing_config = BillingConfig.from_settings()

        assert billing_config.enable_stripe is True
        assert billing_config.stripe_secret_key == "sk_test_123"
        assert "pro" in billing_config.credit_packages

    def test_billing_config_validation(self):
        """
        Tests the custom validation logic in BillingConfig.
        """
        # A valid config should pass
        valid_packages = {"starter": CreditPackage("starter", "Starter", 100, 500)}
        valid_config = BillingConfig("sk_123", "whsec_123", "pk_123", True, "url", valid_packages)
        assert valid_config.validate_configuration() is True

        # An invalid config should fail
        invalid_packages = {"starter": CreditPackage("starter", "Starter", 0, 500)} # Zero credits
        invalid_config = BillingConfig("sk_123", "whsec_123", "pk_123", True, "url", invalid_packages)
        with pytest.raises(ValueError, match="must have positive credits"):
            invalid_config.validate_configuration()


class TestBillingModels:
    """Tests for the data models in billing.py."""

    def test_transaction_record_from_dict(self):
        """
        Tests that TransactionRecord.from_dict correctly parses a raw dictionary.
        """
        raw_data = {
            "id": str(uuid4()), "user_id": str(uuid4()), "transaction_type": "purchase", "credit_amount": 100,
            "credit_balance_after": 150, "description": "Starter Pack", "reference_id": str(uuid4()),
            "reference_type": "stripe_checkout", "usd_amount": "5.00", "usd_per_credit": "0.05",
            "metadata": {"package_key": "starter"}, "created_at": "2025-07-18T20:00:00Z"
        }
        transaction = TransactionRecord.from_dict(raw_data)

        assert isinstance(transaction.id, UUID)
        assert isinstance(transaction.created_at, datetime)
        assert transaction.created_at.tzinfo is timezone.utc
    
    def test_transaction_record_properties(self):
        """
        Tests the computed properties on the TransactionRecord model.
        """
        user_id = uuid4()
        purchase = TransactionRecord(id=uuid4(), user_id=user_id, transaction_type="purchase", credit_amount=100,
                                     credit_balance_after=100, description="", reference_id=None, reference_type=None,
                                     usd_amount=None, usd_per_credit=None, metadata={}, created_at=datetime.now())
        
        usage = TransactionRecord(id=uuid4(), user_id=user_id, transaction_type="usage", credit_amount=-5,
                                  credit_balance_after=95, description="", reference_id=None, reference_type=None,
                                  usd_amount=None, usd_per_credit=None, metadata={}, created_at=datetime.now())

        assert purchase.is_credit_addition is True
        assert purchase.is_credit_deduction is False
        assert usage.is_credit_addition is False
        assert usage.is_credit_deduction is True

    def test_billing_history_from_transactions(self):
        """
        Tests the logic for calculating billing history totals from a list of transactions.
        """
        user_id = uuid4()
        now = datetime.now()
        transactions = [
            TransactionRecord(id=uuid4(), user_id=user_id, transaction_type="purchase", credit_amount=100, credit_balance_after=100, description="", reference_id=None, reference_type=None, usd_amount=None, usd_per_credit=None, metadata={}, created_at=now),
            TransactionRecord(id=uuid4(), user_id=user_id, transaction_type="bonus", credit_amount=10, credit_balance_after=110, description="", reference_id=None, reference_type=None, usd_amount=None, usd_per_credit=None, metadata={}, created_at=now),
            TransactionRecord(id=uuid4(), user_id=user_id, transaction_type="usage", credit_amount=-5, credit_balance_after=105, description="", reference_id=None, reference_type=None, usd_amount=None, usd_per_credit=None, metadata={}, created_at=now),
            TransactionRecord(id=uuid4(), user_id=user_id, transaction_type="usage", credit_amount=-15, credit_balance_after=90, description="", reference_id=None, reference_type=None, usd_amount=None, usd_per_credit=None, metadata={}, created_at=now)
        ]

        history = BillingHistory.from_transactions(user_id, transactions, current_balance=90)

        assert history.total_transactions == 4
        assert history.total_purchased == 110 # 100 (purchase) + 10 (bonus)
        assert history.total_used == 20 # 5 + 15
        assert history.current_balance == 90