from __future__ import annotations

from typing import Any

import frappe

from enable_banking.client import EnableBankingClient


@frappe.whitelist()
def test_configuration() -> dict[str, Any]:
	frappe.only_for("System Manager")
	return get_configuration_status()


def get_configuration_status() -> dict[str, Any]:
	application = EnableBankingClient().get_application()
	if not application.get("active"):
		frappe.throw("The Enable Banking application is not active.")

	services = application.get("services") or []
	if "AIS" not in services:
		frappe.throw("The Enable Banking application does not have AIS access.")

	return {
		"active": True,
		"environment": application.get("environment"),
		"name": application.get("name"),
		"services": services,
	}
