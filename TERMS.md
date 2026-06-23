# Terms of Use Template for ERPNext Operators

This document is an operator-facing template. It is not legal advice and does not create complete
terms for your organization by itself. Each ERPNext operator must adapt it to their own company,
hosting setup, retention rules, legal basis, data protection contact, users, jurisdiction, and
business process.

Replace all placeholders before publishing these terms.

## Operator and scope

These terms apply to the use of the Enable Banking integration in the ERPNext site operated by:

- Operator legal name: `[Operator legal name]`
- ERPNext site or service name: `[Site/service name]`
- Contact: `[Operator contact details]`
- Data protection contact: `[Data protection contact, if different]`

The operator is responsible for configuring, hosting, securing, monitoring, and legally operating
the ERPNext site and this integration.

## Independent project notice

This app is an independent, community-developed integration for ERPNext. It is not affiliated with,
endorsed by, sponsored by, or financially connected to Enable Banking Oy. "Enable Banking" and
related trademarks belong to their respective owners and are used only to identify the API with
which this software interoperates.

## Enable Banking account and API terms

The operator must obtain and maintain its own Enable Banking account, application registration,
API credentials, redirect URL configuration, and any required commercial or contractual
arrangements.

The operator and its users must comply with Enable Banking's applicable API terms, documentation,
acceptable use rules, security requirements, and any limits or restrictions applied by Enable
Banking or connected banks/ASPSPs.

This app does not grant any right to use Enable Banking services except through the operator's own
valid Enable Banking account and agreements.

## Bank consent and authorization

Users may only connect bank accounts where they have the required authority to grant access. By
starting an authorization flow, the user confirms that they are authorized to connect the selected
bank account to the operator's ERPNext site for the purposes defined by the operator.

Bank access depends on the consent or authorization granted through Enable Banking and the selected
bank or ASPSP. Consents may expire, be rejected, be revoked, require renewal, or be limited by the
bank, Enable Banking, regulation, user permissions, or technical availability.

The operator is responsible for explaining to users what access is requested, why it is requested,
how long it is retained, and how authorization can be renewed or revoked.

## ERPNext import and reconciliation

This app imports bank account information, balances, and booked transactions into ERPNext according
to the operator's configuration and the data returned by Enable Banking and the connected bank.

Imported data may be delayed, incomplete, duplicated, rejected, unavailable, formatted differently
between banks, or require review. The operator is responsible for:

- Mapping connected accounts to the correct ERPNext Company, GL Account, and Bank Account.
- Reviewing imported Bank Transactions before relying on them.
- Reconciling transactions according to the operator's accounting process.
- Correcting mapping, currency, tax, accounting, or reconciliation errors.
- Maintaining appropriate audit trails, backups, and internal controls.

The integration is an operational tool and does not replace accounting review, bank statements,
professional judgment, or legally required records.

## No financial, legal, tax, or accounting advice

This app and these template terms do not provide financial, legal, tax, accounting, regulatory, or
compliance advice. Operators and users must consult qualified professionals where advice is needed.

The operator is responsible for determining whether and how this integration may be used in its own
business, jurisdiction, accounting process, security model, and regulatory environment.

## Availability and limitations

Availability of the integration depends on multiple systems and conditions, including the
operator's ERPNext site, hosting infrastructure, scheduled jobs, internet connectivity, Enable
Banking APIs, selected banks/ASPSPs, valid user authorization, account status, API limits, and
software configuration.

The integration may be unavailable, delayed, interrupted, or return errors. Synchronization may stop
or require manual action when consent expires, a bank connection changes, a provider returns an
error, credentials are invalid, account mappings are incomplete, or the ERPNext site is unavailable.

The operator should monitor synchronization status, review errors, and maintain fallback processes
for obtaining bank data directly from the bank when needed.

## Security and operator responsibility

The operator is responsible for securing the ERPNext site and integration, including user access,
administrator privileges, API credentials, private keys, site encryption keys, backups, logs,
servers, databases, TLS, and connected services.

Users must follow the operator's access control, credential, and security policies. Users must not
connect accounts without authorization, misuse imported data, bypass permissions, or share
credentials or private keys.

## Privacy and data protection

The operator is responsible for publishing and maintaining an appropriate privacy notice describing
how personal data is processed through the ERPNext site and this integration.

Operators should adapt `PRIVACY.md` or their own privacy documentation to reflect their actual
company, hosting setup, legal basis, retention rules, data recipients, security measures, user
rights, and contact details.

## AGPL-3.0 license

This app is licensed under the GNU Affero General Public License v3.0 (`AGPL-3.0`). The license
governs copying, modification, distribution, and network use of the app source code.

See `license.txt` in this repository for the license text. Operators are responsible for complying
with the AGPL-3.0 when they modify, deploy, or provide network access to the app.

## Contact

For questions about these operator terms or use of this ERPNext site, contact:

`[Operator contact]`

For questions about Enable Banking's own services, terms, or availability, consult Enable Banking's
own documentation and support channels. For questions about a bank account, consent, or bank data,
contact the relevant bank or ASPSP.
