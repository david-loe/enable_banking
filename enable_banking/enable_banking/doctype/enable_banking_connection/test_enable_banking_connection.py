import json
import uuid
from datetime import datetime, timedelta

import frappe
from frappe.tests import IntegrationTestCase

from enable_banking.integrity import internal_operation
from enable_banking.onboarding import _account_identity_hash, create_erpnext_account
from enable_banking.tests.constants import TEST_COMPANY as COMPANY
from enable_banking.tests.constants import TEST_PARENT_ACCOUNT as PARENT_ACCOUNT

IGNORE_TEST_RECORD_DEPENDENCIES = [
	"Enable Banking Authorization",
	"Company",
	"Account",
	"Bank Account",
	"Currency",
]


class TestEnableBankingConnection(IntegrationTestCase):
	def test_direct_creation_is_rejected_even_when_permissions_are_ignored(self):
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc({"doctype": "Enable Banking Connection"}).insert(ignore_permissions=True)

	def test_delete_removes_child_accounts_and_unlinks_authorization(self):
		integration = self._make_integration_account()
		connection = frappe.get_doc("Enable Banking Connection", integration.connection)
		connection.db_set("authorization_status", "CLOSED")
		frappe.db.set_value(
			"Enable Banking Authorization",
			connection.authorization,
			"connection",
			connection.name,
		)
		created = create_erpnext_account(integration.name)

		with internal_operation():
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

	def test_delete_rejects_a_connection_with_a_possibly_active_session(self):
		integration = self._make_integration_account()

		with (
			self.assertRaisesRegex(Exception, "Close the Enable Banking connection"),
			internal_operation(),
		):
			frappe.delete_doc(
				"Enable Banking Connection",
				integration.connection,
				ignore_permissions=True,
			)

	def test_expiry_notification_recipients_are_configurable(self):
		integration = self._make_integration_account()
		connection = frappe.get_doc("Enable Banking Connection", integration.connection)
		connection.expiry_notification_recipients = "manager@example.com\nops@example.com"
		connection.save(ignore_permissions=True)

		self.assertEqual(
			frappe.db.get_value(
				"Enable Banking Connection",
				connection.name,
				"expiry_notification_recipients",
			),
			"manager@example.com\nops@example.com",
		)

	def test_expiry_notification_save_allows_equivalent_read_only_datetime_strings(self):
		integration = self._make_integration_account()
		now = datetime(2026, 6, 23, 10, 15, 30)
		timestamp_fields = (
			"valid_from",
			"valid_until",
			"expiry_notification_last_valid_until",
			"last_health_check_at",
			"last_successful_health_check_at",
			"last_authorized_at",
			"closed_at",
			"last_sync_attempt_at",
			"last_sync_success_at",
		)
		frappe.db.set_value(
			"Enable Banking Connection",
			integration.connection,
			{fieldname: now + timedelta(minutes=index) for index, fieldname in enumerate(timestamp_fields)},
			update_modified=False,
		)
		connection = frappe.get_doc("Enable Banking Connection", integration.connection)
		for fieldname in timestamp_fields:
			connection.set(fieldname, str(connection.get(fieldname)))
		connection.expiry_notification_recipients = "manager@example.com"
		connection.save(ignore_permissions=True)

		self.assertEqual(
			frappe.db.get_value(
				"Enable Banking Connection",
				connection.name,
				"expiry_notification_recipients",
			),
			"manager@example.com",
		)

	def test_expiry_notification_save_rejects_changed_read_only_datetime(self):
		integration = self._make_integration_account()
		frappe.db.set_value(
			"Enable Banking Connection",
			integration.connection,
			"valid_until",
			datetime(2026, 6, 23, 10, 15, 30),
			update_modified=False,
		)
		connection = frappe.get_doc("Enable Banking Connection", integration.connection)
		connection.valid_until = "2026-06-24 10:15:30"
		connection.expiry_notification_recipients = "manager@example.com"

		with self.assertRaisesRegex(frappe.PermissionError, "Valid Until"):
			connection.save(ignore_permissions=True)

	def test_invalid_expiry_notification_recipients_are_rejected(self):
		integration = self._make_integration_account()
		connection = frappe.get_doc("Enable Banking Connection", integration.connection)
		connection.expiry_notification_recipients = "not-an-email"

		with self.assertRaises(frappe.InvalidEmailAddressError):
			connection.save(ignore_permissions=True)

	def _make_integration_account(self):
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
			"currency": "EUR",
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
					"currency": "EUR",
					"cash_account_type": "CACC",
					"account_metadata_json": json.dumps(account),
				}
			).insert(ignore_permissions=True)
