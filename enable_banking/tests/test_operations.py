from unittest import TestCase
from unittest.mock import patch

from enable_banking.exceptions import EnableBankingAPIError
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

	@patch("enable_banking.operations.frappe")
	def test_error_log_includes_provider_error_code_without_provider_payload(self, frappe_mock):
		log_operational_error(
			"account refresh failed",
			EnableBankingAPIError(
				"Enable Banking API returned HTTP 400. Error code: CONSENT_INVALID. "
				"Detail: account_id acc-123.",
				status_code=400,
				endpoint="/accounts/[REDACTED]/details",
				provider_error="CONSENT_INVALID",
				provider_detail="account_id [REDACTED]",
			),
		)

		message = frappe_mock.log_error.call_args.kwargs["message"]
		self.assertIn("HTTP status: 400", message)
		self.assertIn("Provider error: CONSENT_INVALID", message)
		self.assertIn("Endpoint: /accounts/[REDACTED]/details", message)
		self.assertNotIn("account_id", message)
		self.assertNotIn("acc-123", message)
