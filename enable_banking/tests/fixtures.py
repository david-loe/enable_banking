from __future__ import annotations

import frappe

TEST_COMPANY = "_Enable Banking Test Company"
TEST_COMPANY_ABBR = "_EBT"
TEST_PARENT_ACCOUNT = f"Bank Accounts - {TEST_COMPANY_ABBR}"


def ensure_accounting_fixtures() -> None:
	if not frappe.db.exists("Company", TEST_COMPANY):
		frappe.get_doc(
			{
				"doctype": "Company",
				"company_name": TEST_COMPANY,
				"abbr": TEST_COMPANY_ABBR,
				"default_currency": "EUR",
				"country": "Germany",
				"create_chart_of_accounts_based_on": "Standard Template",
				"chart_of_accounts": "Standard",
			}
		).insert(ignore_permissions=True)

	if not frappe.db.exists("Account", TEST_PARENT_ACCOUNT):
		raise RuntimeError(
			f"Enable Banking test setup could not create parent GL account {TEST_PARENT_ACCOUNT!r}."
		)
