from __future__ import annotations

import re

import frappe
from frappe import _
from frappe.model.document import Document

SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class EnableBankingAuthorization(Document):
	def validate(self):
		if self.state_hash and not SHA256_PATTERN.fullmatch(self.state_hash):
			frappe.throw(_("State Hash must be a lowercase SHA-256 hexadecimal digest."))
		if self.consent_days is not None and self.consent_days < 1:
			frappe.throw(_("Consent Days must be at least one day."))

