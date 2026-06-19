import unittest
from unittest.mock import Mock, patch

from enable_banking.enable_banking.doctype.enable_banking_settings import (
	enable_banking_settings as settings_module,
)
from enable_banking.enable_banking.doctype.enable_banking_settings.enable_banking_settings import (
	EnableBankingSettings,
)


class TestEnableBankingSettings(unittest.TestCase):
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
			{
				"private_key_source": "Pasted Key",
				"private_key_configured": 1,
			},
		)
		self.assertEqual(result, {"configured": True})
