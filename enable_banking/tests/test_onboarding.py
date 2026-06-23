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
		frappe_mock.get_doc.return_value.insert.assert_called_once_with(ignore_permissions=True)
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
		authorization = SimpleNamespace(
			name="AUTH-1",
			status="Processing",
			provider_session_id=None,
			db_set=Mock(),
		)
		consume.return_value = authorization
		client_class.return_value.authorize_session.return_value = {"session_id": "session"}
		create_records.return_value = (SimpleNamespace(name="CONN 1"), None)

		onboarding.callback(state="state", code="secret-code")

		redirect.assert_called_once_with("/app/enable-banking-connection/CONN%201")
		self.assertNotIn("secret-code", str(authorization.db_set.call_args))

	@patch("enable_banking.onboarding._redirect")
	@patch(
		"enable_banking.onboarding._create_connection_and_accounts",
		side_effect=RuntimeError("database failed for /sessions/new-session"),
	)
	@patch("enable_banking.onboarding.EnableBankingClient")
	@patch("enable_banking.onboarding._consume_authorization")
	@patch("enable_banking.onboarding.frappe")
	def test_callback_closes_new_session_when_local_persistence_fails(
		self,
		frappe_mock,
		consume,
		client_class,
		_create_records,
		_redirect,
	):
		authorization = SimpleNamespace(
			name="AUTH-1",
			status="Processing",
			provider_session_id=None,
			db_set=Mock(),
		)
		consume.return_value = authorization
		client = client_class.return_value
		client.authorize_session.return_value = {"session_id": "new-session"}

		onboarding.callback(state="state", code="secret-code")

		client.delete_session.assert_called_once_with("new-session")
		update = frappe_mock.db.set_value.call_args.args[2]
		self.assertEqual(update["status"], "Failed")
		self.assertIsNone(update["provider_session_id"])
		self.assertNotIn("new-session", update["error_message"])

	@patch("enable_banking.onboarding._redirect")
	@patch(
		"enable_banking.onboarding._create_connection_and_accounts",
		side_effect=RuntimeError("database failed"),
	)
	@patch("enable_banking.onboarding.EnableBankingClient")
	@patch("enable_banking.onboarding._consume_authorization")
	@patch("enable_banking.onboarding.frappe")
	def test_callback_preserves_recoverable_state_when_new_session_cleanup_fails(
		self,
		frappe_mock,
		consume,
		client_class,
		_create_records,
		_redirect,
	):
		authorization = SimpleNamespace(
			name="AUTH-1",
			status="Processing",
			provider_session_id=None,
			db_set=Mock(),
		)
		consume.return_value = authorization
		client = client_class.return_value
		client.authorize_session.return_value = {"session_id": "new-session"}
		client.delete_session.side_effect = RuntimeError("failed /sessions/new-session")

		onboarding.callback(state="state", code="secret-code")

		update = frappe_mock.db.set_value.call_args.args[2]
		self.assertEqual(update["status"], "Cleanup Required")
		self.assertEqual(update["provider_session_id"], "new-session")
		self.assertNotIn("new-session", update["error_message"])

	@patch("enable_banking.onboarding._redirect")
	@patch("enable_banking.onboarding._create_connection_and_accounts")
	@patch("enable_banking.onboarding.EnableBankingClient")
	@patch("enable_banking.onboarding._consume_authorization")
	@patch("enable_banking.onboarding.frappe")
	def test_callback_recovers_a_previously_created_session(
		self,
		_frappe_mock,
		consume,
		client_class,
		create_records,
		redirect,
	):
		authorization = SimpleNamespace(
			name="AUTH-1",
			status="Session Created",
			provider_session_id="existing-session",
			db_set=Mock(),
		)
		consume.return_value = authorization
		client_class.return_value.get_session.return_value = {"accounts": []}
		create_records.return_value = (SimpleNamespace(name="CONN-1"), None)

		onboarding.callback(state="state")

		client_class.return_value.authorize_session.assert_not_called()
		client_class.return_value.get_session.assert_called_once_with("existing-session")
		session = create_records.call_args.args[1]
		self.assertEqual(session["session_id"], "existing-session")
		redirect.assert_called_once_with("/app/enable-banking-connection/CONN-1")

	@patch("enable_banking.onboarding._redirect")
	@patch("enable_banking.onboarding._close_superseded_session")
	@patch("enable_banking.onboarding.EnableBankingClient")
	@patch("enable_banking.onboarding._consume_authorization")
	@patch("enable_banking.onboarding.frappe")
	def test_callback_resumes_only_old_session_cleanup_after_reauthorization_commit(
		self,
		frappe_mock,
		consume,
		client_class,
		close_superseded,
		redirect,
	):
		authorization = SimpleNamespace(
			name="AUTH-1",
			status="Session Created",
			provider_session_id="new-session",
			connection="CONN-1",
			superseded_session_id="old-session",
		)
		connection = SimpleNamespace(name="CONN-1")
		consume.return_value = authorization
		frappe_mock.get_doc.return_value = connection

		onboarding.callback(state="state")

		close_superseded.assert_called_once_with(
			authorization,
			connection,
			"old-session",
			client_class.return_value,
		)
		client_class.return_value.get_session.assert_not_called()
		redirect.assert_called_once_with("/app/enable-banking-connection/CONN-1")

	@patch("enable_banking.onboarding._redirect")
	@patch("enable_banking.onboarding._close_superseded_session")
	@patch("enable_banking.onboarding._create_connection_and_accounts")
	@patch("enable_banking.onboarding.EnableBankingClient")
	@patch("enable_banking.onboarding._consume_authorization")
	@patch("enable_banking.onboarding.frappe")
	def test_successful_reauthorization_callback_closes_old_session(
		self,
		frappe_mock,
		consume,
		client_class,
		create_records,
		close_superseded,
		redirect,
	):
		authorization = SimpleNamespace(
			name="AUTH-1",
			status="Processing",
			provider_session_id=None,
			db_set=Mock(),
		)
		connection = SimpleNamespace(name="CONN-1")
		consume.return_value = authorization
		client = client_class.return_value
		client.authorize_session.return_value = {"session_id": "new-session"}
		create_records.return_value = (connection, "old-session")

		onboarding.callback(state="state", code="secret-code")

		persistence_update = authorization.db_set.call_args_list[-1].args[0]
		self.assertEqual(persistence_update["status"], "Session Created")
		self.assertEqual(persistence_update["superseded_session_id"], "old-session")
		close_superseded.assert_called_once_with(
			authorization,
			connection,
			"old-session",
			client,
		)
		frappe_mock.db.commit.assert_called()
		redirect.assert_called_once_with("/app/enable-banking-connection/CONN-1")

	@patch("enable_banking.onboarding._start_authorization")
	@patch("enable_banking.onboarding._require_manager")
	@patch("enable_banking.onboarding.frappe")
	def test_reauthorize_targets_the_existing_connection(
		self,
		frappe_mock,
		_require_manager,
		start,
	):
		connection = SimpleNamespace(
			name="CONN-1",
			authorization="AUTH-OLD",
			company="Test Company",
			parent_gl_account="Bank Accounts - TC",
			aspsp_country="FI",
			aspsp_name="OP",
			psu_type="personal",
			automatic_sync=1,
			check_permission=Mock(),
		)
		source = SimpleNamespace(consent_days=30, parent_gl_account="Bank Accounts - TC")
		frappe_mock.get_doc.side_effect = [connection, source]
		frappe_mock.db.exists.return_value = True

		onboarding.reauthorize("CONN-1")

		self.assertEqual(start.call_args.kwargs["reauthorization_connection"], "CONN-1")

	@patch("enable_banking.onboarding._refresh_connection_details_after_authorization")
	@patch("enable_banking.onboarding._upsert_discovered_account")
	@patch(
		"enable_banking.onboarding.now_datetime",
		return_value=datetime(2026, 6, 19, 12, 0),
	)
	@patch("enable_banking.onboarding.frappe")
	def test_reauthorization_reuses_connection_and_refreshes_once(
		self,
		frappe_mock,
		_now,
		upsert,
		refresh,
	):
		connection = Mock(
			name="connection",
			company="Test Company",
			aspsp_name="OP",
			aspsp_country="FI",
			psu_type="personal",
			provider_session_id="old-session",
		)
		connection.name = "CONN-1"
		frappe_mock.get_doc.return_value = connection
		authorization = SimpleNamespace(
			name="AUTH-NEW",
			company="Test Company",
			parent_gl_account="Bank Accounts - TC",
			automatic_sync=1,
			aspsp_name="OP",
			aspsp_country="FI",
			psu_type="personal",
			reauthorization_connection="CONN-1",
		)
		session = {
			"session_id": "new-session",
			"aspsp": {"name": "OP", "country": "FI"},
			"psu_type": "personal",
			"accounts": [{"uid": "one"}, {"uid": "two"}],
		}

		result, old_session = onboarding._create_connection_and_accounts(
			authorization,
			session,
		)

		self.assertIs(result, connection)
		self.assertEqual(old_session, "old-session")
		connection.save.assert_called_once_with(ignore_permissions=True)
		self.assertEqual(upsert.call_count, 2)
		refresh.assert_called_once_with(connection)

	@patch("enable_banking.onboarding.frappe")
	def test_failed_close_preserves_active_local_state(self, frappe_mock):
		connection = SimpleNamespace(
			name="CONN-1",
			authorization_status="AUTHORIZED",
			provider_session_id="secret-session",
			check_permission=Mock(),
			db_set=Mock(),
		)
		frappe_mock.get_doc.return_value = connection
		frappe_mock.throw.side_effect = RuntimeError

		with (
			patch("enable_banking.onboarding._require_manager"),
			patch("enable_banking.onboarding.EnableBankingClient") as client_class,
		):
			client_class.return_value.delete_session.side_effect = RuntimeError(
				"failed /sessions/secret-session"
			)
			with self.assertRaises(RuntimeError):
				onboarding.close_connection("CONN-1")

		self.assertEqual(connection.authorization_status, "AUTHORIZED")
		error = connection.db_set.call_args.args[1]
		self.assertNotIn("secret-session", error)

	@patch("enable_banking.onboarding.frappe")
	def test_successful_reauthorization_closes_superseded_session(self, frappe_mock):
		authorization = SimpleNamespace(db_set=Mock())
		connection = SimpleNamespace(db_set=Mock())
		client = Mock()

		onboarding._close_superseded_session(
			authorization,
			connection,
			"old-session",
			client,
		)

		client.delete_session.assert_called_once_with("old-session")
		update = authorization.db_set.call_args.args[0]
		self.assertEqual(update["status"], "Consumed")
		self.assertIsNone(update["superseded_session_id"])
		connection.db_set.assert_called_once_with(
			"last_error",
			None,
			update_modified=False,
		)
		frappe_mock.db.commit.assert_called_once()


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
		existing.connection = "CONN-2"
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

	@patch("enable_banking.integrity.frappe")
	@patch("enable_banking.onboarding.frappe")
	def test_existing_mapping_rejects_currency_mismatch(
		self,
		frappe_mock,
		integrity_frappe,
	):
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
		integrity_frappe.db.get_value.return_value = SimpleNamespace(
			company="Test Company",
			account_currency="USD",
			account_type="Bank",
			is_group=0,
			disabled=0,
		)
		integrity_frappe.throw.side_effect = RuntimeError("currency mismatch")

		with self.assertRaisesRegex(RuntimeError, "currency mismatch"):
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

	def test_minimal_account_metadata_drops_unneeded_provider_fields(self):
		account = _provider_account()
		account["provider_debug"] = {"secret": "not-required"}
		account["all_account_ids"] = [{"scheme_name": "IBAN", "identification": "FI0455231152453547"}]

		metadata = onboarding.minimal_account_metadata(account)

		self.assertEqual(metadata["account_id"], {"iban": "FI0455231152453547"})
		self.assertEqual(
			metadata["all_account_ids"],
			[{"scheme_name": "IBAN", "identification": "FI0455231152453547"}],
		)
		self.assertNotIn("provider_debug", metadata)


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
