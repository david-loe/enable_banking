from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

import frappe
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key

from enable_banking.exceptions import EnableBankingConfigurationError

DEFAULT_API_URL = "https://api.enablebanking.com"
API_URL_SITE_CONFIG_KEY = "enable_banking_api_url"
SETTINGS_DOCTYPE = "Enable Banking Settings"
MAX_PRIVATE_KEY_BYTES = 64 * 1024


@dataclass(frozen=True, slots=True)
class EnableBankingConfig:
	app_id: str
	redirect_url: str
	private_key_content: str
	api_url: str = DEFAULT_API_URL

	@classmethod
	def from_settings(cls) -> EnableBankingConfig:
		settings = _get_settings()
		if not settings:
			raise EnableBankingConfigurationError(
				"Configure Enable Banking from the Enable Banking Settings form."
			)

		return cls(
			app_id=_required_settings_value(settings, "app_id"),
			redirect_url=_required_settings_value(settings, "redirect_url"),
			api_url=_configured_api_url(),
			private_key_content=_get_private_key(settings),
		).validate()

	def validate(self) -> EnableBankingConfig:
		if not self.app_id.strip():
			raise EnableBankingConfigurationError("Enable Banking application ID is empty.")

		validate_private_key(self.private_key_content)
		_validate_url(self.redirect_url, field_label="redirect URL", allow_http_localhost=True)
		_validate_url(self.api_url, field_label="API URL", allow_http_localhost=False)
		return self

	def read_private_key(self) -> str:
		return validate_private_key(self.private_key_content)


def validate_private_key(private_key: str | bytes) -> str:
	if isinstance(private_key, bytes):
		private_key_bytes = private_key
		try:
			private_key = private_key.decode("utf-8")
		except UnicodeDecodeError as exc:
			raise EnableBankingConfigurationError(
				"Enable Banking private key must be a UTF-8 PEM file."
			) from exc

	else:
		private_key_bytes = private_key.encode("utf-8")

	if len(private_key_bytes) > MAX_PRIVATE_KEY_BYTES:
		raise EnableBankingConfigurationError("Enable Banking private key exceeds 64 KiB.")

	private_key = private_key.strip() + "\n"
	try:
		parsed_key = load_pem_private_key(private_key.encode("utf-8"), password=None)
	except (TypeError, ValueError) as exc:
		raise EnableBankingConfigurationError(
			"Enable Banking private key is not a valid unencrypted PEM private key."
		) from exc
	if not isinstance(parsed_key, RSAPrivateKey):
		raise EnableBankingConfigurationError("Enable Banking private key must be an RSA private key.")
	return private_key


def _get_settings():
	if not getattr(frappe, "db", None) or not frappe.db.exists("DocType", SETTINGS_DOCTYPE):
		return None
	return frappe.get_single(SETTINGS_DOCTYPE)


def _get_private_key(settings) -> str:
	private_key = settings.get_password("private_key", raise_exception=False)
	if not private_key:
		raise EnableBankingConfigurationError("Paste a private key in Enable Banking Settings.")
	return validate_private_key(private_key)


def _configured_api_url() -> str:
	return str(frappe.conf.get(API_URL_SITE_CONFIG_KEY) or DEFAULT_API_URL).strip().rstrip("/")


def _required_settings_value(settings, fieldname: str) -> str:
	value = _settings_value(settings, fieldname)
	if not value:
		raise EnableBankingConfigurationError(f"Missing required Enable Banking setting: {fieldname}")
	return value


def _settings_value(settings, fieldname: str) -> str | None:
	value = settings.get(fieldname)
	return str(value).strip() if value and str(value).strip() else None


def _validate_url(url: str, *, field_label: str, allow_http_localhost: bool) -> None:
	parsed = urlparse(url)
	is_local_http = (
		allow_http_localhost
		and parsed.scheme == "http"
		and parsed.hostname
		in {
			"localhost",
			"127.0.0.1",
			"::1",
		}
	)
	if not parsed.netloc or (parsed.scheme != "https" and not is_local_http):
		raise EnableBankingConfigurationError(
			f"Enable Banking {field_label} must use HTTPS"
			+ (" (HTTP is allowed only for localhost)." if allow_http_localhost else ".")
		)
