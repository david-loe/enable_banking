import unittest
from unittest.mock import Mock, patch

from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

from enable_banking.configuration import (
	EnableBankingConfig,
	get_uploaded_private_key,
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

	@patch("enable_banking.configuration.frappe.get_doc")
	def test_uploaded_private_file_is_supported(self, get_doc):
		file_doc = Mock(
			is_private=1,
			file_url="/private/files/key.pem",
			file_size=len(self.private_key),
		)
		file_doc.get_content.return_value = self.private_key.encode()
		get_doc.return_value = file_doc

		self.assertEqual(get_uploaded_private_key("/private/files/key.pem"), self.private_key)
		get_doc.assert_called_once_with(
			"File",
			{
				"file_url": "/private/files/key.pem",
				"attached_to_doctype": "Enable Banking Settings",
				"attached_to_name": "Enable Banking Settings",
				"attached_to_field": "private_key_file",
			},
		)

	@patch("enable_banking.configuration.frappe.get_doc")
	def test_public_uploaded_file_is_rejected(self, get_doc):
		get_doc.return_value = Mock(
			is_private=0,
			file_url="/files/key.pem",
			file_size=len(self.private_key),
		)

		with self.assertRaisesRegex(EnableBankingConfigurationError, "private files"):
			get_uploaded_private_key("/files/key.pem")

	@patch("enable_banking.configuration.frappe.get_doc")
	def test_remote_uploaded_file_is_rejected(self, get_doc):
		get_doc.return_value = Mock(
			is_private=1,
			file_url="https://example.com/key.pem",
			file_size=len(self.private_key),
		)

		with self.assertRaisesRegex(EnableBankingConfigurationError, "ERPNext site"):
			get_uploaded_private_key("https://example.com/key.pem")
