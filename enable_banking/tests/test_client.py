import unittest
from datetime import UTC, date, datetime
from unittest.mock import Mock, patch

import jwt
import requests

from enable_banking.client import EnableBankingClient, sanitize_for_log
from enable_banking.configuration import EnableBankingConfig
from enable_banking.exceptions import EnableBankingAPIError, EnableBankingRequestError

TEST_PRIVATE_KEY = """-----BEGIN PRIVATE KEY-----
MIIEvQIBADANBgkqhkiG9w0BAQEFAASC...
-----END PRIVATE KEY-----
"""


def make_response(status_code=200, payload=None, headers=None):
	response = Mock(spec=requests.Response)
	response.status_code = status_code
	response.headers = headers or {}
	response.content = b"" if payload is None else b"json"
	response.json.return_value = payload
	return response


class TestEnableBankingClient(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		from cryptography.hazmat.primitives.asymmetric import rsa
		from cryptography.hazmat.primitives.serialization import (
			Encoding,
			NoEncryption,
			PrivateFormat,
		)

		cls.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
		cls.private_key_pem = cls.private_key.private_bytes(
			Encoding.PEM,
			PrivateFormat.PKCS8,
			NoEncryption(),
		).decode()

	def setUp(self):
		self.config = EnableBankingConfig(
			app_id="test-app-id",
			redirect_url="http://localhost/callback",
			private_key_content=self.private_key_pem,
		)
		self.session = Mock(spec=requests.Session)
		self.now = datetime(2026, 6, 18, 12, 0, tzinfo=UTC)
		self.sleep = Mock()
		self.client = EnableBankingClient(
			self.config,
			session=self.session,
			sleep=self.sleep,
			now=lambda: self.now,
		)

	def test_jwt_contains_required_headers_and_claims(self):
		token = self.client.create_jwt()
		headers = jwt.get_unverified_header(token)
		claims = jwt.decode(
			token,
			self.private_key.public_key(),
			algorithms=["RS256"],
			audience="api.enablebanking.com",
			options={"verify_exp": False, "verify_iat": False},
		)

		self.assertEqual(headers["typ"], "JWT")
		self.assertEqual(headers["alg"], "RS256")
		self.assertEqual(headers["kid"], "test-app-id")
		self.assertEqual(claims["iss"], "enablebanking.com")
		self.assertEqual(claims["iat"], int(self.now.timestamp()))
		self.assertEqual(claims["exp"] - claims["iat"], 300)

	def test_get_retries_retryable_status_and_respects_retry_after(self):
		self.session.request.side_effect = [
			make_response(429, {"code": "RATE_LIMIT"}, {"Retry-After": "2"}),
			make_response(200, {"active": True}),
		]

		result = self.client.get_application()

		self.assertEqual(result, {"active": True})
		self.assertEqual(self.session.request.call_count, 2)
		self.sleep.assert_called_once_with(2.0)

	def test_post_is_not_retried(self):
		self.session.request.return_value = make_response(503, {"code": "ASPSP_ERROR"})

		with self.assertRaises(EnableBankingAPIError):
			self.client.start_authorization({"state": "secret"})

		self.assertEqual(self.session.request.call_count, 1)
		self.sleep.assert_not_called()

	def test_psu_headers_cannot_override_authorization(self):
		self.session.request.return_value = make_response(200, {"balances": []})

		self.client.get_account_balances(
			"account-id",
			psu_headers={
				"Psu-Ip-Address": "127.0.0.1",
				"Authorization": "attacker",
				"X-Injected": "attacker",
			},
		)

		headers = self.session.request.call_args.kwargs["headers"]
		self.assertTrue(headers["Authorization"].startswith("Bearer "))
		self.assertNotEqual(headers["Authorization"], "attacker")
		self.assertEqual(headers["Psu-Ip-Address"], "127.0.0.1")
		self.assertNotIn("X-Injected", headers)

	def test_get_retries_connection_errors(self):
		self.session.request.side_effect = [
			requests.ConnectionError("network"),
			make_response(200, {"active": True}),
		]

		self.assertEqual(self.client.get_application(), {"active": True})
		self.sleep.assert_called_once_with(0.5)

	def test_request_failure_does_not_expose_account_id(self):
		self.session.request.side_effect = requests.Timeout("timed out")

		with self.assertRaises(EnableBankingRequestError) as caught:
			self.client.get_account_balances("sensitive-account-id")

		self.assertNotIn("sensitive-account-id", str(caught.exception))
		self.assertIn("[REDACTED]", str(caught.exception))

	def test_transactions_follow_continuation_keys(self):
		self.session.request.side_effect = [
			make_response(
				200,
				{"transactions": [{"entry_reference": "one"}], "continuation_key": "next"},
			),
			make_response(
				200,
				{"transactions": [{"entry_reference": "two"}], "continuation_key": None},
			),
		]

		result = self.client.get_account_transactions(
			"account-id",
			date_from=date(2026, 1, 1),
			date_to="2026-06-18",
			transaction_status="BOOK",
		)

		self.assertEqual(
			result["transactions"],
			[{"entry_reference": "one"}, {"entry_reference": "two"}],
		)
		first_params = self.session.request.call_args_list[0].kwargs["params"]
		second_params = self.session.request.call_args_list[1].kwargs["params"]
		self.assertEqual(first_params["date_from"], "2026-01-01")
		self.assertNotIn("continuation_key", first_params)
		self.assertEqual(second_params["continuation_key"], "next")

	def test_repeated_continuation_key_is_rejected(self):
		self.session.request.side_effect = [
			make_response(200, {"transactions": [], "continuation_key": "same"}),
			make_response(200, {"transactions": [], "continuation_key": "same"}),
		]

		with self.assertRaisesRegex(EnableBankingRequestError, "repeated"):
			self.client.get_account_transactions("account-id")

	def test_api_error_exposes_only_status_and_error_code(self):
		self.session.request.return_value = make_response(
			400,
			{"code": "WRONG_REQUEST_PARAMETERS", "detail": "IBAN FI001234567"},
		)

		with self.assertRaises(EnableBankingAPIError) as caught:
			self.client.get_application()

		self.assertEqual(caught.exception.status_code, 400)
		self.assertEqual(caught.exception.error_code, "WRONG_REQUEST_PARAMETERS")
		self.assertNotIn("FI001234567", str(caught.exception))

	@patch("enable_banking.client.frappe.logger")
	def test_log_sanitizer_redacts_secrets(self, _logger):
		token = "eyJheader.payload.signature"
		private_key = "-----BEGIN PRIVATE KEY-----\nsecret\n-----END PRIVATE KEY-----"
		data = {
			"authorization": f"Bearer {token}",
			"account_id": "account",
			"message": f"{token} {private_key}",
		}

		sanitized = sanitize_for_log(data)

		self.assertEqual(sanitized["authorization"], "[REDACTED]")
		self.assertEqual(sanitized["account_id"], "[REDACTED]")
		self.assertNotIn("secret", sanitized["message"])
