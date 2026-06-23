import json
import unittest
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
DOCTYPE_ROOT = APP_ROOT / "enable_banking" / "doctype"
WORKSPACE_ROOT = APP_ROOT / "enable_banking" / "workspace"
RESTRICTED_ROLES = {"System Manager", "Accounts Manager"}


class TestDocTypeMetadata(unittest.TestCase):
	def test_phase_two_doctypes_exist_with_restricted_roles(self):
		settings = _load_doctype("enable_banking_settings")
		self.assertEqual(
			{permission["role"] for permission in settings["permissions"]},
			{"System Manager"},
		)

		for doctype_name in (
			"enable_banking_authorization",
			"enable_banking_connection",
			"enable_banking_account",
		):
			metadata = _load_doctype(doctype_name)
			self.assertEqual(
				{permission["role"] for permission in metadata["permissions"]},
				RESTRICTED_ROLES,
			)
			for permission in metadata["permissions"]:
				self.assertNotIn("create", permission)
				self.assertNotIn("delete", permission)

	def test_authorization_stores_only_hashed_state(self):
		fields = _fields("enable_banking_authorization")

		self.assertNotIn("state", fields)
		self.assertEqual(fields["state_hash"]["length"], 64)
		self.assertEqual(fields["state_hash"]["unique"], 1)
		self.assertEqual(fields["provider_session_id"]["hidden"], 1)
		self.assertEqual(fields["superseded_session_id"]["hidden"], 1)
		self.assertEqual(
			fields["reauthorization_connection"]["options"],
			"Enable Banking Connection",
		)

	def test_account_separates_stable_identity_from_session_uid(self):
		fields = _fields("enable_banking_account")

		self.assertEqual(fields["identification_hash"]["unique"], 1)
		self.assertEqual(fields["identification_hash"]["length"], 64)
		self.assertEqual(fields["resource_uid"]["unique"], 1)
		self.assertIn("identification_hashes_json", fields)
		self.assertNotIn("integration_id", fields)
		self.assertEqual(fields["connection"]["read_only"], 1)
		self.assertEqual(fields["bank_account"]["read_only"], 1)

	def test_connection_identity_fields_are_read_only(self):
		fields = _fields("enable_banking_connection")

		for fieldname in (
			"company",
			"parent_gl_account",
			"aspsp_name",
			"aspsp_country",
			"psu_type",
			"provider_session_id",
			"authorization",
		):
			self.assertEqual(fields[fieldname]["read_only"], 1)

	def test_phase_six_settings_connection_and_workspace_metadata(self):
		settings = _fields("enable_banking_settings")
		connection = _fields("enable_banking_connection")
		workspace = json.loads((WORKSPACE_ROOT / "enable_banking" / "enable_banking.json").read_text())

		self.assertEqual(
			settings["sync_interval"]["options"],
			"Every Hour\nFour Times a Day\nOnce a Day",
		)
		self.assertEqual(settings["expiry_notification_lead_days"]["default"], "7")
		self.assertEqual(settings["expiry_notification_frequency"]["options"], "Daily\nOnce")
		self.assertNotIn("api_url", settings)
		self.assertNotIn("private_key_source", settings)
		self.assertNotIn("private_key_file", settings)
		self.assertIn("last_sync_attempt_at", connection)
		self.assertIn("last_sync_success_at", connection)
		self.assertIn("sync_counts", connection)
		self.assertIn("expiry_notification_recipients", connection)
		self.assertNotIn("read_only", connection["expiry_notification_recipients"])
		self.assertEqual(connection["expiry_notification_last_valid_until"]["read_only"], 1)
		self.assertEqual(
			{shortcut["link_to"] for shortcut in workspace["shortcuts"]},
			{
				"Enable Banking Settings",
				"Enable Banking Connection",
				"Enable Banking Account",
				"Bank Transaction",
			},
		)
		transaction_shortcut = next(
			item for item in workspace["shortcuts"] if item["link_to"] == "Bank Transaction"
		)
		self.assertIn("enable_banking_account", transaction_shortcut["stats_filter"])


def _load_doctype(doctype_name):
	path = DOCTYPE_ROOT / doctype_name / f"{doctype_name}.json"
	return json.loads(path.read_text())


def _fields(doctype_name):
	return {
		field["fieldname"]: field for field in _load_doctype(doctype_name)["fields"] if "fieldname" in field
	}
