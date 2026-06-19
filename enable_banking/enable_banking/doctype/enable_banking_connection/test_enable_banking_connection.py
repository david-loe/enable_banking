import json
import uuid

import frappe
from frappe.tests import IntegrationTestCase

from enable_banking.onboarding import _account_identity_hash, create_erpnext_account

COMPANY = "_Test Company 2"
PARENT_ACCOUNT = "Bank Accounts - _TC2"
IGNORE_TEST_RECORD_DEPENDENCIES = [
	"Enable Banking Authorization",
	"Company",
	"Account",
	"Bank Account",
	"Currency",
]


class TestEnableBankingConnection(IntegrationTestCase):
	def test_delete_removes_child_accounts_and_unlinks_authorization(self):
		integration = self._make_integration_account()
		connection = frappe.get_doc("Enable Banking Connection", integration.connection)
		frappe.db.set_value(
			"Enable Banking Authorization",
			connection.authorization,
			"connection",
			connection.name,
		)
		created = create_erpnext_account(integration.name)

		frappe.delete_doc(
			"Enable Banking Connection",
			connection.name,
			ignore_permissions=True,
		)

		self.assertFalse(frappe.db.exists("Enable Banking Connection", connection.name))
		self.assertFalse(frappe.db.exists("Enable Banking Account", integration.name))
		self.assertEqual(
			frappe.db.get_value(
				"Enable Banking Authorization",
				connection.authorization,
				"connection",
			),
			None,
		)
		self.assertTrue(frappe.db.exists("Bank Account", created["bank_account"]))
		self.assertEqual(
			frappe.db.get_value(
				"Bank Account",
				created["bank_account"],
				"enable_banking_account",
			),
			None,
		)

	def _make_integration_account(self):
		suffix = uuid.uuid4().hex
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
			"currency": "EUR",
			"cash_account_type": "CACC",
		}
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
				"currency": "EUR",
				"cash_account_type": "CACC",
				"account_metadata_json": json.dumps(account),
			}
		).insert(ignore_permissions=True)
