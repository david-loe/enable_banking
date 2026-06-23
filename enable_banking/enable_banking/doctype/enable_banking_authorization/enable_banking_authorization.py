from __future__ import annotations

import re

import frappe
from frappe import _
from frappe.model.document import Document

from enable_banking.integrity import require_internal_operation, validate_immutable_fields

SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
IMMUTABLE_FIELDS = {
	"status",
	"initiating_user",
	"expires_at",
	"consumed_at",
	"state_hash",
	"provider_authorization_id",
	"provider_session_id",
	"company",
	"parent_gl_account",
	"aspsp_name",
	"aspsp_country",
	"psu_type",
	"consent_days",
	"automatic_sync",
	"reauthorization_connection",
	"connection",
	"superseded_session_id",
	"error_message",
}


class EnableBankingAuthorization(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		aspsp_country: DF.Data
		aspsp_name: DF.Data
		automatic_sync: DF.Check
		company: DF.Link
		connection: DF.Link | None
		consent_days: DF.Int
		consumed_at: DF.Datetime | None
		error_message: DF.SmallText | None
		expires_at: DF.Datetime
		initiating_user: DF.Link
		parent_gl_account: DF.Link
		provider_authorization_id: DF.Data | None
		provider_session_id: DF.Data | None
		psu_type: DF.Literal["personal", "business"]
		reauthorization_connection: DF.Link | None
		state_hash: DF.Data
		status: DF.Literal[
			"Pending",
			"Processing",
			"Session Created",
			"Consumed",
			"Cleanup Required",
			"Cancelled",
			"Failed",
			"Expired",
		]
		superseded_session_id: DF.Data | None
	# end: auto-generated types

	def before_insert(self):
		require_internal_operation(_("created"))

	def validate(self):
		validate_immutable_fields(self, IMMUTABLE_FIELDS)
		if self.state_hash and not SHA256_PATTERN.fullmatch(self.state_hash):
			frappe.throw(_("State Hash must be a lowercase SHA-256 hexadecimal digest."))
		if self.consent_days is not None and self.consent_days < 1:
			frappe.throw(_("Consent Days must be at least one day."))
		if len(self.aspsp_country or "") != 2:
			frappe.throw(_("ASPSP Country must be a two-letter ISO code."))
		if self.reauthorization_connection:
			connection = frappe.db.get_value(
				"Enable Banking Connection",
				self.reauthorization_connection,
				["company", "aspsp_name", "aspsp_country", "psu_type"],
				as_dict=True,
			)
			if not connection:
				frappe.throw(_("The connection being reauthorized does not exist."))
			if (
				connection.company != self.company
				or connection.aspsp_name != self.aspsp_name
				or connection.aspsp_country != self.aspsp_country
				or connection.psu_type != self.psu_type
			):
				frappe.throw(_("The connection being reauthorized does not match the authorization."))

	def on_trash(self):
		require_internal_operation(_("deleted"))
