from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from enable_banking import integrity, sync


class TestBankAccountMappingIntegrity(TestCase):
	@patch("enable_banking.integrity.frappe")
	def test_valid_mapping_revalidates_company_gl_currency_and_competing_links(
		self,
		frappe_mock,
	):
		integration = SimpleNamespace(
			name="EB-ACCOUNT",
			company="Test Company",
			currency="EUR",
		)
		bank_account = _bank_account()
		frappe_mock.db.get_value.side_effect = [
			SimpleNamespace(
				company="Test Company",
				account_currency="EUR",
				account_type="Bank",
				is_group=0,
				disabled=0,
			),
			None,
		]

		integrity.validate_bank_account_mapping(integration, bank_account)

		self.assertEqual(frappe_mock.db.get_value.call_count, 2)
		frappe_mock.throw.assert_not_called()

	@patch("enable_banking.integrity.frappe")
	def test_disabled_bank_account_is_rejected(self, frappe_mock):
		frappe_mock.throw.side_effect = RuntimeError("The Bank Account is disabled.")
		bank_account = _bank_account()
		bank_account.disabled = 1

		with self.assertRaisesRegex(RuntimeError, "disabled"):
			integrity.validate_bank_account_mapping(
				SimpleNamespace(name="EB-ACCOUNT", company="Test Company", currency="EUR"),
				bank_account,
			)

	@patch("enable_banking.integrity.frappe")
	def test_reciprocal_link_is_required(self, frappe_mock):
		frappe_mock.throw.side_effect = RuntimeError(
			"The Bank Account does not point to this Enable Banking account."
		)
		integration = SimpleNamespace(name="EB-ACCOUNT", bank_account="BA-1")
		bank_account = _bank_account(enable_banking_account=None)

		with self.assertRaisesRegex(RuntimeError, "does not point"):
			integrity.validate_reciprocal_mapping(integration, bank_account)

	@patch("enable_banking.sync.validate_reciprocal_mapping")
	@patch("enable_banking.sync.validate_bank_account_mapping")
	def test_sync_revalidates_mapping_before_use(self, validate_mapping, validate_reciprocal):
		account = SimpleNamespace(
			name="EB-ACCOUNT",
			connection="CONN-1",
			company="Test Company",
		)
		connection = SimpleNamespace(name="CONN-1", company="Test Company")
		bank_account = _bank_account()

		sync._validate_mapped_bank_account(account, connection, bank_account)

		validate_mapping.assert_called_once_with(account, bank_account)
		validate_reciprocal.assert_called_once_with(account, bank_account)


def _bank_account(**overrides):
	values = {
		"name": "BA-1",
		"is_company_account": 1,
		"company": "Test Company",
		"disabled": 0,
		"integration_id": None,
		"account": "Bank EUR - TC",
		"enable_banking_account": "EB-ACCOUNT",
	}
	values.update(overrides)
	doc = SimpleNamespace(**values)
	doc.get = Mock(side_effect=lambda fieldname: getattr(doc, fieldname, None))
	return doc
