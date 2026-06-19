class EnableBankingError(Exception):
	"""Base exception for the Enable Banking integration."""


class EnableBankingConfigurationError(EnableBankingError):
	"""Raised when required integration configuration is missing or unsafe."""


class EnableBankingRequestError(EnableBankingError):
	"""Raised when a request cannot reach the Enable Banking API."""


class EnableBankingAPIError(EnableBankingError):
	"""Raised when the Enable Banking API rejects a request."""

	def __init__(
		self,
		message: str,
		*,
		status_code: int,
		error_code: str | None = None,
		endpoint: str | None = None,
	):
		super().__init__(message)
		self.status_code = status_code
		self.error_code = error_code
		self.endpoint = endpoint
