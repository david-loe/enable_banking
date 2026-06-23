from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

import frappe
from frappe import _

_internal_operation_depth: ContextVar[int] = ContextVar(
	"enable_banking_internal_operation_depth",
	default=0,
)


@contextmanager
def internal_operation():
	token = _internal_operation_depth.set(_internal_operation_depth.get() + 1)
	try:
		yield
	finally:
		_internal_operation_depth.reset(token)


def is_internal_operation() -> bool:
	return _internal_operation_depth.get() > 0


def require_internal_operation(action: str) -> None:
	if not is_internal_operation():
		frappe.throw(
			_(
				"Enable Banking records cannot be {0} directly. Use the Enable Banking lifecycle actions."
			).format(action),
			frappe.PermissionError,
		)


def validate_immutable_fields(doc, fieldnames: set[str]) -> None:
	if doc.is_new() or is_internal_operation():
		return
	previous = doc.get_doc_before_save()
	if not previous:
		return
	changed = [
		doc.meta.get_label(fieldname) or fieldname
		for fieldname in sorted(fieldnames)
		if doc.get(fieldname) != previous.get(fieldname)
	]
	if changed:
		frappe.throw(
			_("These Enable Banking fields are managed internally and cannot be changed: {0}.").format(
				", ".join(changed)
			),
			frappe.PermissionError,
		)


def validate_bank_account_mapping(integration, bank_account: Any) -> None:
	if not bank_account.is_company_account or bank_account.company != integration.company:
		frappe.throw(_("The Bank Account must be a company account for {0}.").format(integration.company))
	if bank_account.disabled:
		frappe.throw(_("The Bank Account is disabled."))
	if bank_account.integration_id:
		frappe.throw(_("The Bank Account is already linked to another banking integration."))
	if not bank_account.account:
		frappe.throw(_("The Bank Account must be linked to a company GL Account."))

	gl_account = frappe.db.get_value(
		"Account",
		bank_account.account,
		["company", "account_currency", "account_type", "is_group", "disabled"],
		as_dict=True,
	)
	if not gl_account:
		frappe.throw(_("The Bank Account company GL Account does not exist."))
	if (
		gl_account.company != integration.company
		or gl_account.account_type != "Bank"
		or gl_account.is_group
		or gl_account.disabled
	):
		frappe.throw(
			_("The Bank Account must use an enabled, non-group Bank GL Account for {0}.").format(
				integration.company
			)
		)
	if gl_account.account_currency != integration.currency:
		frappe.throw(
			_("The Bank Account currency {0} does not match the provider currency {1}.").format(
				gl_account.account_currency,
				integration.currency,
			)
		)

	linked_integration = bank_account.get("enable_banking_account")
	if linked_integration and linked_integration != integration.name:
		frappe.throw(_("The Bank Account is linked to another Enable Banking account."))
	other = frappe.db.get_value(
		"Enable Banking Account",
		{"bank_account": bank_account.name, "name": ["!=", integration.name]},
	)
	if other:
		frappe.throw(_("The Bank Account is linked to another Enable Banking account."))


def validate_reciprocal_mapping(integration, bank_account: Any) -> None:
	if integration.bank_account != bank_account.name:
		frappe.throw(_("The Enable Banking account does not point to this Bank Account."))
	if bank_account.get("enable_banking_account") != integration.name:
		frappe.throw(_("The Bank Account does not point to this Enable Banking account."))


def set_bank_account_mapping(integration, bank_account: Any) -> None:
	if integration.bank_account and integration.bank_account != bank_account.name:
		frappe.throw(_("This Enable Banking account is already mapped."))
	validate_bank_account_mapping(integration, bank_account)
	with internal_operation():
		frappe.db.set_value(
			"Bank Account",
			bank_account.name,
			"enable_banking_account",
			integration.name,
			update_modified=False,
		)
		frappe.db.set_value(
			"Enable Banking Account",
			integration.name,
			"bank_account",
			bank_account.name,
			update_modified=False,
		)
	integration.bank_account = bank_account.name
	bank_account.enable_banking_account = integration.name


def clear_bank_account_mapping(integration) -> None:
	if not integration.bank_account:
		return
	bank_account_name = integration.bank_account
	current_link = frappe.db.get_value(
		"Bank Account",
		bank_account_name,
		"enable_banking_account",
	)
	if current_link and current_link != integration.name:
		frappe.throw(_("The Bank Account is linked to another Enable Banking account."))
	with internal_operation():
		frappe.db.set_value(
			"Bank Account",
			bank_account_name,
			{
				"enable_banking_account": None,
				"enable_banking_booked_balance": 0,
				"enable_banking_available_balance": 0,
				"enable_banking_balance_currency": None,
				"enable_banking_balance_as_of": None,
				"enable_banking_last_sync_at": None,
			},
			update_modified=False,
		)
		frappe.db.set_value(
			"Enable Banking Account",
			integration.name,
			"bank_account",
			None,
			update_modified=False,
		)
	integration.bank_account = None
