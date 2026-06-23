import json
import uuid

import frappe
from frappe.tests import IntegrationTestCase

from enable_banking.integrity import internal_operation
from enable_banking.onboarding import (
	_account_identity_hash,
	create_erpnext_account,
	map_existing_account,
	unmap_account,
)

COMPANY = "_Test Company 2"
PARENT_ACCOUNT = "Bank Accounts - _TC2"
IGNORE_TEST_RECORD_DEPENDENCIES = [
	"Enable Banking Connection",
	"Company",
	"Bank Account",
	"Currency",
]


class TestEnableBankingAccount(IntegrationTestCase):
	def test_create_gl_and_bank_account(self):
		integration = self._make_integration_account()

		result = create_erpnext_account(integration.name)

		bank = frappe.get_doc("Bank", result["bank"])
		gl_account = frappe.get_doc("Account", result["gl_account"])
		bank_account = frappe.get_doc("Bank Account", result["bank_account"])
		self.assertEqual(bank.enable_banking_aspsp_key, "FI::Phase 3 Test Bank")
		self.assertEqual(gl_account.parent_account, PARENT_ACCOUNT)
		self.assertEqual(gl_account.account_currency, "EUR")
		self.assertEqual(bank_account.enable_banking_account, integration.name)
		self.assertEqual(bank_account.iban, "FI0455231152453547")
		self.assertEqual(bank_account.account_type, "Current")

	def test_map_existing_bank_account(self):
		source = self._make_integration_account()
		created = create_erpnext_account(source.name)
		target = self._make_integration_account(currency="EUR")
		source.db_set({"bank_account": None})
		frappe.db.set_value(
			"Bank Account",
			created["bank_account"],
			"enable_banking_account",
			None,
		)

		result = map_existing_account(target.name, created["bank_account"])

		self.assertEqual(result["bank_account"], created["bank_account"])
		self.assertEqual(
			frappe.db.get_value("Bank Account", created["bank_account"], "enable_banking_account"),
			target.name,
		)

	def test_unmap_clears_both_sides(self):
		integration = self._make_integration_account()
		created = create_erpnext_account(integration.name)

		unmap_account(integration.name)

		self.assertIsNone(frappe.db.get_value("Enable Banking Account", integration.name, "bank_account"))
		self.assertIsNone(
			frappe.db.get_value(
				"Bank Account",
				created["bank_account"],
				"enable_banking_account",
			)
		)

	def test_direct_internal_record_creation_is_rejected_even_when_permissions_are_ignored(self):
		existing = self._make_integration_account()
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc(
				{
					"doctype": "Enable Banking Account",
					"connection": existing.connection,
					"company": COMPANY,
					"resource_uid": uuid.uuid4().hex,
					"identification_hash": uuid.uuid4().hex.ljust(64, "0")[:64],
					"currency": "EUR",
				}
			).insert(ignore_permissions=True)

	def test_direct_mapping_edit_is_rejected(self):
		integration = self._make_integration_account()
		created = create_erpnext_account(integration.name)
		unmap_account(integration.name)
		integration.reload()
		integration.bank_account = created["bank_account"]

		with self.assertRaises(frappe.PermissionError):
			integration.save(ignore_permissions=True)

	def test_direct_internal_record_deletion_is_rejected(self):
		integration = self._make_integration_account()

		with self.assertRaises(frappe.PermissionError):
			frappe.delete_doc(
				"Enable Banking Account",
				integration.name,
				ignore_permissions=True,
			)

	def test_direct_bank_account_link_edit_is_rejected(self):
		integration = self._make_integration_account()
		created = create_erpnext_account(integration.name)
		unmap_account(integration.name)
		bank_account = frappe.get_doc("Bank Account", created["bank_account"])
		bank_account.enable_banking_account = integration.name

		with self.assertRaises(frappe.PermissionError):
			bank_account.save(ignore_permissions=True)

	def test_delete_detaches_mapped_bank_account(self):
		integration = self._make_integration_account()
		created = create_erpnext_account(integration.name)
		frappe.db.set_value(
			"Bank Account",
			created["bank_account"],
			{
				"enable_banking_booked_balance": 100,
				"enable_banking_available_balance": 90,
				"enable_banking_balance_currency": "EUR",
				"enable_banking_balance_as_of": frappe.utils.now_datetime(),
				"enable_banking_last_sync_at": frappe.utils.now_datetime(),
			},
		)

		with internal_operation():
			frappe.delete_doc(
				"Enable Banking Account",
				integration.name,
				ignore_permissions=True,
			)

		bank_account = frappe.get_doc("Bank Account", created["bank_account"])
		self.assertFalse(frappe.db.exists("Enable Banking Account", integration.name))
		self.assertEqual(bank_account.enable_banking_account, None)
		self.assertEqual(bank_account.enable_banking_booked_balance, 0)
		self.assertEqual(bank_account.enable_banking_available_balance, 0)
		self.assertEqual(bank_account.enable_banking_balance_currency, None)
		self.assertEqual(bank_account.enable_banking_balance_as_of, None)
		self.assertEqual(bank_account.enable_banking_last_sync_at, None)

	def test_delete_detaches_linked_bank_transactions(self):
		integration = self._make_integration_account()
		created = create_erpnext_account(integration.name)
		transaction_key = uuid.uuid4().hex.ljust(64, "0")[:64]
		transaction = frappe.get_doc(
			{
				"doctype": "Bank Transaction",
				"date": "2026-01-01",
				"bank_account": created["bank_account"],
				"deposit": 25,
				"currency": "EUR",
				"description": "Enable Banking cleanup test",
				"enable_banking_account": integration.name,
				"enable_banking_transaction_key": transaction_key,
			}
		).insert(ignore_permissions=True)

		with internal_operation():
			frappe.delete_doc(
				"Enable Banking Account",
				integration.name,
				ignore_permissions=True,
			)

		transaction.reload()
		self.assertFalse(frappe.db.exists("Enable Banking Account", integration.name))
		self.assertEqual(transaction.enable_banking_account, None)
		self.assertEqual(transaction.enable_banking_transaction_key, transaction_key)

	def _make_integration_account(self, currency="EUR"):
		suffix = uuid.uuid4().hex
		with internal_operation():
			authorization = frappe.get_doc(
				{
					"doctype": "Enable Banking Authorization",
					"status": "Consumed",
					"initiating_user": "Administrator",
					"expires_at": "2099-01-01 00:00:00",
					"consumed_at": frappe.utils.now_datetime(),
					"state_hash": suffix.ljust(64, "0"),
					"company": COMPANY,
					"parent_gl_account": PARENT_ACCOUNT,
					"aspsp_name": "Phase 3 Test Bank",
					"aspsp_country": "FI",
					"psu_type": "personal",
					"consent_days": 90,
				}
			).insert(ignore_permissions=True)
			connection = frappe.get_doc(
				{
					"doctype": "Enable Banking Connection",
					"authorization_status": "AUTHORIZED",
					"company": COMPANY,
					"parent_gl_account": PARENT_ACCOUNT,
					"aspsp_name": "Phase 3 Test Bank",
					"aspsp_country": "FI",
					"psu_type": "personal",
					"provider_session_id": suffix,
					"authorization": authorization.name,
				}
			).insert(ignore_permissions=True)
		account = {
			"account_id": {"iban": "FI0455231152453547"},
			"uid": f"uid-{suffix}",
			"identification_hash": f"hash-{suffix}",
			"identification_hashes": [f"hash-{suffix}"],
			"name": "Phase 3 Account Holder",
			"details": "Everyday account",
			"currency": currency,
			"cash_account_type": "CACC",
		}
		with internal_operation():
			return frappe.get_doc(
				{
					"doctype": "Enable Banking Account",
					"connection": connection.name,
					"company": COMPANY,
					"resource_uid": account["uid"],
					"identification_hash": _account_identity_hash(account["identification_hash"]),
					"identification_hashes_json": json.dumps(account["identification_hashes"]),
					"masked_identifier": "••••3547",
					"account_name": account["name"],
					"account_description": account["details"],
					"currency": currency,
					"cash_account_type": "CACC",
					"account_metadata_json": json.dumps(account),
				}
			).insert(ignore_permissions=True)
