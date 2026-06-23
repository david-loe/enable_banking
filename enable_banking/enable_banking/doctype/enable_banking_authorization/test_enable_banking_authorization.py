from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase

IGNORE_TEST_RECORD_DEPENDENCIES = [
	"User",
	"Company",
	"Account",
	"Enable Banking Connection",
]


class TestEnableBankingAuthorization(IntegrationTestCase):
	def test_direct_creation_is_rejected_even_when_permissions_are_ignored(self):
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc({"doctype": "Enable Banking Authorization"}).insert(ignore_permissions=True)
