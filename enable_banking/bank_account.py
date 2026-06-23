from __future__ import annotations

import frappe
from frappe import _

from enable_banking.integrity import (
	is_internal_operation,
	validate_bank_account_mapping,
	validate_reciprocal_mapping,
)


def validate_enable_banking_link(doc, method=None) -> None:
	if is_internal_operation():
		return
	previous = doc.get_doc_before_save()
	previous_link = previous.get("enable_banking_account") if previous else None
	current_link = doc.get("enable_banking_account")
	if current_link != previous_link:
		frappe.throw(
			_(
				"Enable Banking mappings cannot be changed directly on Bank Account. Use the Enable Banking account actions."
			),
			frappe.PermissionError,
		)
	if not current_link:
		return
	integration = frappe.get_doc("Enable Banking Account", current_link)
	validate_bank_account_mapping(integration, doc)
	validate_reciprocal_mapping(integration, doc)


def prevent_linked_bank_account_deletion(doc, method=None) -> None:
	if doc.get("enable_banking_account") and not is_internal_operation():
		frappe.throw(
			_("Unmap the Enable Banking account before deleting this Bank Account."),
			frappe.PermissionError,
		)
