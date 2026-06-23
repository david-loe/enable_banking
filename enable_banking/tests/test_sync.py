from __future__ import annotations

import json
import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch

from enable_banking import sync


class TestBalanceNormalization(unittest.TestCase):
	def test_balance_precedence_uses_type_order_before_timestamp(self):
		normalized = sync.normalize_balances(
			{
				"balances": [
					_balance("Closing available", "CLAV", "900.00", "EUR", "2026-06-18"),
					_balance("Older interim available", "ITAV", "100.00", "EUR", "2026-06-17"),
					_balance("Newest interim available", "ITAV", "110.00", "EUR", "2026-06-18"),
					_balance("Closing booked", "CLBD", "800.00", "EUR", "2026-06-18"),
					_balance("Interim booked", "ITBD", "810.00", "EUR", "2026-06-17"),
					_balance("Opening booked", "OPBD", "700.00", "EUR", "2026-06-18"),
				]
			}
		)

		snapshot = sync.select_balance_snapshot(normalized)

		self.assertEqual(snapshot["available"]["balance_type"], "ITAV")
		self.assertEqual(snapshot["available_amount"], Decimal("110.00"))
		self.assertEqual(snapshot["booked"]["balance_type"], "ITBD")
		self.assertEqual(snapshot["booked_amount"], Decimal("810.00"))
		self.assertIn("OPBD", {balance["balance_type"] for balance in normalized})

	def test_available_falls_back_to_closing_then_forward_available(self):
		normalized = sync.normalize_balances(
			{
				"balances": [
					_balance("Forward available", "FWAV", "50.00", "EUR", "2026-06-19"),
					_balance("Closing available", "CLAV", "40.00", "EUR", "2026-06-18"),
				]
			}
		)

		snapshot = sync.select_balance_snapshot(normalized)

		self.assertEqual(snapshot["available"]["balance_type"], "CLAV")
		self.assertEqual(snapshot["available_amount"], Decimal("40.00"))

	def test_currency_match_requires_selected_balances_to_match_expected_currency(self):
		snapshot = sync.select_balance_snapshot(
			sync.normalize_balances(
				{
					"balances": [
						_balance("Available", "ITAV", "10.00", "USD", "2026-06-18"),
						_balance("Booked", "ITBD", "10.00", "EUR", "2026-06-18"),
					]
				}
			)
		)

		self.assertFalse(sync.selected_balances_match_currency(snapshot, "EUR"))

	def test_selected_balances_without_timestamps_have_no_as_of(self):
		snapshot = sync.select_balance_snapshot(
			sync.normalize_balances(
				{
					"balances": [
						_balance("Booked", "ITBD", "52.89", "EUR", None),
						_balance("Available", "ITAV", "47.07", "EUR", None),
					]
				}
			)
		)

		self.assertEqual(snapshot["booked_amount"], Decimal("52.89"))
		self.assertEqual(snapshot["available_amount"], Decimal("47.07"))
		self.assertIsNone(snapshot["as_of"])

	def test_selected_balances_use_the_only_valid_timestamp(self):
		snapshot = sync.select_balance_snapshot(
			sync.normalize_balances(
				{
					"balances": [
						_balance("Booked", "ITBD", "52.89", "EUR", None),
						_balance("Available", "ITAV", "47.07", "EUR", "2026-06-19"),
					]
				}
			)
		)

		self.assertEqual(str(snapshot["as_of"]), "2026-06-19 00:00:00")

	def test_selected_balances_use_latest_valid_timestamp(self):
		snapshot = sync.select_balance_snapshot(
			sync.normalize_balances(
				{
					"balances": [
						_balance("Booked", "ITBD", "52.89", "EUR", "2026-06-18"),
						_balance("Available", "ITAV", "47.07", "EUR", "2026-06-19"),
					]
				}
			)
		)

		self.assertEqual(str(snapshot["as_of"]), "2026-06-19 00:00:00")

	def test_selected_balances_ignore_malformed_timestamp(self):
		snapshot = sync.select_balance_snapshot(
			sync.normalize_balances(
				{
					"balances": [
						_balance("Booked", "ITBD", "52.89", "EUR", "not-a-date"),
						_balance("Available", "ITAV", "47.07", "EUR", None),
					]
				}
			)
		)

		self.assertIsNone(snapshot["as_of"])


class TestBalancePersistence(unittest.TestCase):
	def test_booked_only_response_clears_existing_available_balance(self):
		account = Mock()
		account.currency = "EUR"
		normalized = sync.normalize_balances(
			{"balances": [_balance("Closing accounting balance", "ITBD", "13.39", "EUR", None)]}
		)
		snapshot = sync.select_balance_snapshot(normalized)

		sync._update_account_balance_fields(account, normalized, snapshot)

		values = account.db_set.call_args.args[0]
		self.assertEqual(values["booked_balance"], Decimal("13.39"))
		self.assertIsNone(values["available_balance"])
		self.assertEqual(values["balance_currency"], "EUR")
		self.assertIsNone(values["balance_as_of"])

	def test_available_only_response_clears_existing_booked_balance(self):
		account = Mock()
		account.currency = "EUR"
		normalized = sync.normalize_balances(
			{"balances": [_balance("Available", "ITAV", "12.34", "EUR", "2026-06-19")]}
		)
		snapshot = sync.select_balance_snapshot(normalized)

		sync._update_account_balance_fields(account, normalized, snapshot)

		values = account.db_set.call_args.args[0]
		self.assertEqual(values["available_balance"], Decimal("12.34"))
		self.assertIsNone(values["booked_balance"])
		self.assertEqual(values["balance_currency"], "EUR")

	def test_booked_and_available_response_updates_both_balances(self):
		account = Mock()
		account.currency = "EUR"
		normalized = sync.normalize_balances(
			{
				"balances": [
					_balance("Booked", "ITBD", "10.00", "EUR", "2026-06-19"),
					_balance("Available", "ITAV", "8.00", "EUR", "2026-06-19"),
				]
			}
		)
		snapshot = sync.select_balance_snapshot(normalized)

		sync._update_account_balance_fields(account, normalized, snapshot)

		values = account.db_set.call_args.args[0]
		self.assertEqual(values["booked_balance"], Decimal("10.00"))
		self.assertEqual(values["available_balance"], Decimal("8.00"))

	def test_integration_balance_fields_are_not_updated_on_currency_mismatch(self):
		account = Mock()
		account.currency = "EUR"
		normalized = sync.normalize_balances(
			{"balances": [_balance("Available", "ITAV", "10.00", "USD", "2026-06-18")]}
		)
		snapshot = sync.select_balance_snapshot(normalized)

		sync._update_account_balance_fields(account, normalized, snapshot)

		values = account.db_set.call_args.args[0]
		self.assertIn("latest_balances_json", values)
		self.assertEqual(json.loads(values["latest_balances_json"])[0]["balance_type"], "ITAV")
		self.assertNotIn("available_balance", values)
		self.assertNotIn("balance_currency", values)

	@patch("enable_banking.sync._validate_mapped_bank_account")
	@patch("enable_banking.sync.frappe")
	def test_currency_mismatch_only_clears_absent_balance_type(self, frappe_mock, _validate_mapping):
		account = SimpleNamespace(bank_account="BA-1")
		connection = SimpleNamespace(company="Test Company")
		frappe_mock.get_doc.return_value = SimpleNamespace(
			name="BA-1",
			company="Test Company",
			account="Bank USD - TC",
		)
		frappe_mock.get_cached_value.return_value = "EUR"
		snapshot = sync.select_balance_snapshot(
			sync.normalize_balances(
				{"balances": [_balance("Available", "ITAV", "10.00", "USD", "2026-06-18")]}
			)
		)

		sync._update_mapped_bank_account_balance_fields(account, connection, snapshot)

		values = frappe_mock.db.set_value.call_args.args[2]
		self.assertIsNone(values["enable_banking_booked_balance"])
		self.assertNotIn("enable_banking_available_balance", values)
		self.assertNotIn("enable_banking_balance_as_of", values)

	@patch("enable_banking.sync.now_datetime", return_value="2026-06-18 12:00:00")
	@patch("enable_banking.sync._validate_mapped_bank_account")
	@patch("enable_banking.sync.frappe")
	def test_mapped_bank_account_is_updated_when_currency_matches(self, frappe_mock, _validate_mapping, _now):
		account = SimpleNamespace(bank_account="BA-1")
		connection = SimpleNamespace(company="Test Company")
		frappe_mock.get_doc.return_value = SimpleNamespace(
			name="BA-1",
			company="Test Company",
			account="Bank EUR - TC",
		)
		frappe_mock.get_cached_value.return_value = "EUR"
		snapshot = sync.select_balance_snapshot(
			sync.normalize_balances({"balances": [_balance("Booked", "ITBD", "10.00", "EUR", "2026-06-18")]})
		)

		sync._update_mapped_bank_account_balance_fields(account, connection, snapshot)

		values = frappe_mock.db.set_value.call_args.args[2]
		self.assertEqual(values["enable_banking_booked_balance"], Decimal("10.00"))
		self.assertIsNone(values["enable_banking_available_balance"])
		self.assertEqual(values["enable_banking_balance_currency"], "EUR")
		self.assertEqual(values["enable_banking_last_sync_at"], "2026-06-18 12:00:00")

	@patch("enable_banking.sync.now_datetime", return_value="2026-06-18 12:00:00")
	@patch("enable_banking.sync._validate_mapped_bank_account")
	@patch("enable_banking.sync.frappe")
	def test_mapped_bank_account_updates_both_balances_when_present(
		self, frappe_mock, _validate_mapping, _now
	):
		account = SimpleNamespace(bank_account="BA-1")
		connection = SimpleNamespace(company="Test Company")
		frappe_mock.get_doc.return_value = SimpleNamespace(
			name="BA-1",
			company="Test Company",
			account="Bank EUR - TC",
		)
		frappe_mock.get_cached_value.return_value = "EUR"
		snapshot = sync.select_balance_snapshot(
			sync.normalize_balances(
				{
					"balances": [
						_balance("Booked", "ITBD", "10.00", "EUR", "2026-06-18"),
						_balance("Available", "ITAV", "9.00", "EUR", "2026-06-18"),
					]
				}
			)
		)

		sync._update_mapped_bank_account_balance_fields(account, connection, snapshot)

		values = frappe_mock.db.set_value.call_args.args[2]
		self.assertEqual(values["enable_banking_booked_balance"], Decimal("10.00"))
		self.assertEqual(values["enable_banking_available_balance"], Decimal("9.00"))

	@patch("enable_banking.sync.now_datetime", return_value="2026-06-18 12:00:00")
	@patch("enable_banking.sync._validate_mapped_bank_account")
	@patch("enable_banking.sync.frappe")
	def test_empty_successful_response_clears_balances_and_timestamp(
		self, frappe_mock, _validate_mapping, _now
	):
		account = SimpleNamespace(bank_account="BA-1")
		connection = SimpleNamespace(company="Test Company")
		frappe_mock.get_doc.return_value = SimpleNamespace(
			name="BA-1",
			company="Test Company",
			account="Bank EUR - TC",
		)
		frappe_mock.get_cached_value.return_value = "EUR"

		sync._update_mapped_bank_account_balance_fields(
			account,
			connection,
			sync.select_balance_snapshot([]),
		)

		values = frappe_mock.db.set_value.call_args.args[2]
		self.assertIsNone(values["enable_banking_booked_balance"])
		self.assertIsNone(values["enable_banking_available_balance"])
		self.assertIsNone(values["enable_banking_balance_as_of"])


class TestAccountRefresh(unittest.TestCase):
	@patch("enable_banking.sync.now_datetime", return_value="now")
	@patch("enable_banking.sync._update_doc")
	@patch("enable_banking.sync._refresh_balances")
	@patch("enable_banking.sync._update_account_details")
	def test_authorized_unmapped_account_fetches_balances(
		self, update_details, refresh_balances, _update_doc, _now
	):
		account = SimpleNamespace(resource_uid="ACCOUNT-1", bank_account=None)
		connection = SimpleNamespace(authorization_status="AUTHORIZED")
		client = Mock()
		client.get_account_details.return_value = {"uid": "ACCOUNT-1"}
		refresh_balances.return_value = {"balances_refreshed": True, "balance_count": 2}

		result = sync.refresh_account(account, connection=connection, client=client)

		update_details.assert_called_once_with(account, {"uid": "ACCOUNT-1"})
		refresh_balances.assert_called_once_with(account, connection, client)
		self.assertTrue(result["balances_refreshed"])
		self.assertEqual(result["balance_count"], 2)

	@patch("enable_banking.sync.now_datetime", return_value="now")
	@patch("enable_banking.sync._update_doc")
	@patch("enable_banking.sync._refresh_balances")
	@patch("enable_banking.sync._update_account_details")
	def test_authorized_mapped_account_still_fetches_balances(
		self, _update_details, refresh_balances, _update_doc, _now
	):
		account = SimpleNamespace(resource_uid="ACCOUNT-1", bank_account="BA-1")
		connection = SimpleNamespace(authorization_status="AUTHORIZED")
		client = Mock()
		client.get_account_details.return_value = {"uid": "ACCOUNT-1"}
		refresh_balances.return_value = {"balances_refreshed": True, "balance_count": 1}

		result = sync.refresh_account(account, connection=connection, client=client)

		refresh_balances.assert_called_once_with(account, connection, client)
		self.assertTrue(result["balances_refreshed"])

	@patch("enable_banking.sync.now_datetime", return_value="now")
	@patch("enable_banking.sync._update_doc")
	@patch("enable_banking.sync._refresh_balances")
	@patch("enable_banking.sync._update_account_details")
	def test_unauthorized_connection_skips_balances(
		self, _update_details, refresh_balances, _update_doc, _now
	):
		account = SimpleNamespace(resource_uid="ACCOUNT-1", bank_account=None)
		connection = SimpleNamespace(authorization_status="CLOSED")
		client = Mock()
		client.get_account_details.return_value = {"uid": "ACCOUNT-1"}

		result = sync.refresh_account(account, connection=connection, client=client)

		refresh_balances.assert_not_called()
		self.assertFalse(result["balances_refreshed"])

	@patch("enable_banking.sync.now_datetime", return_value="now")
	@patch("enable_banking.sync._update_doc")
	@patch("enable_banking.sync._refresh_balances")
	@patch("enable_banking.sync._update_account_details")
	def test_fetch_balances_false_skips_balances(self, _update_details, refresh_balances, _update_doc, _now):
		account = SimpleNamespace(resource_uid="ACCOUNT-1", bank_account=None)
		connection = SimpleNamespace(authorization_status="AUTHORIZED")
		client = Mock()
		client.get_account_details.return_value = {"uid": "ACCOUNT-1"}

		result = sync.refresh_account(
			account,
			connection=connection,
			client=client,
			fetch_balances=False,
		)

		refresh_balances.assert_not_called()
		self.assertFalse(result["balances_refreshed"])


class TestTransactionNormalization(unittest.TestCase):
	def test_credit_uses_booking_date_positive_deposit_and_debtor(self):
		transaction = _transaction(
			direction="CRDT",
			amount="-12.34",
			booking_date="2026-06-19",
			value_date="2026-06-18",
			transaction_date="2026-06-17",
			debtor={"name": "Sender"},
			debtor_account={"iban": "FI2112345600000785"},
		)

		normalized = sync.normalize_transaction(transaction, "account-hash")

		self.assertEqual(normalized["date"], date(2026, 6, 19))
		self.assertEqual(normalized["deposit"], Decimal("12.34"))
		self.assertEqual(normalized["withdrawal"], Decimal("0"))
		self.assertEqual(normalized["bank_party_name"], "Sender")
		self.assertEqual(normalized["bank_party_iban"], "FI2112345600000785")

	def test_debit_falls_back_to_value_date_and_uses_creditor(self):
		transaction = _transaction(
			direction="DBIT",
			amount="8.50",
			booking_date=None,
			value_date="2026-06-18",
			transaction_date="2026-06-17",
			creditor={"name": "Recipient"},
			creditor_account={"other": {"identification": "123456"}},
		)

		normalized = sync.normalize_transaction(transaction, "account-hash")

		self.assertEqual(normalized["date"], date(2026, 6, 18))
		self.assertEqual(normalized["deposit"], Decimal("0"))
		self.assertEqual(normalized["withdrawal"], Decimal("8.50"))
		self.assertEqual(normalized["bank_party_name"], "Recipient")
		self.assertEqual(normalized["bank_party_account_number"], "123456")

	def test_description_reference_transaction_id_and_type_precedence(self):
		transaction = _transaction(
			entry_reference="ENTRY-1",
			transaction_id="UNSTABLE-ID",
			reference_number="RF-1",
			remittance_information=["Invoice 1", "Second line"],
			note="Customer note",
			debtor={"name": "Sender"},
			bank_transaction_code={
				"description": "A transaction description longer than fifty characters ABCDEFGHIJK",
				"code": "PMNT",
				"sub_code": "ICDT",
			},
		)

		normalized = sync.normalize_transaction(transaction, "account-hash")

		self.assertEqual(normalized["transaction_id"], "ENTRY-1")
		self.assertEqual(normalized["reference_number"], "RF-1")
		self.assertEqual(
			normalized["description"],
			"Invoice 1\nSecond line\nCustomer note\n"
			"A transaction description longer than fifty characters ABCDEFGHIJK\nSender",
		)
		self.assertEqual(len(normalized["transaction_type"]), 50)

	def test_provider_transaction_id_is_used_when_entry_reference_is_missing(self):
		transaction = _transaction(entry_reference=None, transaction_id="PROVIDER-ID")

		normalized = sync.normalize_transaction(transaction, "account-hash")

		self.assertEqual(normalized["transaction_id"], "PROVIDER-ID")
		self.assertEqual(
			normalized["enable_banking_transaction_key"],
			sync.normalize_transaction(transaction, "account-hash")["enable_banking_transaction_key"],
		)

	def test_fingerprint_changes_for_different_accounts(self):
		transaction = _transaction(entry_reference=None, transaction_id=None)

		first = sync.normalize_transaction(transaction, "account-one")
		second = sync.normalize_transaction(transaction, "account-two")

		self.assertNotEqual(
			first["enable_banking_transaction_key"],
			second["enable_banking_transaction_key"],
		)
		self.assertEqual(first["transaction_id"], first["enable_banking_transaction_key"])

	def test_non_booked_transaction_is_rejected(self):
		with self.assertRaises(ValueError):
			sync.normalize_transaction(_transaction(status="PDNG"), "account-hash")


class TestTransactionSync(unittest.TestCase):
	def test_initial_and_incremental_ranges_use_settings(self):
		settings = SimpleNamespace(initial_import_days=90, overlap_days=7)

		initial = sync.transaction_sync_range(
			SimpleNamespace(last_successful_end_date=None),
			settings,
			today="2026-06-19",
		)
		incremental = sync.transaction_sync_range(
			SimpleNamespace(last_successful_end_date="2026-06-18"),
			settings,
			today="2026-06-19",
		)

		self.assertEqual(initial, (date(2026, 3, 21), date(2026, 6, 19)))
		self.assertEqual(incremental, (date(2026, 6, 11), date(2026, 6, 19)))

	@patch("enable_banking.sync._insert_bank_transaction")
	@patch("enable_banking.sync._validate_transaction_sync_account")
	@patch("enable_banking.sync.now_datetime", side_effect=["attempt", "complete"])
	@patch("enable_banking.sync.frappe")
	def test_booked_only_filtering_counts_and_advances_watermark(
		self,
		frappe_mock,
		_now,
		_validate,
		insert_transaction,
	):
		account = _integration_account()
		connection = SimpleNamespace(authorization_status="AUTHORIZED", company="Test Company")
		client = Mock()
		client.get_account_transactions.return_value = {
			"transactions": [_transaction(), _transaction(status="PDNG")]
		}
		insert_transaction.return_value = "created"

		result = sync.synchronize_account_transactions(
			account,
			connection=connection,
			client=client,
			settings=SimpleNamespace(initial_import_days=90, overlap_days=7),
			today="2026-06-19",
		)

		self.assertEqual(result["fetched"], 2)
		self.assertEqual(result["created"], 1)
		self.assertEqual(result["skipped"], 1)
		self.assertTrue(result["successful"])
		self.assertEqual(account.last_successful_end_date, date(2026, 6, 19))
		frappe_mock.db.set_value.assert_called_once()
		request = client.get_account_transactions.call_args
		self.assertEqual(request.kwargs["max_pages"], 20)
		self.assertEqual(request.kwargs["max_transactions"], 5000)

	@patch("enable_banking.sync._insert_bank_transaction")
	@patch("enable_banking.sync._validate_transaction_sync_account")
	@patch("enable_banking.sync.now_datetime", return_value="attempt")
	@patch("enable_banking.sync.frappe")
	def test_partial_failure_preserves_previous_watermark(
		self,
		frappe_mock,
		_now,
		_validate,
		insert_transaction,
	):
		account = _integration_account(last_successful_end_date="2026-06-10")
		connection = SimpleNamespace(authorization_status="AUTHORIZED", company="Test Company")
		client = Mock()
		client.get_account_transactions.return_value = {
			"transactions": [
				_transaction(entry_reference="ONE"),
				_transaction(entry_reference="TWO"),
			]
		}
		insert_transaction.side_effect = ["created", ValueError("bad transaction")]

		result = sync.synchronize_account_transactions(
			account,
			connection=connection,
			client=client,
			settings=SimpleNamespace(initial_import_days=90, overlap_days=7),
			today="2026-06-19",
		)

		self.assertEqual(result["created"], 1)
		self.assertEqual(result["failed"], 1)
		self.assertFalse(result["successful"])
		self.assertEqual(account.last_successful_end_date, "2026-06-10")
		self.assertEqual(account.last_failed_count, 1)
		frappe_mock.db.set_value.assert_not_called()

	@patch("enable_banking.sync._insert_bank_transaction", return_value="duplicate")
	@patch("enable_banking.sync._validate_transaction_sync_account")
	@patch("enable_banking.sync.now_datetime", side_effect=["attempt", "complete"])
	@patch("enable_banking.sync.frappe")
	def test_duplicate_is_a_successful_noop(
		self,
		_frappe,
		_now,
		_validate,
		_insert_transaction,
	):
		account = _integration_account()
		client = Mock()
		client.get_account_transactions.return_value = {"transactions": [_transaction()]}

		result = sync.synchronize_account_transactions(
			account,
			connection=SimpleNamespace(authorization_status="AUTHORIZED", company="Test Company"),
			client=client,
			settings=SimpleNamespace(initial_import_days=90, overlap_days=7),
			today="2026-06-19",
		)

		self.assertEqual(result["created"], 0)
		self.assertEqual(result["duplicate"], 1)
		self.assertTrue(result["successful"])


class TestBankTransactionInsertion(unittest.TestCase):
	@patch("enable_banking.sync.frappe")
	def test_existing_transaction_key_is_a_duplicate_noop(self, frappe_mock):
		frappe_mock.db.exists.return_value = "ACC-BTN-2026-00001"

		result = sync._insert_bank_transaction(
			_integration_account(),
			{"enable_banking_transaction_key": "key"},
			index=0,
		)

		self.assertEqual(result, "duplicate")
		frappe_mock.get_doc.assert_not_called()
		frappe_mock.db.savepoint.assert_not_called()

	@patch("enable_banking.sync.frappe")
	def test_insert_and_submit_run_inside_savepoint(self, frappe_mock):
		frappe_mock.db.exists.return_value = None
		transaction_doc = Mock()
		frappe_mock.get_doc.return_value = transaction_doc

		result = sync._insert_bank_transaction(
			_integration_account(),
			{"enable_banking_transaction_key": "key", "date": date(2026, 6, 19)},
			index=3,
		)

		self.assertEqual(result, "created")
		frappe_mock.db.savepoint.assert_called_once_with("enable_banking_transaction_3")
		transaction_doc.insert.assert_called_once_with(ignore_permissions=True)
		transaction_doc.submit.assert_called_once_with()
		frappe_mock.db.release_savepoint.assert_called_once_with("enable_banking_transaction_3")

	@patch("enable_banking.sync.frappe")
	def test_failed_insert_rolls_back_to_its_savepoint(self, frappe_mock):
		frappe_mock.db.exists.side_effect = [None, None]
		transaction_doc = Mock()
		transaction_doc.insert.side_effect = ValueError("invalid")
		frappe_mock.get_doc.return_value = transaction_doc

		with self.assertRaises(ValueError):
			sync._insert_bank_transaction(
				_integration_account(),
				{"enable_banking_transaction_key": "key"},
				index=5,
			)

		frappe_mock.db.rollback.assert_called_once_with(save_point="enable_banking_transaction_5")
		frappe_mock.db.release_savepoint.assert_called_once_with("enable_banking_transaction_5")


def _balance(name, balance_type, amount, currency, reference_date):
	return {
		"name": name,
		"balance_type": balance_type,
		"balance_amount": {"amount": amount, "currency": currency},
		"reference_date": reference_date,
	}


def _transaction(**overrides):
	transaction = {
		"entry_reference": "ENTRY-1",
		"transaction_id": "TRANSACTION-1",
		"transaction_amount": {"amount": "10.00", "currency": "EUR"},
		"credit_debit_indicator": "CRDT",
		"status": "BOOK",
		"booking_date": "2026-06-19",
		"value_date": "2026-06-18",
		"transaction_date": "2026-06-17",
		"reference_number": None,
		"remittance_information": ["Payment"],
		"debtor": {"name": "Sender"},
		"debtor_account": {"iban": "FI2112345600000785"},
		"creditor": {"name": "Recipient"},
		"creditor_account": {"iban": "FI7850000012345678"},
		"bank_transaction_code": {"description": "Credit transfer", "code": "PMNT", "sub_code": "ICDT"},
	}
	transaction.update(overrides)
	if "direction" in overrides:
		transaction["credit_debit_indicator"] = overrides["direction"]
	if "amount" in overrides:
		transaction["transaction_amount"]["amount"] = overrides["amount"]
	transaction.pop("direction", None)
	transaction.pop("amount", None)
	return transaction


def _integration_account(last_successful_end_date=None):
	return SimpleNamespace(
		name="EB-ACCOUNT-1",
		connection="EB-CONNECTION-1",
		resource_uid="RESOURCE-1",
		identification_hash="account-hash",
		bank_account="BANK-ACCOUNT-1",
		currency="EUR",
		last_successful_end_date=last_successful_end_date,
		db_set=Mock(),
	)
