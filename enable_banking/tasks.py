from __future__ import annotations

from datetime import timedelta
from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, get_datetime, now_datetime, validate_email_address

from enable_banking.client import EnableBankingClient
from enable_banking.configuration import SETTINGS_DOCTYPE
from enable_banking.integrity import internal_operation
from enable_banking.onboarding import (
	ACCOUNT_DOCTYPE,
	AUTHORIZATION_DOCTYPE,
	CONNECTION_DOCTYPE,
	_provider_datetime,
)
from enable_banking.operations import log_operational_error
from enable_banking.sync import (
	AUTHORIZED_STATUS,
	_safe_error,
	refresh_account,
	synchronize_account_transactions,
)

SYNC_INTERVAL_HOURS = {
	"Every Hour": 1,
	"Four Times a Day": 6,
	"Once a Day": 24,
}
SYNC_JOB_TIMEOUT = 30 * 60
SYNC_LOCK_TIMEOUT = 35 * 60
STALE_SYNC_AFTER = timedelta(minutes=40)
AUTHORIZATION_RETENTION_DAYS = 30
INACTIVE_SESSION_STATUSES = frozenset({"CANCELLED", "CLOSED", "EXPIRED", "INVALID", "REVOKED"})
EXPIRY_NOTIFICATION_FREQUENCIES = frozenset({"Daily", "Once"})


@frappe.whitelist()
def sync_all_now() -> dict[str, Any]:
	_require_manager()
	return enqueue_account_syncs(manual=True)


@frappe.whitelist()
def sync_connection_now(connection: str) -> dict[str, Any]:
	_require_manager()
	connection_doc = frappe.get_doc(CONNECTION_DOCTYPE, connection)
	connection_doc.check_permission("write")
	return enqueue_account_syncs(connection=connection_doc.name, manual=True)


@frappe.whitelist()
def sync_account_now(integration_account: str) -> dict[str, Any]:
	_require_manager()
	account = frappe.get_doc(ACCOUNT_DOCTYPE, integration_account)
	account.check_permission("write")
	if not account.bank_account:
		frappe.throw(_("Map the Enable Banking account before synchronizing transactions."))
	return {"queued": int(enqueue_account_job(account.name, manual=True)), "accounts": [account.name]}


def enqueue_scheduled_account_syncs() -> dict[str, Any]:
	recover_stale_account_sync_states()
	settings = frappe.get_single(SETTINGS_DOCTYPE)
	if not settings.enabled or not settings.automatic_sync:
		return {"queued": 0, "accounts": []}
	if not is_sync_interval_due(settings.sync_interval, now=now_datetime()):
		return {"queued": 0, "accounts": []}
	return enqueue_account_syncs(manual=False)


def is_sync_interval_due(sync_interval: str, *, now=None) -> bool:
	hours = SYNC_INTERVAL_HOURS.get(sync_interval)
	if not hours:
		return False
	current = get_datetime(now or now_datetime())
	return current.hour % hours == 0


def enqueue_account_syncs(
	*,
	connection: str | None = None,
	manual: bool,
) -> dict[str, Any]:
	settings = frappe.get_single(SETTINGS_DOCTYPE)
	if not settings.enabled:
		if manual:
			frappe.throw(_("Enable Banking is disabled."))
		return {"queued": 0, "accounts": []}

	filters: dict[str, Any] = {
		"bank_account": ["is", "set"],
	}
	if connection:
		filters["connection"] = connection
	if not manual:
		filters["automatic_sync"] = 1

	accounts = frappe.get_all(
		ACCOUNT_DOCTYPE,
		filters=filters,
		fields=["name", "connection"],
	)
	if not accounts:
		return {"queued": 0, "accounts": []}
	authorized_connections = {
		row.name
		for row in frappe.get_all(
			CONNECTION_DOCTYPE,
			filters={
				"name": ["in", list({row.connection for row in accounts})],
				"authorization_status": AUTHORIZED_STATUS,
				**({"automatic_sync": 1} if not manual else {}),
			},
			fields=["name"],
		)
	}
	eligible = [row.name for row in accounts if row.connection in authorized_connections]
	queued = sum(int(enqueue_account_job(account_name, manual=manual)) for account_name in eligible)
	return {"queued": queued, "accounts": eligible}


def enqueue_account_job(integration_account: str, *, manual: bool) -> bool:
	job = frappe.enqueue(
		"enable_banking.tasks.run_account_sync",
		queue="long",
		timeout=SYNC_JOB_TIMEOUT,
		job_id=f"enable-banking-sync::{frappe.local.site}::{integration_account}",
		deduplicate=True,
		integration_account=integration_account,
		manual=manual,
	)
	if job is not None:
		frappe.db.set_value(
			ACCOUNT_DOCTYPE,
			integration_account,
			{
				"sync_status": "Queued",
				"last_sync_attempt_at": now_datetime(),
				"last_error": None,
			},
			update_modified=False,
		)
	return job is not None


def run_account_sync(integration_account: str, manual: bool = False) -> dict[str, Any]:
	lock = frappe.cache().lock(
		f"enable-banking:account-sync:{frappe.local.site}:{integration_account}",
		timeout=SYNC_LOCK_TIMEOUT,
		blocking_timeout=0,
	)
	if not lock.acquire(blocking=False):
		return {"locked": True, "successful": False}
	try:
		account = frappe.get_doc(ACCOUNT_DOCTYPE, integration_account)
		connection = frappe.get_doc(CONNECTION_DOCTYPE, account.connection)
		_update_doc(
			account,
			{
				"sync_status": "In Progress",
				"last_sync_attempt_at": now_datetime(),
				"last_error": None,
			},
		)
		_update_doc(
			connection,
			{
				"last_sync_attempt_at": now_datetime(),
				"last_error": None,
			},
		)
		settings = frappe.get_single(SETTINGS_DOCTYPE)
		if not manual and (
			not settings.enabled
			or not settings.automatic_sync
			or not account.automatic_sync
			or not connection.automatic_sync
		):
			_update_doc(account, {"sync_status": "Disabled"})
			return {"disabled": True, "successful": False}

		client = EnableBankingClient()
		session = verify_connection_session(connection, client=client)
		if session.get("status") != AUTHORIZED_STATUS:
			if session.get("status") not in INACTIVE_SESSION_STATUSES:
				_update_doc(
					account,
					{
						"sync_status": "Failed",
						"last_error": _("The provider session is not authorized."),
					},
				)
			return {"reauthorization_required": True, "successful": False}

		try:
			refresh_account(
				account,
				connection=connection,
				client=client,
				raise_on_error=True,
				record_sync_status=False,
			)
			result = synchronize_account_transactions(
				account,
				connection=connection,
				client=client,
				settings=settings,
			)
			values = {
				"sync_counts": _format_counts(result),
				"last_error": getattr(account, "last_error", None),
			}
			if result.get("successful"):
				values["last_sync_success_at"] = now_datetime()
				values["last_error"] = None
			_update_doc(connection, values)
			return result
		except Exception as exc:
			log_operational_error("account synchronization failed", exc)
			_update_doc(
				account,
				{
					"sync_status": "Failed",
					"last_error": _safe_error(exc),
				},
			)
			_update_doc(connection, {"last_error": _safe_error(exc)})
			raise
	finally:
		if lock.owned():
			lock.release()


def verify_connection_session(connection, *, client: EnableBankingClient | None = None) -> dict[str, Any]:
	client = client or EnableBankingClient()
	checked_at = now_datetime()
	try:
		session = client.get_session(connection.provider_session_id)
		status = str(session.get("status") or "").upper()
		if not status:
			raise ValueError(_("Enable Banking returned a session without a status."))
		session["status"] = status

		values: dict[str, Any] = {
			"authorization_status": status,
			"last_health_check_at": checked_at,
			"last_error": None,
		}
		if status == AUTHORIZED_STATUS:
			values["last_successful_health_check_at"] = checked_at
			access = session.get("access") or {}
			if access.get("valid_until"):
				values["valid_until"] = _provider_datetime(access["valid_until"])
		else:
			values["automatic_sync"] = 0
		_update_doc(connection, values)

		if status in INACTIVE_SESSION_STATUSES:
			frappe.db.set_value(
				ACCOUNT_DOCTYPE,
				{"connection": connection.name},
				{"automatic_sync": 0, "sync_status": "Disabled"},
				update_modified=False,
			)
		return session
	except Exception as exc:
		log_operational_error("provider session health check failed", exc)
		_update_doc(
			connection,
			{
				"last_health_check_at": checked_at,
				"last_error": _safe_error(exc),
			},
		)
		raise


def recover_stale_account_sync_states(*, now=None) -> int:
	cutoff = get_datetime(now or now_datetime()) - STALE_SYNC_AFTER
	rows = frappe.get_all(
		ACCOUNT_DOCTYPE,
		filters={"sync_status": ["in", ["Queued", "In Progress"]]},
		or_filters=[
			["last_sync_attempt_at", "<", cutoff],
			["last_sync_attempt_at", "is", "not set"],
		],
		fields=["name", "sync_status"],
	)
	for row in rows:
		frappe.db.set_value(
			ACCOUNT_DOCTYPE,
			row.name,
			{
				"sync_status": "Failed",
				"last_error": _(
					"The previous {0} synchronization did not complete and can be retried."
				).format(row.sync_status.lower()),
			},
			update_modified=False,
		)
	return len(rows)


def purge_consumed_authorizations() -> int:
	cutoff = now_datetime() - timedelta(days=AUTHORIZATION_RETENTION_DAYS)
	names = frappe.get_all(
		AUTHORIZATION_DOCTYPE,
		filters={
			"status": ["in", ["Consumed", "Cancelled", "Failed", "Expired"]],
			"consumed_at": ["<", cutoff],
		},
		pluck="name",
	)
	for name in names:
		frappe.db.set_value(
			CONNECTION_DOCTYPE,
			{"authorization": name},
			{"authorization": None},
			update_modified=False,
		)
		with internal_operation():
			frappe.delete_doc(AUTHORIZATION_DOCTYPE, name, ignore_permissions=True)
	return len(names)


def send_connection_expiry_notifications(*, now=None) -> dict[str, int]:
	settings = frappe.get_single(SETTINGS_DOCTYPE)
	lead_days = max(cint(getattr(settings, "expiry_notification_lead_days", 7)) or 7, 1)
	frequency = getattr(settings, "expiry_notification_frequency", None) or "Daily"
	if frequency not in EXPIRY_NOTIFICATION_FREQUENCIES:
		frequency = "Daily"

	current = get_datetime(now or now_datetime())
	cutoff = current + timedelta(days=lead_days)
	connections = frappe.get_all(
		CONNECTION_DOCTYPE,
		filters=[
			["authorization_status", "=", AUTHORIZED_STATUS],
			["valid_until", ">", current],
			["valid_until", "<=", cutoff],
			["expiry_notification_recipients", "is", "set"],
		],
		fields=[
			"name",
			"company",
			"aspsp_name",
			"aspsp_country",
			"valid_until",
			"expiry_notification_recipients",
			"expiry_notification_last_valid_until",
		],
	)

	sent = 0
	skipped = 0
	failed = 0
	for connection in connections:
		if frequency == "Once" and _expiry_notification_was_sent_for_valid_until(connection):
			skipped += 1
			continue
		try:
			recipients = _expiry_notification_recipients(connection.expiry_notification_recipients)
			if not recipients:
				skipped += 1
				continue
			_send_connection_expiry_notification(connection, recipients)
			if frequency == "Once":
				frappe.db.set_value(
					CONNECTION_DOCTYPE,
					connection.name,
					{"expiry_notification_last_valid_until": connection.valid_until},
					update_modified=False,
				)
			sent += 1
		except Exception as exc:
			failed += 1
			log_operational_error("connection expiry notification failed", exc)

	return {"sent": sent, "skipped": skipped, "failed": failed}


def _update_doc(doc, values: dict[str, Any]) -> None:
	doc.db_set(values)
	for key, value in values.items():
		setattr(doc, key, value)


def _expiry_notification_was_sent_for_valid_until(connection) -> bool:
	last_valid_until = getattr(connection, "expiry_notification_last_valid_until", None)
	valid_until = getattr(connection, "valid_until", None)
	if not last_valid_until or not valid_until:
		return False
	return get_datetime(last_valid_until) == get_datetime(valid_until)


def _expiry_notification_recipients(recipients: str | None) -> list[str]:
	if not (recipients or "").strip():
		return []
	normalized = validate_email_address(recipients, throw=True)
	return [recipient.strip() for recipient in normalized.split(",") if recipient.strip()]


def _send_connection_expiry_notification(connection, recipients: list[str]) -> None:
	subject = _("Enable Banking authorization expires soon")
	valid_until = get_datetime(connection.valid_until)
	message = _(
		"""
		<p>The Enable Banking authorization for {aspsp} ({country}) expires on {valid_until}.</p>
		<p>Company: {company}<br>Connection: {connection}</p>
		<p>Please reauthorize the connection before expiry to keep synchronization active.</p>
		"""
	).format(
		aspsp=frappe.utils.escape_html(connection.aspsp_name or _("Unknown ASPSP")),
		country=frappe.utils.escape_html(connection.aspsp_country or ""),
		valid_until=frappe.utils.escape_html(str(valid_until)),
		company=frappe.utils.escape_html(connection.company or ""),
		connection=frappe.utils.escape_html(connection.name),
	)
	frappe.sendmail(
		recipients=recipients,
		subject=subject,
		message=message,
		reference_doctype=CONNECTION_DOCTYPE,
		reference_name=connection.name,
	)


def _format_counts(result: dict[str, Any]) -> str:
	return _("Fetched {0}, created {1}, duplicates {2}, skipped {3}, failed {4}").format(
		result.get("fetched", 0),
		result.get("created", 0),
		result.get("duplicate", 0),
		result.get("skipped", 0),
		result.get("failed", 0),
	)


def _require_manager() -> None:
	frappe.only_for(("System Manager", "Accounts Manager"))
