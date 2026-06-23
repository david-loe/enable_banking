import unittest
from unittest.mock import MagicMock, call, patch

from enable_banking.tests import fixtures


class TestFixtures(unittest.TestCase):
	@patch("enable_banking.tests.fixtures.frappe")
	def test_accounting_fixtures_create_company_and_verify_parent_account(self, frappe):
		frappe.db.exists.side_effect = [False, True]
		company = MagicMock()
		frappe.get_doc.return_value = company

		fixtures.ensure_accounting_fixtures()

		frappe.get_doc.assert_called_once_with(
			{
				"doctype": "Company",
				"company_name": fixtures.TEST_COMPANY,
				"abbr": fixtures.TEST_COMPANY_ABBR,
				"default_currency": "EUR",
				"country": "Germany",
				"create_chart_of_accounts_based_on": "Standard Template",
				"chart_of_accounts": "Standard",
			}
		)
		company.insert.assert_called_once_with(ignore_permissions=True)
		self.assertEqual(
			frappe.db.exists.call_args_list,
			[
				call("Company", fixtures.TEST_COMPANY),
				call("Account", fixtures.TEST_PARENT_ACCOUNT),
			],
		)

	@patch("enable_banking.tests.fixtures.frappe")
	def test_accounting_fixtures_are_idempotent(self, frappe):
		frappe.db.exists.return_value = True

		fixtures.ensure_accounting_fixtures()
		fixtures.ensure_accounting_fixtures()

		frappe.get_doc.assert_not_called()

	@patch("enable_banking.tests.fixtures.frappe")
	def test_accounting_fixtures_fail_clearly_when_parent_account_is_missing(self, frappe):
		frappe.db.exists.side_effect = [True, False]

		with self.assertRaisesRegex(RuntimeError, fixtures.TEST_PARENT_ACCOUNT):
			fixtures.ensure_accounting_fixtures()
