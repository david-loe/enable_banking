import unittest
from unittest.mock import Mock, patch

from enable_banking.api import test_configuration


class TestConfigurationAPI(unittest.TestCase):
	@patch("enable_banking.api.frappe.throw")
	@patch("enable_banking.api.frappe.only_for")
	@patch("enable_banking.api.EnableBankingClient")
	def test_active_ais_application_is_returned(self, client_class, only_for, throw):
		client_class.return_value.get_application.return_value = {
			"active": True,
			"environment": "SANDBOX",
			"name": "App",
			"services": ["AIS"],
			"kid": "secret",
		}

		result = test_configuration()

		only_for.assert_called_once_with("System Manager")
		throw.assert_not_called()
		self.assertEqual(
			result,
			{
				"active": True,
				"environment": "SANDBOX",
				"name": "App",
				"services": ["AIS"],
			},
		)

	@patch("enable_banking.api.frappe.only_for")
	@patch("enable_banking.api.frappe.throw", side_effect=RuntimeError)
	@patch("enable_banking.api.EnableBankingClient")
	def test_inactive_application_is_rejected(self, client_class, throw, _only_for):
		client_class.return_value.get_application.return_value = {
			"active": False,
			"services": ["AIS"],
		}

		with self.assertRaises(RuntimeError):
			test_configuration()

		throw.assert_called_once_with("The Enable Banking application is not active.")

	@patch("enable_banking.api.frappe.only_for")
	@patch("enable_banking.api.frappe.throw", side_effect=RuntimeError)
	@patch("enable_banking.api.EnableBankingClient")
	def test_application_without_ais_is_rejected(self, client_class, throw, _only_for):
		client_class.return_value.get_application.return_value = {
			"active": True,
			"services": ["PIS"],
		}

		with self.assertRaises(RuntimeError):
			test_configuration()

		throw.assert_called_once_with("The Enable Banking application does not have AIS access.")
