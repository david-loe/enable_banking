import frappe
from frappe.model.document import Document


class EnableBankingConnection(Document):
	def on_trash(self):
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
