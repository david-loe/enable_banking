import frappe
from frappe import _
from frappe.model.document import Document

from enable_banking.integrity import require_internal_operation, validate_immutable_fields

INACTIVE_SESSION_STATUSES = frozenset({"CANCELLED", "CLOSED", "EXPIRED", "INVALID", "REVOKED"})
IMMUTABLE_FIELDS = {
	"authorization_status",
	"company",
	"parent_gl_account",
	"aspsp_name",
	"aspsp_country",
	"psu_type",
	"provider_session_id",
	"authorization",
	"valid_from",
	"valid_until",
	"last_health_check_at",
	"last_successful_health_check_at",
	"last_authorized_at",
	"closed_at",
	"last_sync_attempt_at",
	"last_sync_success_at",
	"sync_counts",
	"last_error",
}


class EnableBankingConnection(Document):
	def before_insert(self):
		require_internal_operation(_("created"))

	def validate(self):
		validate_immutable_fields(self, IMMUTABLE_FIELDS)
		if not self.provider_session_id:
			frappe.throw(_("Provider Session ID is required."))
		if len(self.aspsp_country or "") != 2:
			frappe.throw(_("ASPSP Country must be a two-letter ISO code."))
		account = frappe.db.get_value(
			"Account",
			self.parent_gl_account,
			["company", "is_group", "account_type", "disabled"],
			as_dict=True,
		)
		if (
			not account
			or account.company != self.company
			or not account.is_group
			or account.account_type != "Bank"
			or account.disabled
		):
			frappe.throw(
				_("Parent Bank GL Account must be an enabled Bank group for the connection company.")
			)
		if self.authorization:
			authorization = frappe.db.get_value(
				"Enable Banking Authorization",
				self.authorization,
				["company", "aspsp_name", "aspsp_country", "psu_type"],
				as_dict=True,
			)
			if not authorization:
				frappe.throw(_("Source Authorization does not exist."))
			if (
				authorization.company != self.company
				or authorization.aspsp_name != self.aspsp_name
				or authorization.aspsp_country != self.aspsp_country
				or authorization.psu_type != self.psu_type
			):
				frappe.throw(_("Source Authorization does not match the connection."))

	def on_trash(self):
		require_internal_operation(_("deleted"))
		if self.authorization_status not in INACTIVE_SESSION_STATUSES:
			frappe.throw(
				_(
					"Close the Enable Banking connection before deleting it so the provider session is not left active."
				)
			)
		self._delete_integration_accounts()
		self._unlink_authorizations()

	def _delete_integration_accounts(self) -> None:
		for account in frappe.get_all(
			"Enable Banking Account",
			filters={"connection": self.name},
			pluck="name",
		):
			frappe.delete_doc(
				"Enable Banking Account",
				account,
				ignore_permissions=True,
			)

	def _unlink_authorizations(self) -> None:
		frappe.db.set_value(
			"Enable Banking Authorization",
			{"connection": self.name},
			{"connection": None},
			update_modified=False,
		)
