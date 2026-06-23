from __future__ import annotations

import hashlib
import json
import math
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

import frappe
from frappe import _
from frappe.utils import cint, convert_utc_to_system_timezone, get_datetime, get_url, now_datetime

from enable_banking.client import EnableBankingClient, sanitize_for_log
from enable_banking.configuration import SETTINGS_DOCTYPE
from enable_banking.integrity import (
	clear_bank_account_mapping,
	internal_operation,
	set_bank_account_mapping,
	validate_bank_account_mapping,
)
from enable_banking.operations import log_operational_error

AUTHORIZATION_DOCTYPE = "Enable Banking Authorization"
CONNECTION_DOCTYPE = "Enable Banking Connection"
ACCOUNT_DOCTYPE = "Enable Banking Account"
AUTHORIZATION_TTL = timedelta(minutes=15)
CALLBACK_METHOD = "enable_banking.onboarding.callback"
CALLBACK_PATH = f"/api/method/{CALLBACK_METHOD}"
SETTINGS_ROUTE = "/app/enable-banking-settings"
ACCOUNT_TYPE_MAP = {
	"CACC": "Current",
	"SVGS": "Savings",
	"CARD": "Credit Card",
	"LOAN": "Loan",
	"OTHR": "Other",
}
ALLOWED_PSU_TYPES = frozenset({"personal", "business"})


@frappe.whitelist()
def get_aspsps(country: str) -> list[dict[str, Any]]:
	_require_manager()
	country = _country_code(country)
	response = EnableBankingClient().get_aspsps(country=country)
	return [_public_aspsp(aspsp) for aspsp in response.get("aspsps") or []]


@frappe.whitelist()
def start_authorization(
	company: str,
	parent_gl_account: str,
	country: str,
	aspsp_name: str,
	psu_type: str,
	consent_days: int,
	automatic_sync: int = 0,
) -> dict[str, Any]:
	_require_manager()
	return _start_authorization(
		company=company,
		parent_gl_account=parent_gl_account,
		country=country,
		aspsp_name=aspsp_name,
		psu_type=psu_type,
		consent_days=consent_days,
		automatic_sync=automatic_sync,
	)


def _start_authorization(
	*,
	company: str,
	parent_gl_account: str,
	country: str,
	aspsp_name: str,
	psu_type: str,
	consent_days: int,
	automatic_sync: int = 0,
	reauthorization_connection: str | None = None,
) -> dict[str, Any]:
	settings = frappe.get_single(SETTINGS_DOCTYPE)
	if not cint(settings.enabled):
		frappe.throw(_("Enable Banking is disabled."))

	company = str(company).strip()
	parent_gl_account = str(parent_gl_account).strip()
	country = _country_code(country)
	aspsp_name = str(aspsp_name).strip()
	psu_type = str(psu_type).strip().lower()
	consent_days = cint(consent_days)
	if psu_type not in ALLOWED_PSU_TYPES:
		frappe.throw(_("PSU Type must be personal or business."))
	if consent_days < 1:
		frappe.throw(_("Consent Days must be at least one day."))

	_validate_parent_account(parent_gl_account, company)
	aspsp = _find_aspsp(country, aspsp_name, psu_type)
	maximum_seconds = cint(aspsp.get("maximum_consent_validity"))
	if maximum_seconds <= 0:
		frappe.throw(_("The selected ASPSP does not provide a valid maximum consent duration."))

	requested_seconds = consent_days * 86400
	validity_seconds = min(requested_seconds, maximum_seconds)
	valid_until = _utc_now() + timedelta(seconds=validity_seconds)
	state = secrets.token_urlsafe(32)
	state_hash = _state_hash(state)

	with internal_operation():
		authorization = frappe.get_doc(
			{
				"doctype": AUTHORIZATION_DOCTYPE,
				"status": "Pending",
				"initiating_user": frappe.session.user,
				"expires_at": now_datetime() + AUTHORIZATION_TTL,
				"state_hash": state_hash,
				"company": company,
				"parent_gl_account": parent_gl_account,
				"aspsp_name": aspsp_name,
				"aspsp_country": country,
				"psu_type": psu_type,
				"consent_days": max(1, math.ceil(validity_seconds / 86400)),
				"automatic_sync": cint(automatic_sync),
				"reauthorization_connection": reauthorization_connection,
			}
		).insert(ignore_permissions=True)

	payload = {
		"access": {
			"balances": True,
			"transactions": True,
			"valid_until": valid_until.isoformat(timespec="microseconds"),
		},
		"aspsp": {"name": aspsp_name, "country": country},
		"state": state,
		"redirect_url": settings.redirect_url,
		"psu_type": psu_type,
	}
	try:
		result = EnableBankingClient().start_authorization(payload)
		redirect_url = result.get("url")
		if not redirect_url:
			frappe.throw(_("Enable Banking did not return an authorization URL."))
		authorization.db_set("provider_authorization_id", result.get("authorization_id"))
	except Exception as exc:
		authorization.db_set(
			{
				"status": "Failed",
				"error_message": _safe_error(exc),
			}
		)
		raise

	return {
		"authorization": authorization.name,
		"redirect_url": redirect_url,
		"valid_until": valid_until.isoformat(timespec="seconds"),
	}


@frappe.whitelist(allow_guest=True, methods=["GET"])
def callback(
	state: str | None = None,
	code: str | None = None,
	error: str | None = None,
	error_description: str | None = None,
):
	authorization = _consume_authorization(state)
	if not authorization:
		return _redirect(SETTINGS_ROUTE)

	if authorization.status == "Cleanup Required":
		return _retry_callback_cleanup(authorization)

	if (
		authorization.status == "Session Created"
		and getattr(authorization, "connection", None)
		and getattr(authorization, "superseded_session_id", None)
	):
		connection = frappe.get_doc(CONNECTION_DOCTYPE, authorization.connection)
		_close_superseded_session(
			authorization,
			connection,
			authorization.superseded_session_id,
			EnableBankingClient(),
		)
		return _redirect(_connection_route(connection.name))

	if error:
		if error != "access_denied":
			log_operational_error(
				"authorization callback rejected",
				"Provider returned an authorization error.",
			)
		authorization.db_set(
			{
				"status": "Cancelled" if error == "access_denied" else "Failed",
				"error_message": _safe_callback_error(error, error_description),
			},
			update_modified=False,
		)
		frappe.db.commit()
		return _redirect(SETTINGS_ROUTE)

	if not code and not authorization.provider_session_id:
		log_operational_error(
			"authorization callback failed",
			"Provider callback did not contain an authorization code.",
		)
		authorization.db_set(
			{
				"status": "Failed",
				"error_message": _("Enable Banking callback did not contain an authorization code."),
			},
			update_modified=False,
		)
		frappe.db.commit()
		return _redirect(SETTINGS_ROUTE)

	client = EnableBankingClient()
	try:
		session = _get_or_create_callback_session(authorization, code, client)
	except Exception as exc:
		log_operational_error("authorization callback failed", exc)
		frappe.db.rollback()
		frappe.db.set_value(
			AUTHORIZATION_DOCTYPE,
			authorization.name,
			{
				"status": "Failed",
				"error_message": _safe_error(exc),
			},
			update_modified=False,
		)
		frappe.db.commit()
		return _redirect(SETTINGS_ROUTE)

	try:
		connection, superseded_session_id = _create_connection_and_accounts(
			authorization,
			session,
		)
		authorization.db_set(
			{
				"status": "Session Created" if superseded_session_id else "Consumed",
				"connection": connection.name,
				"superseded_session_id": superseded_session_id,
				"error_message": None,
			},
			update_modified=False,
		)
		frappe.db.commit()
	except Exception as exc:
		log_operational_error("authorization callback persistence failed", exc)
		frappe.db.rollback()
		cleanup_error = _close_failed_callback_session(
			authorization,
			session.get("session_id"),
			client,
		)
		frappe.db.set_value(
			AUTHORIZATION_DOCTYPE,
			authorization.name,
			{
				"status": "Cleanup Required" if cleanup_error else "Failed",
				"provider_session_id": session.get("session_id") if cleanup_error else None,
				"error_message": _callback_persistence_error(
					exc,
					cleanup_error,
					session.get("session_id"),
				),
			},
			update_modified=False,
		)
		frappe.db.commit()
		return _redirect(SETTINGS_ROUTE)

	if superseded_session_id:
		_close_superseded_session(
			authorization,
			connection,
			superseded_session_id,
			client,
		)
	return _redirect(_connection_route(connection.name))


@frappe.whitelist()
def map_existing_account(integration_account: str, bank_account: str) -> dict[str, str]:
	_require_manager()
	integration = frappe.get_doc(ACCOUNT_DOCTYPE, integration_account)
	integration.check_permission("write")
	set_bank_account_mapping(integration, frappe.get_doc("Bank Account", bank_account))
	return {"bank_account": bank_account}


@frappe.whitelist()
def create_erpnext_account(integration_account: str) -> dict[str, str]:
	_require_manager()
	integration = frappe.get_doc(ACCOUNT_DOCTYPE, integration_account)
	integration.check_permission("write")
	if integration.bank_account:
		frappe.throw(_("This Enable Banking account is already mapped."))

	connection = frappe.get_doc(CONNECTION_DOCTYPE, integration.connection)
	parent_account = connection.parent_gl_account
	_validate_parent_account(parent_account, connection.company)
	bank = _get_or_create_bank(connection.aspsp_country, connection.aspsp_name)
	account_name = _available_account_name(integration, bank.name, connection.company)

	gl_account = frappe.get_doc(
		{
			"doctype": "Account",
			"account_name": account_name,
			"parent_account": parent_account,
			"account_type": "Bank",
			"account_currency": integration.currency,
			"company": connection.company,
			"is_group": 0,
		}
	).insert()

	account_type = _ensure_bank_account_type(integration.cash_account_type)
	identifier = _primary_account_identifier(_metadata(integration))
	with internal_operation():
		bank_account = frappe.get_doc(
			{
				"doctype": "Bank Account",
				"account_name": account_name,
				"bank": bank.name,
				"account": gl_account.name,
				"account_type": account_type,
				"is_company_account": 1,
				"company": connection.company,
				"iban": identifier.get("iban"),
				"bank_account_no": identifier.get("account_number"),
				"mask": integration.masked_identifier,
			}
		).insert()
	set_bank_account_mapping(integration, bank_account)
	return {"bank_account": bank_account.name, "gl_account": gl_account.name, "bank": bank.name}


@frappe.whitelist()
def unmap_account(integration_account: str) -> dict[str, str | None]:
	_require_manager()
	integration = frappe.get_doc(ACCOUNT_DOCTYPE, integration_account)
	integration.check_permission("write")
	clear_bank_account_mapping(integration)
	return {"bank_account": None}


@frappe.whitelist()
def reauthorize(connection: str) -> dict[str, Any]:
	_require_manager()
	connection_doc = frappe.get_doc(CONNECTION_DOCTYPE, connection)
	connection_doc.check_permission("write")
	source = (
		frappe.get_doc(AUTHORIZATION_DOCTYPE, connection_doc.authorization)
		if connection_doc.authorization
		and frappe.db.exists(AUTHORIZATION_DOCTYPE, connection_doc.authorization)
		else None
	)
	validity_days = cint(source.consent_days) if source else 0
	if validity_days < 1:
		validity_days = cint(frappe.db.get_single_value(SETTINGS_DOCTYPE, "default_consent_days")) or 90
	return _start_authorization(
		company=connection_doc.company,
		parent_gl_account=connection_doc.parent_gl_account or (source.parent_gl_account if source else None),
		country=connection_doc.aspsp_country,
		aspsp_name=connection_doc.aspsp_name,
		psu_type=connection_doc.psu_type,
		consent_days=validity_days,
		automatic_sync=connection_doc.automatic_sync,
		reauthorization_connection=connection_doc.name,
	)


@frappe.whitelist()
def close_connection(connection: str) -> dict[str, str]:
	_require_manager()
	connection_doc = frappe.get_doc(CONNECTION_DOCTYPE, connection)
	connection_doc.check_permission("write")
	if connection_doc.authorization_status != "CLOSED":
		try:
			EnableBankingClient().delete_session(connection_doc.provider_session_id)
		except Exception as exc:
			log_operational_error("provider session closure failed", exc)
			message = _(
				"The provider session could not be closed. The connection remains active; retry after resolving the provider error. Details: {0}"
			).format(_safe_session_error(exc, connection_doc.provider_session_id))
			connection_doc.db_set("last_error", message, update_modified=False)
			frappe.throw(message)
		connection_doc.db_set(
			{
				"authorization_status": "CLOSED",
				"closed_at": now_datetime(),
				"automatic_sync": 0,
				"last_error": None,
			}
		)
		frappe.db.set_value(
			ACCOUNT_DOCTYPE,
			{"connection": connection_doc.name},
			{"automatic_sync": 0, "sync_status": "Disabled"},
			update_modified=False,
		)
	return {"status": "CLOSED"}


@frappe.whitelist()
def delete_connection(connection: str) -> dict[str, str]:
	_require_manager()
	connection_doc = frappe.get_doc(CONNECTION_DOCTYPE, connection)
	connection_doc.check_permission("write")
	if connection_doc.authorization_status != "CLOSED":
		frappe.throw(_("Close the provider session before deleting this connection."))
	with internal_operation():
		frappe.delete_doc(
			CONNECTION_DOCTYPE,
			connection_doc.name,
			ignore_permissions=True,
		)
	return {"deleted": connection_doc.name}


def get_callback_url() -> str:
	return get_url(CALLBACK_PATH)


def _consume_authorization(state: str | None):
	if not state:
		return None
	state_hash = _state_hash(state)
	rows = frappe.db.sql(
		f"""
		select name, status, expires_at
		from `tab{AUTHORIZATION_DOCTYPE}`
		where state_hash = %s
		for update
		""",
		state_hash,
		as_dict=True,
	)
	if not rows:
		frappe.db.rollback()
		return None

	row = rows[0]
	if row.status in {"Processing", "Session Created", "Cleanup Required"}:
		frappe.db.commit()
		return frappe.get_doc(AUTHORIZATION_DOCTYPE, row.name)
	if row.status != "Pending":
		frappe.db.rollback()
		return None
	if get_datetime(row.expires_at) <= now_datetime():
		frappe.db.set_value(
			AUTHORIZATION_DOCTYPE,
			row.name,
			{"status": "Expired", "consumed_at": now_datetime()},
			update_modified=False,
		)
		frappe.db.commit()
		return None

	frappe.db.set_value(
		AUTHORIZATION_DOCTYPE,
		row.name,
		{"status": "Processing", "consumed_at": now_datetime()},
		update_modified=False,
	)
	frappe.db.commit()
	return frappe.get_doc(AUTHORIZATION_DOCTYPE, row.name)


def _create_connection_and_accounts(authorization, session):
	session_id = session.get("session_id")
	if not session_id:
		frappe.throw(_("Enable Banking did not return a session ID."))
	access = session.get("access") or {}
	aspsp = session.get("aspsp") or {}
	now = now_datetime()
	values = {
		"authorization_status": "AUTHORIZED",
		"company": authorization.company,
		"parent_gl_account": authorization.parent_gl_account,
		"automatic_sync": authorization.automatic_sync,
		"aspsp_name": aspsp.get("name") or authorization.aspsp_name,
		"aspsp_country": aspsp.get("country") or authorization.aspsp_country,
		"psu_type": session.get("psu_type") or authorization.psu_type,
		"provider_session_id": session_id,
		"authorization": authorization.name,
		"valid_from": now,
		"valid_until": _provider_datetime(access.get("valid_until")),
		"last_health_check_at": now,
		"last_successful_health_check_at": now,
		"last_authorized_at": now,
		"closed_at": None,
		"last_error": None,
	}
	superseded_session_id = None
	if authorization.reauthorization_connection:
		connection = frappe.get_doc(
			CONNECTION_DOCTYPE,
			authorization.reauthorization_connection,
		)
		if connection.company != authorization.company:
			frappe.throw(_("The connection being reauthorized belongs to another company."))
		if (
			connection.aspsp_name != authorization.aspsp_name
			or connection.aspsp_country != authorization.aspsp_country
			or connection.psu_type != authorization.psu_type
		):
			frappe.throw(_("The connection being reauthorized does not match this authorization."))
		superseded_session_id = connection.provider_session_id
		connection.update(values)
		with internal_operation():
			connection.save(ignore_permissions=True)
	else:
		with internal_operation():
			connection = frappe.get_doc(
				{
					"doctype": CONNECTION_DOCTYPE,
					**values,
				}
			).insert(ignore_permissions=True)

	for account in session.get("accounts") or []:
		_upsert_discovered_account(connection, account)
	_refresh_connection_details_after_authorization(connection)
	return connection, superseded_session_id


def _get_or_create_callback_session(authorization, code, client: EnableBankingClient):
	if authorization.provider_session_id:
		session = client.get_session(authorization.provider_session_id)
		session.setdefault("session_id", authorization.provider_session_id)
		return session

	session = client.authorize_session(code)
	session_id = session.get("session_id")
	if not session_id:
		frappe.throw(_("Enable Banking did not return a session ID."))
	authorization.db_set(
		{
			"status": "Session Created",
			"provider_session_id": session_id,
			"error_message": None,
		},
		update_modified=False,
	)
	frappe.db.commit()
	authorization.status = "Session Created"
	authorization.provider_session_id = session_id
	return session


def _close_failed_callback_session(
	authorization,
	session_id: str | None,
	client: EnableBankingClient,
) -> str | None:
	if not session_id:
		return None
	try:
		client.delete_session(session_id)
		return None
	except Exception as exc:
		log_operational_error("provider session cleanup failed", exc)
		authorization.provider_session_id = session_id
		return _safe_session_error(exc, session_id)


def _close_superseded_session(
	authorization,
	connection,
	session_id: str,
	client: EnableBankingClient,
) -> None:
	try:
		client.delete_session(session_id)
	except Exception as exc:
		log_operational_error("superseded session cleanup failed", exc)
		message = _(
			"The new authorization is active, but the previous provider session could not be closed. Reload this callback URL to retry cleanup. Details: {0}"
		).format(_safe_session_error(exc, session_id))
		authorization.db_set(
			{
				"status": "Cleanup Required",
				"error_message": message,
			},
			update_modified=False,
		)
		connection.db_set("last_error", message, update_modified=False)
		frappe.db.commit()
		return

	authorization.db_set(
		{
			"status": "Consumed",
			"superseded_session_id": None,
			"error_message": None,
		},
		update_modified=False,
	)
	connection.db_set("last_error", None, update_modified=False)
	frappe.db.commit()


def _retry_callback_cleanup(authorization):
	client = EnableBankingClient()
	session_id = authorization.superseded_session_id or authorization.provider_session_id
	if not session_id:
		authorization.db_set(
			{
				"status": "Failed",
				"error_message": _("Provider cleanup was required, but no session was recorded."),
			},
			update_modified=False,
		)
		frappe.db.commit()
		return _redirect(SETTINGS_ROUTE)

	try:
		client.delete_session(session_id)
	except Exception as exc:
		log_operational_error("provider session cleanup retry failed", exc)
		authorization.db_set(
			"error_message",
			_(
				"The provider session still could not be closed. Retry cleanup after resolving the provider error. Details: {0}"
			).format(_safe_session_error(exc, session_id)),
			update_modified=False,
		)
		frappe.db.commit()
		return _redirect(
			_connection_route(authorization.connection) if authorization.connection else SETTINGS_ROUTE
		)

	if authorization.connection and authorization.superseded_session_id:
		authorization.db_set(
			{
				"status": "Consumed",
				"superseded_session_id": None,
				"error_message": None,
			},
			update_modified=False,
		)
		frappe.db.set_value(
			CONNECTION_DOCTYPE,
			authorization.connection,
			"last_error",
			None,
			update_modified=False,
		)
		route = _connection_route(authorization.connection)
	else:
		authorization.db_set(
			{
				"status": "Failed",
				"provider_session_id": None,
				"error_message": _("Local setup failed; the provider session was closed."),
			},
			update_modified=False,
		)
		route = SETTINGS_ROUTE
	frappe.db.commit()
	return _redirect(route)


def _refresh_connection_details_after_authorization(connection) -> None:
	try:
		from enable_banking.sync import refresh_connection

		refresh_connection(connection, fetch_balances=False, raise_on_error=False)
	except Exception as exc:
		log_operational_error("post-authorization account refresh failed", exc)
		connection.db_set("last_error", _safe_error(exc), update_modified=False)


def _upsert_discovered_account(connection, account):
	provider_identification_hash = account.get("identification_hash")
	if not provider_identification_hash:
		frappe.throw(_("Enable Banking returned an account without an identification hash."))
	resource_uid = account.get("uid")
	if not resource_uid:
		frappe.throw(_("Enable Banking returned an account without a resource UID."))
	identification_hash = _account_identity_hash(provider_identification_hash)

	values = {
		"connection": connection.name,
		"company": connection.company,
		"resource_uid": resource_uid,
		"identification_hash": identification_hash,
		"identification_hashes_json": json.dumps(
			account.get("identification_hashes") or [identification_hash],
			sort_keys=True,
		),
		"automatic_sync": connection.automatic_sync,
		"masked_identifier": _masked_identifier(account),
		"account_name": account.get("name"),
		"account_description": account.get("details"),
		"product": account.get("product"),
		"currency": account.get("currency"),
		"usage": account.get("usage"),
		"cash_account_type": account.get("cash_account_type"),
		"psu_status": account.get("psu_status"),
		"account_metadata_json": json.dumps(
			minimal_account_metadata(account),
			sort_keys=True,
			default=str,
		),
		"sync_status": "Never Synced",
		"last_error": None,
	}
	existing_name = frappe.db.get_value(ACCOUNT_DOCTYPE, {"identification_hash": identification_hash})
	if not existing_name and len(str(provider_identification_hash)) <= 140:
		existing_name = frappe.db.get_value(
			ACCOUNT_DOCTYPE,
			{"identification_hash": str(provider_identification_hash)},
		)
	if existing_name:
		existing = frappe.get_doc(ACCOUNT_DOCTYPE, existing_name)
		if existing.company != connection.company:
			frappe.throw(_("A discovered account is already linked to another company."))
		if existing.connection != connection.name:
			frappe.throw(_("A discovered account is already linked to another connection."))
		existing.update(values)
		with internal_operation():
			existing.save(ignore_permissions=True)
		return existing
	with internal_operation():
		return frappe.get_doc({"doctype": ACCOUNT_DOCTYPE, **values}).insert(ignore_permissions=True)


def _validate_bank_account_mapping(integration, bank_account_name):
	if integration.bank_account and integration.bank_account != bank_account_name:
		frappe.throw(_("This Enable Banking account is already mapped."))
	bank_account = frappe.get_doc("Bank Account", bank_account_name)
	validate_bank_account_mapping(integration, bank_account)


def _link_bank_account(integration, bank_account):
	set_bank_account_mapping(integration, bank_account)


def _validate_parent_account(parent_account: str, company: str):
	account = frappe.db.get_value(
		"Account",
		parent_account,
		["company", "is_group", "account_type", "disabled"],
		as_dict=True,
	)
	if not account:
		frappe.throw(_("Parent GL Account does not exist."))
	if (
		account.company != company
		or not account.is_group
		or account.account_type != "Bank"
		or account.disabled
	):
		frappe.throw(
			_("Parent GL Account must be an enabled Bank-type group account belonging to {0}.").format(
				company
			)
		)


def _find_aspsp(country: str, name: str, psu_type: str):
	response = EnableBankingClient().get_aspsps(country=country)
	for aspsp in response.get("aspsps") or []:
		if aspsp.get("name") == name and aspsp.get("country") == country:
			supported_types = {
				method.get("psu_type") for method in aspsp.get("auth_methods") or [] if method.get("psu_type")
			}
			if supported_types and psu_type not in supported_types:
				frappe.throw(_("The selected ASPSP does not support the requested PSU type."))
			return aspsp
	frappe.throw(_("The selected ASPSP is not available."))


def _public_aspsp(aspsp):
	return {
		"name": aspsp.get("name"),
		"country": aspsp.get("country"),
		"logo": aspsp.get("logo"),
		"maximum_consent_validity": cint(aspsp.get("maximum_consent_validity")),
		"psu_types": sorted(
			{method.get("psu_type") for method in aspsp.get("auth_methods") or [] if method.get("psu_type")}
		),
	}


def _get_or_create_bank(country: str, aspsp_name: str):
	key = f"{country}::{aspsp_name}"
	if bank_name := frappe.db.get_value("Bank", {"enable_banking_aspsp_key": key}):
		return frappe.get_doc("Bank", bank_name)

	base_name = f"Enable Banking - {aspsp_name} ({country})"
	bank_name = base_name
	suffix = 2
	while frappe.db.exists("Bank", bank_name):
		bank_name = f"{base_name} {suffix}"
		suffix += 1
	return frappe.get_doc(
		{
			"doctype": "Bank",
			"bank_name": bank_name,
			"enable_banking_aspsp_key": key,
		}
	).insert()


def _available_account_name(integration, bank_name: str, company: str) -> str:
	from erpnext.accounts.utils import get_autoname_with_number

	base = str(integration.account_description or integration.account_name or _("Bank Account")).strip() or _(
		"Bank Account"
	)
	if integration.masked_identifier:
		base = f"{base} {integration.masked_identifier}"
	candidate = base[:120].strip()
	suffix = 2
	while True:
		gl_name = get_autoname_with_number(None, candidate, company)
		bank_account_name = f"{candidate} - {bank_name}"
		if not frappe.db.exists("Account", gl_name) and not frappe.db.exists(
			"Bank Account", bank_account_name
		):
			return candidate
		candidate = f"{base[:110].strip()} {suffix}"
		suffix += 1


def _ensure_bank_account_type(cash_account_type: str | None) -> str:
	account_type = ACCOUNT_TYPE_MAP.get(cash_account_type or "", "Other")
	if not frappe.db.exists("Bank Account Type", account_type):
		frappe.get_doc({"doctype": "Bank Account Type", "account_type": account_type}).insert()
	return account_type


def _primary_account_identifier(metadata: dict[str, Any]) -> dict[str, str | None]:
	account_id = metadata.get("account_id") or {}
	if account_id.get("iban"):
		return {"iban": account_id["iban"], "account_number": None}
	other = account_id.get("other") or {}
	if other.get("identification"):
		return {"iban": None, "account_number": str(other["identification"])[:30]}
	for identifier in metadata.get("all_account_ids") or []:
		if identifier.get("scheme_name") == "IBAN" and identifier.get("identification"):
			return {"iban": identifier["identification"], "account_number": None}
		if identifier.get("identification"):
			return {"iban": None, "account_number": str(identifier["identification"])[:30]}
	return {"iban": None, "account_number": None}


def minimal_account_metadata(account: dict[str, Any]) -> dict[str, Any]:
	"""Retain only identifiers needed to create or display an ERPNext Bank Account."""
	if not isinstance(account, dict):
		return {}

	metadata: dict[str, Any] = {}
	account_id = _minimal_account_identifier(account.get("account_id"))
	if account_id:
		metadata["account_id"] = account_id

	all_account_ids = [
		identifier
		for item in account.get("all_account_ids") or []
		if (identifier := _minimal_account_identifier(item, include_scheme=True))
	]
	if all_account_ids:
		metadata["all_account_ids"] = all_account_ids
	return metadata


def _minimal_account_identifier(
	identifier: Any,
	*,
	include_scheme: bool = False,
) -> dict[str, Any]:
	if not isinstance(identifier, dict):
		return {}
	result = {}
	for fieldname in ("iban", "identification"):
		if value := identifier.get(fieldname):
			result[fieldname] = str(value)
	other = identifier.get("other")
	if isinstance(other, dict) and other.get("identification"):
		result["other"] = {"identification": str(other["identification"])}
	if include_scheme and identifier.get("scheme_name"):
		result["scheme_name"] = str(identifier["scheme_name"])
	return result


def _masked_identifier(account: dict[str, Any]) -> str | None:
	identifier = _primary_account_identifier(account)
	value = identifier.get("iban") or identifier.get("account_number")
	if not value:
		return None
	value = str(value).replace(" ", "")
	return f"••••{value[-4:]}" if len(value) > 4 else f"••••{value}"


def _metadata(integration) -> dict[str, Any]:
	try:
		return json.loads(integration.account_metadata_json or "{}")
	except TypeError, ValueError:
		return {}


def _country_code(country: str) -> str:
	country = str(country or "").strip()
	if len(country) == 2 and country.isalpha():
		return country.upper()
	code = frappe.db.get_value("Country", country, "code")
	if not code or len(code) != 2:
		frappe.throw(_("Country must be a two-letter ISO code."))
	return str(code).upper()


def _state_hash(state: str) -> str:
	return hashlib.sha256(str(state).encode()).hexdigest()


def _account_identity_hash(value: Any) -> str:
	return hashlib.sha256(str(value).encode()).hexdigest()


def _provider_datetime(value: Any) -> datetime | None:
	"""Convert an ISO-8601 provider timestamp into a naive Frappe system-time datetime."""
	if not value:
		return None
	parsed = get_datetime(value)
	if parsed.tzinfo is not None:
		parsed = convert_utc_to_system_timezone(parsed.astimezone(UTC))
	return parsed.replace(tzinfo=None)


def _safe_callback_error(error: str, description: str | None) -> str:
	error = str(sanitize_for_log(error))[:100]
	description = str(sanitize_for_log(description or ""))[:300]
	return f"{error}: {description}".rstrip(": ")


def _safe_error(exc: Exception) -> str:
	return str(sanitize_for_log(str(exc)))[:500]


def _callback_persistence_error(
	exc: Exception,
	cleanup_error: str | None,
	session_id: str | None,
) -> str:
	message = _("Local connection setup failed: {0}").format(_safe_session_error(exc, session_id))
	if cleanup_error:
		message += _(
			" The new provider session could not be closed; reload the callback URL to retry cleanup. Details: {0}"
		).format(cleanup_error)
	return message[:500]


def _safe_session_error(exc: Exception, *session_ids: str | None) -> str:
	message = _safe_error(exc)
	for session_id in session_ids:
		if session_id:
			message = message.replace(str(session_id), "[REDACTED]")
	return message


def _utc_now() -> datetime:
	return datetime.now(UTC)


def _connection_route(name: str) -> str:
	return f"/app/enable-banking-connection/{quote(name, safe='')}"


def _redirect(location: str):
	frappe.local.response["type"] = "redirect"
	frappe.local.response["location"] = location
	return None


def _require_manager():
	frappe.only_for(("System Manager", "Accounts Manager"))
