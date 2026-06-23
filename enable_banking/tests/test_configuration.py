import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

from enable_banking.configuration import (
	API_URL_SITE_CONFIG_KEY,
	DEFAULT_API_URL,
	EnableBankingConfig,
	_configured_api_url,
	validate_private_key,
)
from enable_banking.exceptions import EnableBankingConfigurationError


class TestEnableBankingConfig(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.private_key = (
			rsa.generate_private_key(public_exponent=65537, key_size=2048)
			.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
			.decode()
		)

	def make_config(self, **overrides):
		values = {
			"app_id": "app-id",
			"private_key_content": self.private_key,
			"redirect_url": "http://localhost/callback",
			"api_url": "https://api.enablebanking.com",
		}
		values.update(overrides)
		return EnableBankingConfig(**values)

	def test_valid_localhost_redirect_and_pasted_key(self):
		config = self.make_config().validate()
		self.assertEqual(config.read_private_key(), self.private_key)

	def test_rejects_invalid_private_key(self):
		with self.assertRaisesRegex(EnableBankingConfigurationError, "PEM"):
			self.make_config(private_key_content="not a key").validate()

	def test_rejects_non_https_api_url(self):
		with self.assertRaisesRegex(EnableBankingConfigurationError, "HTTPS"):
			self.make_config(api_url="http://api.enablebanking.com").validate()

	def test_rejects_non_local_http_redirect(self):
		with self.assertRaisesRegex(EnableBankingConfigurationError, "localhost"):
			self.make_config(redirect_url="http://example.com/callback").validate()

	def test_bytes_private_key_is_decoded(self):
		self.assertEqual(validate_private_key(self.private_key.encode()), self.private_key)

	@patch("enable_banking.configuration.frappe")
	def test_default_api_url_is_fixed(self, frappe_mock):
		frappe_mock.conf = {}

		self.assertEqual(_configured_api_url(), DEFAULT_API_URL)

	@patch("enable_banking.configuration.frappe")
	def test_api_url_override_comes_only_from_site_config(self, frappe_mock):
		frappe_mock.conf = {API_URL_SITE_CONFIG_KEY: "https://sandbox.example.test/"}

		self.assertEqual(_configured_api_url(), "https://sandbox.example.test")

	@patch("enable_banking.configuration.frappe")
	def test_non_https_site_config_override_is_rejected(self, frappe_mock):
		frappe_mock.conf = {API_URL_SITE_CONFIG_KEY: "http://sandbox.example.test"}

		with self.assertRaisesRegex(EnableBankingConfigurationError, "HTTPS"):
			self.make_config(api_url=_configured_api_url()).validate()
