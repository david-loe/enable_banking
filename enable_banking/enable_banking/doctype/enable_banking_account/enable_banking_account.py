import frappe
from frappe.model.document import Document


class EnableBankingAccount(Document):
	def on_trash(self):
		self._unlink_bank_accounts()
		self._unlink_bank_transactions()

	def _unlink_bank_accounts(self) -> None:
		bank_accounts = set(
			frappe.get_all(
				"Bank Account",
				filters={"enable_banking_account": self.name},
				pluck="name",
			)
		)
		if self.bank_account and frappe.db.exists("Bank Account", self.bank_account):
			bank_accounts.add(self.bank_account)

		for bank_account in bank_accounts:
			current_link = frappe.db.get_value("Bank Account", bank_account, "enable_banking_account")
			if current_link and current_link != self.name:
				continue

			values = {
				"enable_banking_booked_balance": 0,
				"enable_banking_available_balance": 0,
				"enable_banking_balance_currency": None,
				"enable_banking_balance_as_of": None,
				"enable_banking_last_sync_at": None,
			}
			if current_link == self.name:
				values["enable_banking_account"] = None
			frappe.db.set_value("Bank Account", bank_account, values, update_modified=False)

	def _unlink_bank_transactions(self) -> None:
		frappe.db.set_value(
			"Bank Transaction",
			{"enable_banking_account": self.name},
			{"enable_banking_account": None},
			update_modified=False,
		)
