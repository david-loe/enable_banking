import re

import frappe
from frappe import _
from frappe.model.document import Document

from enable_banking.integrity import (
	require_internal_operation,
	validate_bank_account_mapping,
	validate_immutable_fields,
	validate_reciprocal_mapping,
)

IMMUTABLE_FIELDS = {
	"connection",
	"company",
	"resource_uid",
	"identification_hash",
	"identification_hashes_json",
	"bank_account",
	"masked_identifier",
	"account_name",
	"account_description",
	"product",
	"currency",
	"usage",
	"cash_account_type",
	"psu_status",
	"account_metadata_json",
	"booked_balance",
	"available_balance",
	"balance_currency",
	"balance_as_of",
	"latest_balances_json",
	"sync_status",
	"last_sync_attempt_at",
	"last_sync_success_at",
	"last_successful_end_date",
	"last_fetched_count",
	"last_created_count",
	"last_duplicate_count",
	"last_skipped_count",
	"last_failed_count",
	"last_error",
}
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class EnableBankingAccount(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		account_description: DF.SmallText | None
		account_metadata_json: DF.Code | None
		account_name: DF.Data | None
		automatic_sync: DF.Check
		available_balance: DF.Currency
		balance_as_of: DF.Datetime | None
		balance_currency: DF.Link | None
		bank_account: DF.Link | None
		booked_balance: DF.Currency
		cash_account_type: DF.Data | None
		company: DF.Link
		connection: DF.Link
		currency: DF.Link | None
		identification_hash: DF.Data
		identification_hashes_json: DF.Code | None
		last_created_count: DF.Int
		last_duplicate_count: DF.Int
		last_error: DF.SmallText | None
		last_failed_count: DF.Int
		last_fetched_count: DF.Int
		last_skipped_count: DF.Int
		last_successful_end_date: DF.Date | None
		last_sync_attempt_at: DF.Datetime | None
		last_sync_success_at: DF.Datetime | None
		latest_balances_json: DF.Code | None
		masked_identifier: DF.Data | None
		product: DF.Data | None
		psu_status: DF.Data | None
		resource_uid: DF.Data
		sync_status: DF.Literal["Never Synced", "Queued", "In Progress", "Success", "Failed", "Disabled"]
		usage: DF.Data | None
	# end: auto-generated types

	def before_insert(self):
		require_internal_operation(_("created"))

	def validate(self):
		validate_immutable_fields(self, IMMUTABLE_FIELDS)
		connection = frappe.db.get_value(
			"Enable Banking Connection",
			self.connection,
			["company", "authorization_status"],
			as_dict=True,
		)
		if not connection:
			frappe.throw(_("Enable Banking Connection does not exist."))
		if connection.company != self.company:
			frappe.throw(_("Enable Banking Account company must match its connection."))
		if not self.resource_uid or not self.identification_hash:
			frappe.throw(_("Provider resource UID and identification hash are required."))
		if not SHA256_PATTERN.fullmatch(self.identification_hash or ""):
			frappe.throw(_("Identification Hash must be a SHA-256 hexadecimal digest."))
		if self.bank_account:
			bank_account = frappe.get_doc("Bank Account", self.bank_account)
			validate_bank_account_mapping(self, bank_account)
			validate_reciprocal_mapping(self, bank_account)

	def on_trash(self):
		require_internal_operation(_("deleted"))
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
