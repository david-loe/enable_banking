import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from enable_banking.enable_banking.doctype.enable_banking_settings import (
	enable_banking_settings as settings_module,
)
from enable_banking.enable_banking.doctype.enable_banking_settings.enable_banking_settings import (
	EnableBankingSettings,
)


class TestEnableBankingSettings(unittest.TestCase):
	def test_private_key_is_not_managed_by_regular_settings_save(self):
		settings = object.__new__(EnableBankingSettings)
		settings.flags = Mock()

		settings.__setup__()

		self.assertEqual(settings.flags.ignore_save_passwords, ["private_key"])

	def test_valid_notification_settings_are_accepted(self):
		settings = _settings(
			expiry_notification_lead_days=7,
			expiry_notification_frequency="Daily",
		)
		frappe_mock = Mock()

		with patch.object(settings_module, "frappe", frappe_mock):
			EnableBankingSettings.validate(settings)

		frappe_mock.throw.assert_not_called()

	def test_invalid_notification_frequency_is_rejected(self):
		settings = _settings(expiry_notification_frequency="Weekly")
		frappe_mock = Mock()
		frappe_mock.throw.side_effect = RuntimeError("invalid frequency")

		with (
			patch.object(settings_module, "frappe", frappe_mock),
			self.assertRaisesRegex(RuntimeError, "invalid frequency"),
		):
			EnableBankingSettings.validate(settings)

	def test_expiry_notification_lead_days_must_be_positive(self):
		settings = _settings(expiry_notification_lead_days=0)
		frappe_mock = Mock()
		frappe_mock.throw.side_effect = RuntimeError("invalid lead days")

		with (
			patch.object(settings_module, "frappe", frappe_mock),
			self.assertRaisesRegex(RuntimeError, "invalid lead days"),
		):
			EnableBankingSettings.validate(settings)

	@patch(
		"enable_banking.enable_banking.doctype.enable_banking_settings.enable_banking_settings."
		"set_encrypted_password"
	)
	@patch(
		"enable_banking.enable_banking.doctype.enable_banking_settings.enable_banking_settings."
		"validate_private_key",
		return_value="validated-key",
	)
	def test_pasted_key_is_encrypted_and_selected(
		self,
		validate_key,
		set_encrypted_password,
	):
		settings = object.__new__(EnableBankingSettings)
		frappe_mock = Mock()

		with patch.object(settings_module, "frappe", frappe_mock):
			result = settings.set_private_key("private-key")

		frappe_mock.only_for.assert_called_once_with("System Manager")
		validate_key.assert_called_once_with("private-key")
		set_encrypted_password.assert_called_once_with(
			"Enable Banking Settings",
			"Enable Banking Settings",
			"validated-key",
			"private_key",
		)
		frappe_mock.db.set_single_value.assert_called_once_with(
			"Enable Banking Settings",
			"private_key_configured",
			1,
		)
		self.assertEqual(result, {"configured": True})

	@patch(
		"enable_banking.enable_banking.doctype.enable_banking_settings.enable_banking_settings."
		"remove_encrypted_password"
	)
	def test_clear_private_key_removes_encrypted_key(self, remove_encrypted_password):
		settings = object.__new__(EnableBankingSettings)
		frappe_mock = Mock()

		with patch.object(settings_module, "frappe", frappe_mock):
			result = settings.clear_private_key()

		frappe_mock.only_for.assert_called_once_with("System Manager")
		remove_encrypted_password.assert_called_once_with(
			"Enable Banking Settings",
			"Enable Banking Settings",
			"private_key",
		)
		frappe_mock.db.set_single_value.assert_called_once_with(
			"Enable Banking Settings",
			"private_key_configured",
			0,
		)
		self.assertEqual(result, {"configured": False})


def _settings(**overrides):
	values = {
		"sync_interval": "Every Hour",
		"initial_import_days": 90,
		"default_consent_days": 90,
		"max_transaction_pages": 20,
		"max_transactions_per_sync": 5000,
		"expiry_notification_lead_days": 7,
		"expiry_notification_frequency": "Daily",
		"overlap_days": 7,
	}
	values.update(overrides)
	settings = SimpleNamespace(**values)
	settings.meta = Mock()
	settings.meta.get_label.side_effect = lambda fieldname: fieldname
	settings.get = lambda fieldname: getattr(settings, fieldname, None)
	return settings
