from __future__ import annotations

import hashlib
import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

from enable_banking import onboarding


class TestAuthorizationStart(unittest.TestCase):
	@patch("enable_banking.onboarding.EnableBankingClient")
	@patch("enable_banking.onboarding._validate_parent_account")
	@patch("enable_banking.onboarding._require_manager")
	@patch("enable_banking.onboarding.frappe")
	def test_state_is_hashed_and_consent_is_clamped(
		self,
		frappe_mock,
		_require_manager,
		_validate_parent,
		client_class,
	):
		settings = SimpleNamespace(enabled=1, redirect_url="https://erp.example/callback")
		frappe_mock.get_single.return_value = settings
		frappe_mock.session.user = "manager@example.com"
		authorization = Mock(name="authorization")
		authorization.name = "AUTH-1"
		frappe_mock.get_doc.return_value.insert.return_value = authorization
		client = client_class.return_value
		client.get_aspsps.return_value = {
			"aspsps": [
				{
					"name": "OP",
					"country": "FI",
					"maximum_consent_validity": 10 * 86400,
					"auth_methods": [{"psu_type": "personal"}],
				}
			]
		}
		client.start_authorization.return_value = {
			"url": "https://auth.enablebanking.example/start",
			"authorization_id": "provider-auth",
		}

		with (
			patch("enable_banking.onboarding.secrets.token_urlsafe", return_value="raw-state"),
			patch(
				"enable_banking.onboarding.now_datetime",
				return_value=datetime(2026, 6, 18, 12, 0),
			),
			patch(
				"enable_banking.onboarding._utc_now",
				return_value=datetime(2026, 6, 18, 12, 0, tzinfo=UTC),
			),
		):
			result = onboarding.start_authorization(
				company="Test Company",
				parent_gl_account="Bank Accounts - TC",
				country="fi",
				aspsp_name="OP",
				psu_type="personal",
				consent_days=90,
				automatic_sync=1,
			)

		doc = frappe_mock.get_doc.call_args.args[0]
		self.assertNotIn("state", doc)
		self.assertEqual(
			doc["state_hash"],
			hashlib.sha256(b"raw-state").hexdigest(),
		)
		self.assertEqual(doc["consent_days"], 10)
		payload = client.start_authorization.call_args.args[0]
		self.assertEqual(payload["state"], "raw-state")
		self.assertTrue(payload["access"]["balances"])
		self.assertTrue(payload["access"]["transactions"])
		self.assertEqual(payload["access"]["valid_until"], "2026-06-28T12:00:00.000000+00:00")
		self.assertEqual(result["redirect_url"], "https://auth.enablebanking.example/start")


class TestCallbackState(unittest.TestCase):
	@patch("enable_banking.onboarding.frappe")
	def test_mismatched_state_is_rejected(self, frappe_mock):
		frappe_mock.db.sql.return_value = []

		self.assertIsNone(onboarding._consume_authorization("wrong-state"))
		frappe_mock.db.rollback.assert_called_once()

	@patch("enable_banking.onboarding.frappe")
	def test_replayed_state_is_rejected(self, frappe_mock):
		frappe_mock.db.sql.return_value = [
			SimpleNamespace(
				name="AUTH-1",
				status="Consumed",
				expires_at=datetime(2026, 6, 18, 12, 15),
			)
		]

		self.assertIsNone(onboarding._consume_authorization("state"))
		frappe_mock.db.rollback.assert_called_once()

	@patch("enable_banking.onboarding.now_datetime")
	@patch("enable_banking.onboarding.frappe")
	def test_expired_state_is_marked_expired(self, frappe_mock, now):
		now.return_value = datetime(2026, 6, 18, 12, 16)
		frappe_mock.db.sql.return_value = [
			SimpleNamespace(
				name="AUTH-1",
				status="Pending",
				expires_at=datetime(2026, 6, 18, 12, 15),
			)
		]

		self.assertIsNone(onboarding._consume_authorization("state"))
		update = frappe_mock.db.set_value.call_args.args[2]
		self.assertEqual(update["status"], "Expired")
		frappe_mock.db.commit.assert_called_once()

	@patch("enable_banking.onboarding._redirect")
	@patch("enable_banking.onboarding._consume_authorization")
	@patch("enable_banking.onboarding.frappe")
	def test_cancelled_callback_does_not_exchange_code(self, frappe_mock, consume, redirect):
		authorization = Mock()
		consume.return_value = authorization

		onboarding.callback(
			state="state",
			error="access_denied",
			error_description="Cancelled by user",
		)

		update = authorization.db_set.call_args.args[0]
		self.assertEqual(update["status"], "Cancelled")
		redirect.assert_called_once_with(onboarding.SETTINGS_ROUTE)

	@patch("enable_banking.onboarding._redirect")
	@patch("enable_banking.onboarding._create_connection_and_accounts")
	@patch("enable_banking.onboarding.EnableBankingClient")
	@patch("enable_banking.onboarding._consume_authorization")
	@patch("enable_banking.onboarding.frappe")
	def test_successful_callback_uses_fixed_connection_route(
		self,
		frappe_mock,
		consume,
		client_class,
		create_records,
		redirect,
	):
		authorization = Mock()
		consume.return_value = authorization
		client_class.return_value.authorize_session.return_value = {"session_id": "session"}
		create_records.return_value = SimpleNamespace(name="CONN 1")

		onboarding.callback(state="state", code="secret-code")

		redirect.assert_called_once_with("/app/enable-banking-connection/CONN%201")
		self.assertNotIn("secret-code", str(authorization.db_set.call_args))


class TestAccountDiscovery(unittest.TestCase):
	def test_provider_identification_hash_is_normalized_to_fixed_length(self):
		result = onboarding._account_identity_hash(
			"WwpbCiJhc3BzcF9uYW1lIgpdLApbCiJhc3BzcF9jb3VudHJ5IgpdLApbCiJhY2NvdW50IiwKInJlc291cmNlX2lkIgpdCl0=.Tcuyk97WZbS8FT0ru9OmKWquAFEpCahC+L46U/3j+sI="
		)

		self.assertEqual(len(result), 64)

	@patch("enable_banking.onboarding.convert_utc_to_system_timezone")
	def test_provider_z_datetime_is_normalized_for_mariadb(self, convert_timezone):
		convert_timezone.return_value = datetime(
			2026,
			12,
			15,
			18,
			27,
			57,
			369934,
			tzinfo=UTC,
		)

		result = onboarding._provider_datetime("2026-12-15T17:27:57.369934Z")

		self.assertEqual(result, datetime(2026, 12, 15, 18, 27, 57, 369934))
		self.assertIsNone(result.tzinfo)

	@patch("enable_banking.onboarding.frappe")
	def test_reauthorization_updates_account_by_identification_hash(self, frappe_mock):
		connection = SimpleNamespace(name="CONN-2", company="Test Company", automatic_sync=1)
		existing = Mock()
		existing.company = "Test Company"
		frappe_mock.db.get_value.return_value = "ACCOUNT-1"
		frappe_mock.get_doc.return_value = existing
		account = _provider_account()
		account["uid"] = "new-session-uid"

		result = onboarding._upsert_discovered_account(connection, account)

		self.assertIs(result, existing)
		self.assertEqual(
			frappe_mock.db.get_value.call_args.args[1]["identification_hash"],
			onboarding._account_identity_hash(account["identification_hash"]),
		)
		self.assertEqual(existing.update.call_args.args[0]["resource_uid"], "new-session-uid")
		existing.save.assert_called_once_with(ignore_permissions=True)

	@patch("enable_banking.onboarding.frappe")
	def test_existing_mapping_rejects_currency_mismatch(self, frappe_mock):
		integration = SimpleNamespace(
			name="EB-ACCOUNT",
			bank_account=None,
			company="Test Company",
			currency="EUR",
		)
		bank_account = SimpleNamespace(
			name="USD Account",
			is_company_account=1,
			company="Test Company",
			disabled=0,
			integration_id=None,
			account="Bank USD - TC",
			get=lambda fieldname: None,
		)
		frappe_mock.get_doc.return_value = bank_account
		frappe_mock.get_cached_value.return_value = "USD"
		frappe_mock.throw.side_effect = RuntimeError

		with self.assertRaises(RuntimeError):
			onboarding._validate_bank_account_mapping(integration, bank_account.name)

	@patch("enable_banking.onboarding.frappe")
	def test_bank_is_reused_by_provider_key(self, frappe_mock):
		frappe_mock.db.get_value.return_value = "Enable Banking - OP (FI)"
		bank = Mock()
		frappe_mock.get_doc.return_value = bank

		self.assertIs(onboarding._get_or_create_bank("FI", "OP"), bank)
		frappe_mock.db.get_value.assert_called_once_with(
			"Bank",
			{"enable_banking_aspsp_key": "FI::OP"},
		)

	def test_mask_and_account_identifier(self):
		account = _provider_account()
		self.assertEqual(onboarding._masked_identifier(account), "••••3547")
		self.assertEqual(
			onboarding._primary_account_identifier(account),
			{"iban": "FI0455231152453547", "account_number": None},
		)


def _provider_account():
	return {
		"uid": "session-uid",
		"identification_hash": "stable-hash",
		"identification_hashes": ["stable-hash"],
		"account_id": {"iban": "FI0455231152453547"},
		"name": "Account Holder",
		"details": "Everyday account",
		"product": "Current Account",
		"currency": "EUR",
		"usage": "PRIV",
		"cash_account_type": "CACC",
		"psu_status": "Account Holder",
	}
