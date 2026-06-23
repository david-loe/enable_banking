from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils.password import remove_encrypted_password, set_encrypted_password

from enable_banking.configuration import SETTINGS_DOCTYPE, validate_private_key


class EnableBankingSettings(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		app_id: DF.Data
		automatic_sync: DF.Check
		callback_url: DF.Data | None
		default_consent_days: DF.Int
		enabled: DF.Check
		expiry_notification_frequency: DF.Literal["Daily", "Once"]
		expiry_notification_lead_days: DF.Int
		initial_import_days: DF.Int
		max_transaction_pages: DF.Int
		max_transactions_per_sync: DF.Int
		overlap_days: DF.Int
		private_key: DF.Password | None
		private_key_configured: DF.Check
		redirect_url: DF.Data
		sync_interval: DF.Literal["Every Hour", "Four Times a Day", "Once a Day"]
	# end: auto-generated types

	def __setup__(self):
		self.flags.ignore_save_passwords = ["private_key"]

	def onload(self):
		from enable_banking.onboarding import get_callback_url

		self.private_key_configured = bool(self.get_password("private_key", raise_exception=False))
		self.callback_url = get_callback_url()

	def validate(self):
		if self.sync_interval not in ("Every Hour", "Four Times a Day", "Once a Day"):
			frappe.throw(_("Select a valid Synchronization Interval."))
		if self.expiry_notification_frequency not in ("Daily", "Once"):
			frappe.throw(_("Select a valid Expiry Notification Frequency."))
		for fieldname in (
			"initial_import_days",
			"default_consent_days",
			"max_transaction_pages",
			"max_transactions_per_sync",
			"expiry_notification_lead_days",
		):
			if self.get(fieldname) is not None and self.get(fieldname) < 1:
				frappe.throw(_("{0} must be at least one day.").format(self.meta.get_label(fieldname)))
		if self.overlap_days is not None and self.overlap_days < 0:
			frappe.throw(_("Incremental Import Overlap Days cannot be negative."))

	@frappe.whitelist()
	def set_private_key(self, private_key: str):
		frappe.only_for("System Manager")
		private_key = validate_private_key(private_key)
		set_encrypted_password(SETTINGS_DOCTYPE, SETTINGS_DOCTYPE, private_key, "private_key")
		frappe.db.set_single_value(
			SETTINGS_DOCTYPE,
			"private_key_configured",
			1,
		)
		return {"configured": True}

	@frappe.whitelist()
	def clear_private_key(self):
		frappe.only_for("System Manager")
		remove_encrypted_password(SETTINGS_DOCTYPE, SETTINGS_DOCTYPE, "private_key")
		frappe.db.set_single_value(SETTINGS_DOCTYPE, "private_key_configured", 0)
		return {"configured": False}

	@frappe.whitelist()
	def test_configuration(self):
		from enable_banking.api import get_configuration_status

		frappe.only_for("System Manager")
		status = get_configuration_status()
		frappe.msgprint(
			_("Connected to {0} ({1}).").format(
				frappe.bold(status.get("name") or _("Enable Banking")),
				frappe.bold(status.get("environment") or _("Unknown environment")),
			),
			title=_("Configuration Valid"),
			indicator="green",
		)
		return status
