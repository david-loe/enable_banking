import unittest
from unittest.mock import patch

from enable_banking import setup


class TestSetup(unittest.TestCase):
	def test_custom_fields_cover_phase_two_extensions(self):
		custom_fields = setup.get_custom_fields()

		self.assertEqual(
			{field["fieldname"] for field in custom_fields["Bank"]},
			{"enable_banking_aspsp_key"},
		)
		self.assertEqual(
			{field["fieldname"] for field in custom_fields["Bank Account"]},
			{
				"enable_banking_section",
				"enable_banking_account",
				"enable_banking_booked_balance",
				"enable_banking_available_balance",
				"enable_banking_balance_currency",
				"enable_banking_balance_as_of",
				"enable_banking_last_sync_at",
			},
		)
		self.assertEqual(
			{field["fieldname"] for field in custom_fields["Bank Transaction"]},
			{
				"enable_banking_section",
				"enable_banking_account",
				"enable_banking_transaction_key",
			},
		)
		self.assertNotIn(
			"integration_id",
			{field["fieldname"] for fields in custom_fields.values() for field in fields},
		)

	def test_unique_provider_and_idempotency_fields(self):
		custom_fields = setup.get_custom_fields()

		bank_key = _field(custom_fields, "Bank", "enable_banking_aspsp_key")
		account_link = _field(custom_fields, "Bank Account", "enable_banking_account")
		transaction_key = _field(
			custom_fields,
			"Bank Transaction",
			"enable_banking_transaction_key",
		)

		self.assertEqual(bank_key["unique"], 1)
		self.assertEqual(account_link["unique"], 1)
		self.assertEqual(transaction_key["unique"], 1)
		self.assertEqual(transaction_key["length"], 64)

	@patch("enable_banking.setup.create_custom_fields")
	def test_install_and_migrate_hooks_are_idempotent(self, create_custom_fields):
		setup.after_install()
		setup.after_migrate()
		setup.before_tests()

		self.assertEqual(create_custom_fields.call_count, 3)
		for call in create_custom_fields.call_args_list:
			self.assertEqual(call.kwargs, {"update": True})
			self.assertEqual(call.args, (setup.get_custom_fields(),))


def _field(custom_fields, doctype, fieldname):
	return next(field for field in custom_fields[doctype] if field["fieldname"] == fieldname)
