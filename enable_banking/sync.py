from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, convert_utc_to_system_timezone, get_datetime, getdate, now_datetime, nowdate

from enable_banking.client import EnableBankingClient
from enable_banking.configuration import SETTINGS_DOCTYPE
from enable_banking.integrity import (
	validate_bank_account_mapping,
	validate_reciprocal_mapping,
)
from enable_banking.onboarding import (
	ACCOUNT_DOCTYPE,
	CONNECTION_DOCTYPE,
	_account_identity_hash,
	_masked_identifier,
	minimal_account_metadata,
)
from enable_banking.operations import log_operational_error, sanitized_error

AVAILABLE_BALANCE_PRECEDENCE = ("ITAV", "CLAV", "FWAV")
BOOKED_BALANCE_PRECEDENCE = ("ITBD", "CLBD")
AUTHORIZED_STATUS = "AUTHORIZED"
BOOKED_TRANSACTION_STATUS = "BOOK"
CREDIT_INDICATOR = "CRDT"
DEBIT_INDICATOR = "DBIT"
DEFAULT_INITIAL_IMPORT_DAYS = 90
DEFAULT_OVERLAP_DAYS = 7
DEFAULT_MAX_TRANSACTION_PAGES = 20
DEFAULT_MAX_TRANSACTIONS_PER_SYNC = 5000


@frappe.whitelist()
def refresh_account_details_and_balances(integration_account: str) -> dict[str, Any]:
	_require_manager()
	account = frappe.get_doc(ACCOUNT_DOCTYPE, integration_account)
	account.check_permission("write")
	return refresh_account(account, raise_on_error=True)


@frappe.whitelist()
def refresh_connection_details_and_balances(connection: str) -> dict[str, Any]:
	_require_manager()
	connection_doc = frappe.get_doc(CONNECTION_DOCTYPE, connection)
	connection_doc.check_permission("write")
	return refresh_connection(connection_doc, fetch_balances=True, raise_on_error=True)


@frappe.whitelist()
def sync_account_transactions(integration_account: str) -> dict[str, Any]:
	from enable_banking.tasks import sync_account_now

	return sync_account_now(integration_account)


def synchronize_account_transactions(
	account,
	*,
	connection=None,
	client: EnableBankingClient | None = None,
	settings=None,
	today: date | str | None = None,
) -> dict[str, Any]:
	client = client or EnableBankingClient()
	connection = connection or frappe.get_doc(CONNECTION_DOCTYPE, account.connection)
	settings = settings or frappe.get_single(SETTINGS_DOCTYPE)
	date_from, date_to = transaction_sync_range(account, settings, today=today)
	attempted_at = now_datetime()
	counts = _empty_transaction_counts()
	_update_doc(
		account,
		{
			"sync_status": "In Progress",
			"last_sync_attempt_at": attempted_at,
			"last_error": None,
		},
	)

	try:
		_validate_transaction_sync_account(account, connection)
		response = client.get_account_transactions(
			account.resource_uid,
			date_from=date_from,
			date_to=date_to,
			max_pages=max(
				1,
				cint(getattr(settings, "max_transaction_pages", DEFAULT_MAX_TRANSACTION_PAGES))
				or DEFAULT_MAX_TRANSACTION_PAGES,
			),
			max_transactions=max(
				1,
				cint(
					getattr(
						settings,
						"max_transactions_per_sync",
						DEFAULT_MAX_TRANSACTIONS_PER_SYNC,
					)
				)
				or DEFAULT_MAX_TRANSACTIONS_PER_SYNC,
			),
		)
		transactions = response.get("transactions") if isinstance(response, dict) else None
		if not isinstance(transactions, list):
			raise ValueError(_("Enable Banking returned an invalid transaction list."))
	except Exception as exc:
		counts["failed"] = 1
		_record_transaction_sync_failure(account, counts, exc)
		return {**counts, "date_from": date_from, "date_to": date_to, "successful": False}

	counts["fetched"] = len(transactions)
	errors: list[str] = []
	for index, transaction in enumerate(transactions):
		if not isinstance(transaction, dict):
			counts["failed"] += 1
			errors.append(_("Transaction {0} was not an object.").format(index + 1))
			continue
		if transaction.get("status") != BOOKED_TRANSACTION_STATUS:
			counts["skipped"] += 1
			continue

		try:
			normalized = normalize_transaction(transaction, account.identification_hash)
			result = _insert_bank_transaction(account, normalized, index=index)
			counts[result] += 1
		except Exception as exc:
			counts["failed"] += 1
			errors.append(_safe_error(exc))

	if counts["failed"]:
		error = "; ".join(dict.fromkeys(error for error in errors if error))
		_record_transaction_sync_failure(
			account,
			counts,
			Exception(error or _("One or more transactions failed to import.")),
		)
		return {**counts, "date_from": date_from, "date_to": date_to, "successful": False}

	completed_at = now_datetime()
	_update_doc(
		account,
		{
			"sync_status": "Success",
			"last_sync_success_at": completed_at,
			"last_successful_end_date": date_to,
			"last_fetched_count": counts["fetched"],
			"last_created_count": counts["created"],
			"last_duplicate_count": counts["duplicate"],
			"last_skipped_count": counts["skipped"],
			"last_failed_count": 0,
			"last_error": None,
		},
	)
	frappe.db.set_value(
		"Bank Account",
		account.bank_account,
		"enable_banking_last_sync_at",
		completed_at,
		update_modified=False,
	)
	return {**counts, "date_from": date_from, "date_to": date_to, "successful": True}


def transaction_sync_range(account, settings, *, today: date | str | None = None) -> tuple[date, date]:
	date_to = getdate(today or nowdate())
	if account.last_successful_end_date:
		overlap_days = max(
			0,
			cint(getattr(settings, "overlap_days", DEFAULT_OVERLAP_DAYS)),
		)
		date_from = getdate(account.last_successful_end_date) - timedelta(days=overlap_days)
	else:
		initial_days = max(
			1,
			cint(getattr(settings, "initial_import_days", DEFAULT_INITIAL_IMPORT_DAYS))
			or DEFAULT_INITIAL_IMPORT_DAYS,
		)
		date_from = date_to - timedelta(days=initial_days)
	return date_from, date_to


def normalize_transaction(transaction: dict[str, Any], account_identification_hash: str) -> dict[str, Any]:
	if not isinstance(transaction, dict):
		raise ValueError(_("Enable Banking transaction must be an object."))
	if transaction.get("status") != BOOKED_TRANSACTION_STATUS:
		raise ValueError(_("Only booked Enable Banking transactions can be normalized."))

	direction = _required_text(transaction.get("credit_debit_indicator"), "credit_debit_indicator")
	if direction not in (CREDIT_INDICATOR, DEBIT_INDICATOR):
		raise ValueError(_("Unsupported transaction credit/debit indicator."))

	amount_data = transaction.get("transaction_amount")
	if not isinstance(amount_data, dict):
		raise ValueError(_("Transaction amount is missing."))
	amount = _decimal_or_none(amount_data.get("amount"))
	currency = _clean_text(amount_data.get("currency"))
	if amount is None or not currency:
		raise ValueError(_("Transaction amount and currency are required."))
	amount = abs(amount)

	transaction_date = _transaction_date(transaction)
	entry_reference = _clean_text(transaction.get("entry_reference"))
	provider_transaction_id = _clean_text(transaction.get("transaction_id"))
	reference_number = _clean_text(transaction.get("reference_number")) or entry_reference
	remittance = _text_list(transaction.get("remittance_information"))
	counterparty = _counterparty(transaction, direction)
	transaction_code = _transaction_code(transaction.get("bank_transaction_code"))
	fingerprint = transaction_fingerprint(
		account_identification_hash=account_identification_hash,
		transaction_date=transaction_date,
		amount=amount,
		currency=currency,
		direction=direction,
		reference=reference_number,
		remittance=remittance,
		counterparty=counterparty,
		transaction_code=transaction_code,
	)
	transaction_key = (
		_sha256_json([account_identification_hash, entry_reference]) if entry_reference else fingerprint
	)
	description_parts = [
		*remittance,
		_clean_text(transaction.get("note")),
		transaction_code.get("description"),
		counterparty.get("name"),
	]
	description = "\n".join(dict.fromkeys(part for part in description_parts if _clean_text(part)))
	transaction_type = (transaction_code.get("description") or transaction_code.get("display_code") or "")[
		:50
	]

	values = {
		"date": transaction_date,
		"deposit": amount if direction == CREDIT_INDICATOR else Decimal("0"),
		"withdrawal": amount if direction == DEBIT_INDICATOR else Decimal("0"),
		"currency": currency,
		"transaction_id": entry_reference or provider_transaction_id or fingerprint,
		"reference_number": reference_number,
		"description": description,
		"transaction_type": transaction_type,
		"bank_party_name": counterparty.get("name"),
		"bank_party_iban": counterparty.get("iban"),
		"bank_party_account_number": counterparty.get("account_number"),
		"enable_banking_transaction_key": transaction_key,
	}
	return values


def transaction_fingerprint(
	*,
	account_identification_hash: str,
	transaction_date: date,
	amount: Decimal,
	currency: str,
	direction: str,
	reference: str | None,
	remittance: list[str],
	counterparty: dict[str, str | None],
	transaction_code: dict[str, str | None],
) -> str:
	"""Create the fallback key from stable transaction fields documented in PLAN.md."""
	return _sha256_json(
		{
			"account": account_identification_hash,
			"date": transaction_date.isoformat(),
			"amount": _canonical_decimal(amount),
			"currency": currency,
			"direction": direction,
			"reference": reference or "",
			"remittance": remittance,
			"counterparty": {
				"name": counterparty.get("name") or "",
				"iban": counterparty.get("iban") or "",
				"account_number": counterparty.get("account_number") or "",
			},
			"transaction_code": {
				"description": transaction_code.get("description") or "",
				"code": transaction_code.get("code") or "",
				"sub_code": transaction_code.get("sub_code") or "",
			},
		}
	)


def refresh_connection(
	connection,
	*,
	client: EnableBankingClient | None = None,
	fetch_balances: bool = True,
	raise_on_error: bool = False,
) -> dict[str, Any]:
	client = client or EnableBankingClient()
	account_names = frappe.get_all(
		ACCOUNT_DOCTYPE,
		filters={"connection": connection.name},
		pluck="name",
	)
	refreshed = 0
	failed = 0
	for account_name in account_names:
		account = frappe.get_doc(ACCOUNT_DOCTYPE, account_name)
		result = refresh_account(
			account,
			connection=connection,
			client=client,
			fetch_balances=fetch_balances,
			raise_on_error=False,
		)
		refreshed += int(bool(result.get("refreshed")))
		failed += int(bool(result.get("failed")))

	now = now_datetime()
	if failed:
		_update_doc(
			connection,
			{
				"last_health_check_at": now,
				"last_error": _safe_error(
					Exception(_("{0} Enable Banking account refreshes failed.").format(failed))
				),
			},
		)
		if raise_on_error:
			frappe.throw(_("{0} Enable Banking account refreshes failed.").format(failed))
	else:
		_update_doc(
			connection,
			{
				"last_health_check_at": now,
				"last_successful_health_check_at": now,
				"last_error": None,
			},
		)
	return {"refreshed": refreshed, "failed": failed}


def refresh_account(
	account,
	*,
	connection=None,
	client: EnableBankingClient | None = None,
	fetch_balances: bool = True,
	raise_on_error: bool = False,
	record_sync_status: bool = True,
) -> dict[str, Any]:
	client = client or EnableBankingClient()
	connection = connection or frappe.get_doc(CONNECTION_DOCTYPE, account.connection)
	now = now_datetime()
	try:
		details = client.get_account_details(account.resource_uid)
		_update_account_details(account, details)
		balance_result = {"balances_refreshed": False}
		if fetch_balances and _is_balance_refresh_allowed(connection):
			balance_result = _refresh_balances(account, connection, client)
		if record_sync_status:
			_update_doc(
				account,
				{
					"sync_status": "Success",
					"last_sync_attempt_at": now,
					"last_sync_success_at": now,
					"last_error": None,
				},
			)
		return {"refreshed": True, "failed": False, **balance_result}
	except Exception as exc:
		if record_sync_status:
			_update_doc(
				account,
				{
					"sync_status": "Failed",
					"last_sync_attempt_at": now,
					"last_error": _safe_error(exc),
				},
			)
		log_operational_error("account refresh failed", exc)
		if raise_on_error:
			raise
		return {"refreshed": False, "failed": True, "error": _safe_error(exc)}


def normalize_balances(response: dict[str, Any] | list[dict[str, Any]]) -> list[dict[str, Any]]:
	if isinstance(response, dict):
		balances = response.get("balances") or []
	else:
		balances = response or []

	normalized = []
	for balance in balances:
		if not isinstance(balance, dict):
			continue
		amount = balance.get("balance_amount") or {}
		amount_value = _decimal_or_none(amount.get("amount"))
		as_of = _balance_as_of(balance)
		normalized.append(
			{
				"balance_type": balance.get("balance_type"),
				"amount": str(amount_value) if amount_value is not None else None,
				"currency": amount.get("currency"),
				"last_change_date_time": balance.get("last_change_date_time"),
				"reference_date": balance.get("reference_date"),
				"as_of": as_of.isoformat(sep=" ") if as_of else None,
			}
		)
	return normalized


def select_balance_snapshot(normalized_balances: list[dict[str, Any]]) -> dict[str, Any]:
	available = _select_by_precedence(normalized_balances, AVAILABLE_BALANCE_PRECEDENCE)
	booked = _select_by_precedence(normalized_balances, BOOKED_BALANCE_PRECEDENCE)
	selected = [balance for balance in (available, booked) if balance]
	selected_timestamps = [
		timestamp
		for balance in selected
		if (timestamp := _parse_normalized_as_of(balance.get("as_of"))) is not None
	]
	as_of = max(selected_timestamps, default=None)
	return {
		"available": available,
		"booked": booked,
		"available_amount": _decimal_or_none(available.get("amount")) if available else None,
		"booked_amount": _decimal_or_none(booked.get("amount")) if booked else None,
		"currency": _selected_currency(selected),
		"as_of": as_of,
	}


def selected_balances_match_currency(snapshot: dict[str, Any], expected_currency: str | None) -> bool:
	selected = [snapshot.get("available"), snapshot.get("booked")]
	currencies = {
		balance.get("currency")
		for balance in selected
		if isinstance(balance, dict) and balance.get("amount") is not None
	}
	return bool(currencies) and len(currencies) == 1 and next(iter(currencies)) == expected_currency


def _refresh_balances(account, connection, client: EnableBankingClient) -> dict[str, Any]:
	response = client.get_account_balances(account.resource_uid)
	normalized = normalize_balances(response)
	snapshot = select_balance_snapshot(normalized)
	_update_account_balance_fields(account, normalized, snapshot)
	_update_mapped_bank_account_balance_fields(account, connection, snapshot)
	return {"balances_refreshed": True, "balance_count": len(normalized)}


def _update_account_details(account, details: dict[str, Any]) -> None:
	if not isinstance(details, dict):
		frappe.throw(_("Enable Banking returned invalid account details."))

	values = {
		"resource_uid": details.get("uid") or account.resource_uid,
		"identification_hashes_json": json.dumps(
			details.get("identification_hashes") or _existing_identification_hashes(account),
			sort_keys=True,
			default=str,
		),
		"automatic_sync": account.automatic_sync,
		"masked_identifier": _masked_identifier(details) or account.masked_identifier,
		"account_name": details.get("name"),
		"account_description": details.get("details"),
		"product": details.get("product"),
		"currency": details.get("currency") or account.currency,
		"usage": details.get("usage"),
		"cash_account_type": details.get("cash_account_type"),
		"psu_status": details.get("psu_status"),
		"account_metadata_json": json.dumps(
			minimal_account_metadata(details),
			sort_keys=True,
			default=str,
		),
	}

	provider_identification_hash = details.get("identification_hash")
	if provider_identification_hash:
		details_identity_hash = _account_identity_hash(provider_identification_hash)
		if details_identity_hash != account.identification_hash:
			frappe.throw(_("Enable Banking returned details for a different account."))

	_update_doc(account, values)


def _update_account_balance_fields(
	account,
	normalized: list[dict[str, Any]],
	snapshot: dict[str, Any],
) -> None:
	values = {
		"latest_balances_json": json.dumps(normalized, sort_keys=True, default=str),
	}
	if selected_balances_match_currency(snapshot, account.currency):
		values.update(
			{
				"booked_balance": snapshot.get("booked_amount"),
				"available_balance": snapshot.get("available_amount"),
				"balance_currency": snapshot.get("currency"),
				"balance_as_of": snapshot.get("as_of"),
			}
		)
	else:
		if snapshot.get("booked") is None:
			values["booked_balance"] = None
		if snapshot.get("available") is None:
			values["available_balance"] = None
		if snapshot.get("booked") is None and snapshot.get("available") is None:
			values.update({"balance_currency": None, "balance_as_of": None})
	_update_doc(account, values)


def _update_mapped_bank_account_balance_fields(account, connection, snapshot: dict[str, Any]) -> None:
	if not account.bank_account:
		return

	bank_account = frappe.get_doc("Bank Account", account.bank_account)
	_validate_mapped_bank_account(account, connection, bank_account)
	gl_currency = frappe.get_cached_value("Account", bank_account.account, "account_currency")

	values: dict[str, Any] = {}
	if selected_balances_match_currency(snapshot, gl_currency):
		values.update(
			{
				"enable_banking_booked_balance": snapshot.get("booked_amount"),
				"enable_banking_available_balance": snapshot.get("available_amount"),
				"enable_banking_balance_currency": snapshot.get("currency"),
				"enable_banking_balance_as_of": snapshot.get("as_of"),
				"enable_banking_last_sync_at": now_datetime(),
			}
		)
	else:
		if snapshot.get("booked") is None:
			values["enable_banking_booked_balance"] = None
		if snapshot.get("available") is None:
			values["enable_banking_available_balance"] = None
		if snapshot.get("booked") is None and snapshot.get("available") is None:
			values.update(
				{
					"enable_banking_balance_currency": None,
					"enable_banking_balance_as_of": None,
					"enable_banking_last_sync_at": now_datetime(),
				}
			)

	if values:
		frappe.db.set_value(
			"Bank Account",
			bank_account.name,
			values,
			update_modified=False,
		)


def _is_balance_refresh_allowed(connection) -> bool:
	return connection.authorization_status == AUTHORIZED_STATUS


def _select_by_precedence(
	normalized_balances: list[dict[str, Any]],
	precedence: tuple[str, ...],
) -> dict[str, Any] | None:
	for balance_type in precedence:
		candidates = [
			balance
			for balance in normalized_balances
			if balance.get("balance_type") == balance_type
			and balance.get("amount") is not None
			and balance.get("currency")
		]
		if candidates:
			return max(
				candidates,
				key=lambda balance: _parse_normalized_as_of(balance.get("as_of")) or datetime.min,
			)
	return None


def _selected_currency(selected_balances: list[dict[str, Any]]) -> str | None:
	currencies = [
		balance.get("currency")
		for balance in selected_balances
		if balance and balance.get("amount") is not None
	]
	return currencies[0] if currencies and all(currency == currencies[0] for currency in currencies) else None


def _balance_as_of(balance: dict[str, Any]) -> datetime | None:
	return _provider_datetime(balance.get("last_change_date_time")) or _provider_datetime(
		balance.get("reference_date")
	)


def _provider_datetime(value: Any) -> datetime | None:
	if not value:
		return None
	if isinstance(value, datetime):
		parsed = value
	elif isinstance(value, date):
		parsed = datetime.combine(value, time.min)
	else:
		value = str(value)
		try:
			if len(value) == 10:
				parsed = datetime.combine(date.fromisoformat(value), time.min)
			else:
				parsed = get_datetime(value)
		except TypeError, ValueError:
			return None
	if parsed.tzinfo is not None:
		parsed = convert_utc_to_system_timezone(parsed.astimezone(UTC))
	return parsed.replace(tzinfo=None)


def _parse_normalized_as_of(value: Any) -> datetime | None:
	if not value:
		return None
	if isinstance(value, datetime):
		return value
	try:
		return get_datetime(value)
	except TypeError, ValueError:
		return None


def _decimal_or_none(value: Any) -> Decimal | None:
	if value is None or value == "":
		return None
	try:
		return Decimal(str(value))
	except InvalidOperation, ValueError:
		return None


def _validate_transaction_sync_account(account, connection) -> None:
	if connection.authorization_status != AUTHORIZED_STATUS:
		raise ValueError(_("The Enable Banking connection is not authorized."))
	if not account.bank_account:
		raise ValueError(_("Map the Enable Banking account before importing transactions."))
	bank_account = frappe.get_doc("Bank Account", account.bank_account)
	try:
		_validate_mapped_bank_account(account, connection, bank_account)
	except frappe.ValidationError as exc:
		raise ValueError(str(exc)) from exc


def _validate_mapped_bank_account(account, connection, bank_account) -> None:
	if account.connection != connection.name:
		frappe.throw(_("The Enable Banking account does not belong to this connection."))
	if account.company != connection.company:
		frappe.throw(_("The Enable Banking account company does not match the connection."))
	validate_bank_account_mapping(account, bank_account)
	validate_reciprocal_mapping(account, bank_account)


def _insert_bank_transaction(account, values: dict[str, Any], *, index: int) -> str:
	transaction_key = values["enable_banking_transaction_key"]
	if frappe.db.exists(
		"Bank Transaction",
		{"enable_banking_transaction_key": transaction_key},
	):
		return "duplicate"

	savepoint = f"enable_banking_transaction_{index}"
	frappe.db.savepoint(savepoint)
	try:
		doc = frappe.get_doc(
			{
				"doctype": "Bank Transaction",
				"bank_account": account.bank_account,
				"enable_banking_account": account.name,
				**values,
			}
		)
		doc.insert(ignore_permissions=True)
		doc.submit()
		return "created"
	except Exception:
		frappe.db.rollback(save_point=savepoint)
		if frappe.db.exists(
			"Bank Transaction",
			{"enable_banking_transaction_key": transaction_key},
		):
			return "duplicate"
		raise
	finally:
		frappe.db.release_savepoint(savepoint)


def _record_transaction_sync_failure(account, counts: dict[str, int], exc: Exception) -> None:
	log_operational_error("transaction import failed", exc)
	_update_doc(
		account,
		{
			"sync_status": "Failed",
			"last_fetched_count": counts["fetched"],
			"last_created_count": counts["created"],
			"last_duplicate_count": counts["duplicate"],
			"last_skipped_count": counts["skipped"],
			"last_failed_count": counts["failed"],
			"last_error": _safe_error(exc),
		},
	)


def _empty_transaction_counts() -> dict[str, int]:
	return {"fetched": 0, "created": 0, "duplicate": 0, "skipped": 0, "failed": 0}


def _transaction_date(transaction: dict[str, Any]) -> date:
	for fieldname in ("booking_date", "value_date", "transaction_date"):
		value = transaction.get(fieldname)
		if not value:
			continue
		try:
			return getdate(value)
		except TypeError, ValueError:
			continue
	raise ValueError(_("Transaction has no valid booking, value, or transaction date."))


def _counterparty(transaction: dict[str, Any], direction: str) -> dict[str, str | None]:
	prefix = "debtor" if direction == CREDIT_INDICATOR else "creditor"
	party = transaction.get(prefix) or {}
	account = transaction.get(f"{prefix}_account") or {}
	if not isinstance(party, dict):
		party = {}
	if not isinstance(account, dict):
		account = {}
	other = account.get("other") or {}
	if not isinstance(other, dict):
		other = {}
	iban = _clean_text(account.get("iban"))
	account_number = _clean_text(other.get("identification"))
	if not account_number and not iban:
		account_number = _clean_text(account.get("identification"))
	return {
		"name": _truncate(_clean_text(party.get("name")), 140),
		"iban": _truncate(iban, 140),
		"account_number": _truncate(account_number, 140),
	}


def _transaction_code(value: Any) -> dict[str, str | None]:
	if not isinstance(value, dict):
		value = {}
	description = _clean_text(value.get("description"))
	code = _clean_text(value.get("code"))
	sub_code = _clean_text(value.get("sub_code"))
	display_code = "/".join(part for part in (code, sub_code) if part)
	return {
		"description": description,
		"code": code,
		"sub_code": sub_code,
		"display_code": display_code or None,
	}


def _text_list(value: Any) -> list[str]:
	if isinstance(value, str):
		value = [value]
	if not isinstance(value, list):
		return []
	return [text for item in value if (text := _clean_text(item))]


def _required_text(value: Any, fieldname: str) -> str:
	text = _clean_text(value)
	if not text:
		raise ValueError(_("Transaction field {0} is required.").format(fieldname))
	return text


def _clean_text(value: Any) -> str | None:
	if value is None:
		return None
	text = str(value).strip()
	return text or None


def _truncate(value: str | None, length: int) -> str | None:
	return value[:length] if value else None


def _canonical_decimal(value: Decimal) -> str:
	canonical = format(value.normalize(), "f")
	return "0" if canonical in ("-0", "") else canonical


def _sha256_json(value: Any) -> str:
	payload = json.dumps(
		value,
		sort_keys=True,
		separators=(",", ":"),
		ensure_ascii=False,
		default=str,
	)
	return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _existing_identification_hashes(account) -> list[str]:
	try:
		values = json.loads(account.identification_hashes_json or "[]")
	except TypeError, ValueError:
		values = []
	return values if isinstance(values, list) else []


def _update_doc(doc, values: dict[str, Any]) -> None:
	doc.db_set(values)
	for key, value in values.items():
		setattr(doc, key, value)


def _safe_error(exc: Exception) -> str:
	return sanitized_error(exc)


def _require_manager() -> None:
	frappe.only_for(("System Manager", "Accounts Manager"))
