from __future__ import annotations

import re
import time
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote

import frappe
import jwt
import requests

from enable_banking.configuration import EnableBankingConfig
from enable_banking.exceptions import (
	EnableBankingAPIError,
	EnableBankingConfigurationError,
	EnableBankingRequestError,
)

JWT_ISSUER = "enablebanking.com"
JWT_AUDIENCE = "api.enablebanking.com"
JWT_TTL = timedelta(minutes=5)
DEFAULT_TIMEOUT = (10, 60)
DEFAULT_MAX_GET_ATTEMPTS = 3
RETRYABLE_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})
SENSITIVE_KEYS = frozenset(
	{
		"authorization",
		"authorization_code",
		"code",
		"credential",
		"credentials",
		"iban",
		"account_id",
		"all_account_ids",
		"identification",
		"private_key",
		"token",
		"jwt",
	}
)
JWT_PATTERN = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")
PEM_PATTERN = re.compile(
	r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----",
	flags=re.DOTALL,
)
RESOURCE_PATH_PATTERN = re.compile(
	r"/(accounts|sessions)/[^/?]+",
	flags=re.IGNORECASE,
)


class EnableBankingClient:
	def __init__(
		self,
		config: EnableBankingConfig | None = None,
		*,
		session: requests.Session | None = None,
		timeout: tuple[int, int] = DEFAULT_TIMEOUT,
		max_get_attempts: int = DEFAULT_MAX_GET_ATTEMPTS,
		sleep: Callable[[float], None] = time.sleep,
		now: Callable[[], datetime] | None = None,
	):
		self.config = (config or EnableBankingConfig.from_settings()).validate()
		self.session = session or requests.Session()
		self.timeout = timeout
		self.max_get_attempts = max(1, max_get_attempts)
		self.sleep = sleep
		self.now = now or (lambda: datetime.now(UTC))

	def create_jwt(self) -> str:
		issued_at = self.now().astimezone(UTC)
		payload = {
			"iss": JWT_ISSUER,
			"aud": JWT_AUDIENCE,
			"iat": int(issued_at.timestamp()),
			"exp": int((issued_at + JWT_TTL).timestamp()),
		}
		headers = {"typ": "JWT", "kid": self.config.app_id}

		try:
			return jwt.encode(
				payload,
				self.config.read_private_key(),
				algorithm="RS256",
				headers=headers,
			)
		except (ValueError, TypeError, jwt.PyJWTError) as exc:
			raise EnableBankingConfigurationError(
				"Enable Banking private key could not sign an RS256 JWT."
			) from exc

	def get_application(self) -> dict[str, Any]:
		return self._request("GET", "/application")

	def get_aspsps(
		self,
		*,
		country: str | None = None,
		service: str = "AIS",
	) -> dict[str, Any]:
		return self._request(
			"GET",
			"/aspsps",
			params={"country": country, "service": service},
		)

	def start_authorization(self, payload: Mapping[str, Any]) -> dict[str, Any]:
		return self._request("POST", "/auth", json=dict(payload))

	def authorize_session(self, code: str) -> dict[str, Any]:
		return self._request("POST", "/sessions", json={"code": code})

	def get_session(self, session_id: str) -> dict[str, Any]:
		return self._request("GET", f"/sessions/{_path_segment(session_id)}")

	def delete_session(
		self,
		session_id: str,
		*,
		psu_headers: Mapping[str, str] | None = None,
	) -> dict[str, Any]:
		return self._request(
			"DELETE",
			f"/sessions/{_path_segment(session_id)}",
			headers=psu_headers,
		)

	def get_account_details(
		self,
		account_id: str,
		*,
		psu_headers: Mapping[str, str] | None = None,
	) -> dict[str, Any]:
		return self._request(
			"GET",
			f"/accounts/{_path_segment(account_id)}/details",
			headers=psu_headers,
		)

	def get_account_balances(
		self,
		account_id: str,
		*,
		psu_headers: Mapping[str, str] | None = None,
	) -> dict[str, Any]:
		return self._request(
			"GET",
			f"/accounts/{_path_segment(account_id)}/balances",
			headers=psu_headers,
		)

	def get_account_transactions(
		self,
		account_id: str,
		*,
		date_from: date | str | None = None,
		date_to: date | str | None = None,
		transaction_status: str | None = None,
		strategy: str | None = None,
		psu_headers: Mapping[str, str] | None = None,
	) -> dict[str, Any]:
		path = f"/accounts/{_path_segment(account_id)}/transactions"
		params = {
			"date_from": _date_string(date_from),
			"date_to": _date_string(date_to),
			"transaction_status": transaction_status,
			"strategy": strategy,
		}
		transactions: list[dict[str, Any]] = []
		seen_continuation_keys: set[str] = set()

		while True:
			page = self._request("GET", path, params=params, headers=psu_headers)
			transactions.extend(page.get("transactions") or [])
			continuation_key = page.get("continuation_key")
			if not continuation_key:
				break
			if continuation_key in seen_continuation_keys:
				raise EnableBankingRequestError(
					"Enable Banking returned a repeated transaction continuation key."
				)
			seen_continuation_keys.add(continuation_key)
			params["continuation_key"] = continuation_key

		return {"transactions": transactions, "continuation_key": None}

	def get_transaction(
		self,
		account_id: str,
		transaction_id: str,
		*,
		psu_headers: Mapping[str, str] | None = None,
	) -> dict[str, Any]:
		return self._request(
			"GET",
			f"/accounts/{_path_segment(account_id)}/transactions/{_path_segment(transaction_id)}",
			headers=psu_headers,
		)

	def _request(
		self,
		method: str,
		path: str,
		*,
		params: Mapping[str, Any] | None = None,
		json: Mapping[str, Any] | None = None,
		headers: Mapping[str, str] | None = None,
	) -> dict[str, Any]:
		if not path.startswith("/") or "://" in path:
			raise ValueError("Enable Banking API path must be relative to the configured API URL.")

		method = method.upper()
		max_attempts = self.max_get_attempts if method == "GET" else 1
		url = f"{self.config.api_url}{path}"
		request_headers = _validated_psu_headers(headers)
		request_headers["Accept"] = "application/json"
		if json is not None:
			request_headers["Content-Type"] = "application/json"

		for attempt in range(1, max_attempts + 1):
			request_headers["Authorization"] = f"Bearer {self.create_jwt()}"
			try:
				response = self.session.request(
					method,
					url,
					params=_without_none(params),
					json=json,
					headers=request_headers,
					timeout=self.timeout,
				)
			except (requests.Timeout, requests.ConnectionError) as exc:
				if attempt < max_attempts:
					self._log_retry(method, path, attempt, reason=exc.__class__.__name__)
					self.sleep(_backoff_seconds(attempt))
					continue
				raise EnableBankingRequestError(
					f"Enable Banking request failed: {method} {_redact_endpoint(path)}."
				) from exc
			except requests.RequestException as exc:
				raise EnableBankingRequestError(
					f"Enable Banking request failed: {method} {_redact_endpoint(path)}."
				) from exc

			if response.status_code in RETRYABLE_STATUS_CODES and attempt < max_attempts:
				delay = _retry_delay(response, attempt, now=self.now())
				self._log_retry(
					method,
					path,
					attempt,
					reason=f"HTTP {response.status_code}",
					delay=delay,
				)
				self.sleep(delay)
				continue

			return self._decode_response(response, method=method, path=path)

		raise EnableBankingRequestError("Enable Banking request exhausted all retry attempts.")

	def _decode_response(
		self,
		response: requests.Response,
		*,
		method: str,
		path: str,
	) -> dict[str, Any]:
		if 200 <= response.status_code < 300:
			if response.status_code == 204 or not response.content:
				return {}
			try:
				data = response.json()
			except requests.JSONDecodeError as exc:
				raise EnableBankingRequestError(
					f"Enable Banking returned invalid JSON for {method} {_redact_endpoint(path)}."
				) from exc
			if not isinstance(data, dict):
				raise EnableBankingRequestError(
					f"Enable Banking returned an unexpected response for {method} {_redact_endpoint(path)}."
				)
			return data

		error_code = None
		try:
			error_data = response.json()
			if isinstance(error_data, dict):
				error_code = error_data.get("code") or error_data.get("error")
		except requests.JSONDecodeError:
			pass

		endpoint = _redact_endpoint(path)
		message = f"Enable Banking API returned HTTP {response.status_code} for {method} {endpoint}."
		if error_code:
			message += f" Error code: {sanitize_for_log(str(error_code))}."
		raise EnableBankingAPIError(
			message,
			status_code=response.status_code,
			error_code=str(error_code) if error_code else None,
			endpoint=endpoint,
		)

	def _log_retry(
		self,
		method: str,
		path: str,
		attempt: int,
		*,
		reason: str,
		delay: float | None = None,
	) -> None:
		frappe.logger("enable_banking").warning(
			"Retrying Enable Banking request",
			extra={
				"method": method,
				"endpoint": _redact_endpoint(path),
				"attempt": attempt,
				"reason": sanitize_for_log(reason),
				"delay_seconds": delay,
			},
		)


def sanitize_for_log(value: Any) -> Any:
	if isinstance(value, Mapping):
		return {
			key: "[REDACTED]" if str(key).lower() in SENSITIVE_KEYS else sanitize_for_log(item)
			for key, item in value.items()
		}
	if isinstance(value, list | tuple):
		return [sanitize_for_log(item) for item in value]
	if not isinstance(value, str):
		return value

	sanitized = PEM_PATTERN.sub("[REDACTED PRIVATE KEY]", value)
	sanitized = JWT_PATTERN.sub("[REDACTED JWT]", sanitized)
	return sanitized


def _without_none(values: Mapping[str, Any] | None) -> dict[str, Any] | None:
	if values is None:
		return None
	return {key: value for key, value in values.items() if value is not None}


def _validated_psu_headers(headers: Mapping[str, str] | None) -> dict[str, str]:
	if not headers:
		return {}
	return {key: value for key, value in headers.items() if key.lower().startswith("psu-")}


def _path_segment(value: str) -> str:
	if not value:
		raise ValueError("Enable Banking resource identifier cannot be empty.")
	return quote(value, safe="")


def _date_string(value: date | str | None) -> str | None:
	if isinstance(value, date):
		return value.isoformat()
	return value


def _redact_endpoint(path: str) -> str:
	return RESOURCE_PATH_PATTERN.sub(r"/\1/[REDACTED]", path)


def _backoff_seconds(attempt: int) -> float:
	return min(0.5 * (2 ** (attempt - 1)), 8.0)


def _retry_delay(response: requests.Response, attempt: int, *, now: datetime) -> float:
	retry_after = response.headers.get("Retry-After")
	if retry_after:
		try:
			return max(0.0, float(retry_after))
		except ValueError:
			try:
				retry_at = parsedate_to_datetime(retry_after)
				if retry_at.tzinfo is None:
					retry_at = retry_at.replace(tzinfo=UTC)
				return max(0.0, (retry_at - now.astimezone(UTC)).total_seconds())
			except (TypeError, ValueError, OverflowError):
				pass
	return _backoff_seconds(attempt)
