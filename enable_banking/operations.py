from __future__ import annotations

import frappe

from enable_banking.client import sanitize_for_log


def log_operational_error(operation: str, exc: Exception | str) -> None:
	"""Create a compact Error Log without document names, provider IDs, or payloads."""
	error_type = exc.__class__.__name__ if isinstance(exc, Exception) else "Error"
	details = []
	for label, attribute in (
		("HTTP status", "status_code"),
		("Endpoint", "endpoint"),
	):
		if value := getattr(exc, attribute, None):
			details.append(f"{label}: {sanitize_for_log(value)}")
	message = "\n".join(
		[
			f"Operation: {operation}",
			f"Error type: {error_type}",
			*details,
			"Details are stored in sanitized form on the related integration record.",
		]
	)
	try:
		frappe.log_error(
			message=message[:2000],
			title=f"Enable Banking: {operation}"[:140],
		)
	except Exception:
		try:
			frappe.logger("enable_banking").exception("Could not create Enable Banking Error Log")
		except Exception:
			pass


def sanitized_error(exc: Exception | str, *, limit: int = 500) -> str:
	return str(sanitize_for_log(str(exc)))[:limit]
