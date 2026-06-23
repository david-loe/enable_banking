from __future__ import annotations

import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

from enable_banking import tasks


class TestSyncCadence(unittest.TestCase):
	def test_configured_intervals_are_due_at_expected_hours(self):
		self.assertTrue(tasks.is_sync_interval_due("Every Hour", now=datetime(2026, 6, 19, 5, 0)))
		self.assertTrue(tasks.is_sync_interval_due("Four Times a Day", now=datetime(2026, 6, 19, 12, 0)))
		self.assertFalse(tasks.is_sync_interval_due("Four Times a Day", now=datetime(2026, 6, 19, 13, 0)))
		self.assertTrue(tasks.is_sync_interval_due("Once a Day", now=datetime(2026, 6, 19, 0, 0)))
		self.assertFalse(tasks.is_sync_interval_due("Once a Day", now=datetime(2026, 6, 19, 1, 0)))

	@patch("enable_banking.tasks.enqueue_account_syncs")
	@patch("enable_banking.tasks.recover_stale_account_sync_states")
	@patch("enable_banking.tasks.now_datetime", return_value=datetime(2026, 6, 19, 12, 0))
	@patch("enable_banking.tasks.frappe")
	def test_scheduler_dispatches_only_when_enabled_and_due(
		self,
		frappe_mock,
		_now,
		recover_stale,
		enqueue_syncs,
	):
		frappe_mock.get_single.return_value = SimpleNamespace(
			enabled=1,
			automatic_sync=1,
			sync_interval="Four Times a Day",
		)
		enqueue_syncs.return_value = {"queued": 2, "accounts": ["A", "B"]}

		result = tasks.enqueue_scheduled_account_syncs()

		self.assertEqual(result["queued"], 2)
		recover_stale.assert_called_once_with()
		enqueue_syncs.assert_called_once_with(manual=False)

	@patch("enable_banking.tasks.enqueue_account_job", return_value=True)
	@patch("enable_banking.tasks.frappe")
	def test_scheduled_filter_requires_mapped_enabled_authorized_records(
		self,
		frappe_mock,
		enqueue_job,
	):
		frappe_mock.get_single.return_value = SimpleNamespace(enabled=1)
		frappe_mock.get_all.side_effect = [
			[
				SimpleNamespace(name="ACCOUNT-1", connection="CONNECTION-1"),
				SimpleNamespace(name="ACCOUNT-2", connection="CONNECTION-2"),
			],
			[SimpleNamespace(name="CONNECTION-1")],
		]

		result = tasks.enqueue_account_syncs(manual=False)

		self.assertEqual(result, {"queued": 1, "accounts": ["ACCOUNT-1"]})
		account_filters = frappe_mock.get_all.call_args_list[0].kwargs["filters"]
		self.assertEqual(account_filters["bank_account"], ["is", "set"])
		self.assertEqual(account_filters["automatic_sync"], 1)
		connection_filters = frappe_mock.get_all.call_args_list[1].kwargs["filters"]
		self.assertEqual(connection_filters["authorization_status"], "AUTHORIZED")
		self.assertEqual(connection_filters["automatic_sync"], 1)
		enqueue_job.assert_called_once_with("ACCOUNT-1", manual=False)


class TestAccountLocking(unittest.TestCase):
	@patch("enable_banking.tasks.EnableBankingClient")
	@patch("enable_banking.tasks.frappe")
	def test_locked_account_is_not_synchronized(self, frappe_mock, client_class):
		lock = Mock()
		lock.acquire.return_value = False
		frappe_mock.cache.return_value.lock.return_value = lock
		frappe_mock.local.site = "development.localhost"

		result = tasks.run_account_sync("ACCOUNT-1")

		self.assertEqual(result, {"locked": True, "successful": False})
		frappe_mock.get_doc.assert_not_called()
		client_class.assert_not_called()

	@patch("enable_banking.tasks.synchronize_account_transactions")
	@patch("enable_banking.tasks.refresh_account")
	@patch("enable_banking.tasks.verify_connection_session")
	@patch("enable_banking.tasks.EnableBankingClient")
	@patch(
		"enable_banking.tasks.now_datetime",
		side_effect=["account-attempt", "connection-attempt", "success"],
	)
	@patch("enable_banking.tasks.frappe")
	def test_authorized_account_runs_under_lock(
		self,
		frappe_mock,
		_now,
		client_class,
		verify_session,
		refresh_account,
		synchronize,
	):
		lock = Mock()
		lock.acquire.return_value = True
		lock.owned.return_value = True
		frappe_mock.cache.return_value.lock.return_value = lock
		frappe_mock.local.site = "development.localhost"
		account = SimpleNamespace(
			name="ACCOUNT-1",
			connection="CONNECTION-1",
			automatic_sync=1,
			last_error=None,
			db_set=Mock(),
		)
		connection = SimpleNamespace(
			name="CONNECTION-1",
			automatic_sync=1,
			db_set=Mock(),
		)
		frappe_mock.get_doc.side_effect = [account, connection]
		settings = SimpleNamespace(enabled=1, automatic_sync=1)
		frappe_mock.get_single.return_value = settings
		verify_session.return_value = {"status": "AUTHORIZED"}
		synchronize.return_value = {
			"successful": True,
			"fetched": 2,
			"created": 1,
			"duplicate": 1,
			"skipped": 0,
			"failed": 0,
		}

		result = tasks.run_account_sync("ACCOUNT-1")

		self.assertTrue(result["successful"])
		refresh_account.assert_called_once_with(
			account,
			connection=connection,
			client=client_class.return_value,
			raise_on_error=True,
			record_sync_status=False,
		)
		synchronize.assert_called_once()
		lock.release.assert_called_once_with()
		self.assertEqual(connection.last_sync_success_at, "success")
		self.assertIn("created 1", connection.sync_counts)

	@patch("enable_banking.tasks.frappe")
	def test_stale_queued_and_in_progress_states_are_recovered(self, frappe_mock):
		frappe_mock.get_all.return_value = [
			SimpleNamespace(name="ACCOUNT-1", sync_status="Queued"),
			SimpleNamespace(name="ACCOUNT-2", sync_status="In Progress"),
		]

		count = tasks.recover_stale_account_sync_states(now=datetime(2026, 6, 19, 12, 0))

		self.assertEqual(count, 2)
		self.assertEqual(frappe_mock.db.set_value.call_count, 2)
		for call in frappe_mock.db.set_value.call_args_list:
			self.assertEqual(call.args[2]["sync_status"], "Failed")

	def test_lock_lifetime_exceeds_background_job_timeout(self):
		self.assertGreater(tasks.SYNC_LOCK_TIMEOUT, tasks.SYNC_JOB_TIMEOUT)


class TestSessionHealth(unittest.TestCase):
	@patch("enable_banking.tasks.now_datetime", return_value=datetime(2026, 6, 19, 12, 0))
	@patch("enable_banking.tasks.frappe")
	def test_revoked_session_disables_connection_and_accounts(self, frappe_mock, _now):
		connection = SimpleNamespace(
			name="CONNECTION-1",
			provider_session_id="SESSION-1",
			db_set=Mock(),
		)
		client = Mock()
		client.get_session.return_value = {"status": "REVOKED"}

		result = tasks.verify_connection_session(connection, client=client)

		self.assertEqual(result["status"], "REVOKED")
		self.assertEqual(connection.authorization_status, "REVOKED")
		self.assertEqual(connection.automatic_sync, 0)
		account_values = frappe_mock.db.set_value.call_args.args[2]
		self.assertEqual(account_values["automatic_sync"], 0)
		self.assertEqual(account_values["sync_status"], "Disabled")

	@patch("enable_banking.tasks.now_datetime", return_value=datetime(2026, 6, 19, 12, 0))
	@patch("enable_banking.tasks._provider_datetime", return_value="normalized-valid-until")
	@patch("enable_banking.tasks.frappe")
	def test_authorized_session_updates_health_and_validity(
		self,
		frappe_mock,
		_provider_datetime,
		_now,
	):
		connection = SimpleNamespace(
			name="CONNECTION-1",
			provider_session_id="SESSION-1",
			db_set=Mock(),
		)
		client = Mock()
		client.get_session.return_value = {
			"status": "authorized",
			"access": {"valid_until": "2026-09-01T00:00:00Z"},
		}

		result = tasks.verify_connection_session(connection, client=client)

		self.assertEqual(result["status"], "AUTHORIZED")
		self.assertEqual(connection.last_successful_health_check_at, datetime(2026, 6, 19, 12, 0))
		self.assertEqual(connection.valid_until, "normalized-valid-until")
		frappe_mock.db.set_value.assert_not_called()


class TestAuthorizationCleanup(unittest.TestCase):
	@patch("enable_banking.tasks.now_datetime", return_value=datetime(2026, 6, 19, 12, 0))
	@patch("enable_banking.tasks.frappe")
	def test_old_consumed_authorizations_are_deleted(self, frappe_mock, _now):
		frappe_mock.get_all.return_value = ["AUTH-1", "AUTH-2"]

		count = tasks.purge_consumed_authorizations()

		self.assertEqual(count, 2)
		self.assertEqual(frappe_mock.delete_doc.call_count, 2)
		self.assertEqual(frappe_mock.db.set_value.call_count, 2)
		filters = frappe_mock.get_all.call_args.kwargs["filters"]
		self.assertEqual(
			filters["status"],
			["in", ["Consumed", "Cancelled", "Failed", "Expired"]],
		)


class TestSyncPermissions(unittest.TestCase):
	@patch("enable_banking.tasks.enqueue_account_syncs")
	@patch("enable_banking.tasks._require_manager")
	def test_settings_sync_requires_manager(self, require_manager, enqueue_syncs):
		enqueue_syncs.return_value = {"queued": 0, "accounts": []}

		tasks.sync_all_now()

		require_manager.assert_called_once_with()

	@patch("enable_banking.tasks.enqueue_account_syncs")
	@patch("enable_banking.tasks._require_manager")
	@patch("enable_banking.tasks.frappe")
	def test_connection_sync_checks_role_and_document_permission(
		self,
		frappe_mock,
		require_manager,
		enqueue_syncs,
	):
		connection = Mock()
		connection.name = "CONNECTION-1"
		frappe_mock.get_doc.return_value = connection
		enqueue_syncs.return_value = {"queued": 0, "accounts": []}

		tasks.sync_connection_now("CONNECTION-1")

		require_manager.assert_called_once_with()
		connection.check_permission.assert_called_once_with("write")
