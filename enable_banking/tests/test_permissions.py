from __future__ import annotations

import ast
import unittest
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]


class TestWhitelistedMethodPermissions(unittest.TestCase):
	def test_every_non_guest_whitelisted_method_has_an_authorization_guard(self):
		unguarded = []
		for path in APP_ROOT.rglob("*.py"):
			if "tests" in path.parts:
				continue
			tree = ast.parse(path.read_text())
			for node in ast.walk(tree):
				if not isinstance(node, ast.FunctionDef) or not _is_whitelisted(node):
					continue
				if _allows_guest(node):
					continue
				source = ast.get_source_segment(path.read_text(), node) or ""
				if not any(
					guard in source
					for guard in (
						"_require_manager()",
						"frappe.only_for(",
						"sync_account_now(",
					)
				):
					unguarded.append(f"{path.relative_to(APP_ROOT)}:{node.name}")

		self.assertEqual(unguarded, [])


def _is_whitelisted(node: ast.FunctionDef) -> bool:
	return any(
		(
			isinstance(decorator, ast.Call)
			and isinstance(decorator.func, ast.Attribute)
			and decorator.func.attr == "whitelist"
		)
		or (isinstance(decorator, ast.Attribute) and decorator.attr == "whitelist")
		for decorator in node.decorator_list
	)


def _allows_guest(node: ast.FunctionDef) -> bool:
	for decorator in node.decorator_list:
		if not isinstance(decorator, ast.Call):
			continue
		for keyword in decorator.keywords:
			if (
				keyword.arg == "allow_guest"
				and isinstance(keyword.value, ast.Constant)
				and keyword.value.value is True
			):
				return True
	return False
