from unittest import TestCase
from unittest.mock import patch

from enable_banking.operations import log_operational_error


class TestOperationalLogging(TestCase):
	@patch("enable_banking.operations.frappe")
	def test_error_log_does_not_include_exception_payload(self, frappe_mock):
		log_operational_error(
			"transaction import failed",
			RuntimeError(
				"JWT eyJheader.payload.signature "
				"IBAN FI2112345600000785 "
				"authorization-code auth-code-secret "
				"session session-secret "
				"-----BEGIN PRIVATE KEY----- private-key-secret"
			),
		)

		message = frappe_mock.log_error.call_args.kwargs["message"]
		self.assertIn("RuntimeError", message)
		for sensitive_value in (
			"eyJheader",
			"FI2112345600000785",
			"auth-code-secret",
			"session-secret",
			"private-key-secret",
		):
			with self.subTest(sensitive_value=sensitive_value):
				self.assertNotIn(sensitive_value, message)
