# Privacy Notice Template for ERPNext Operators

This document is an operator-facing template. It is not legal advice and does not make your ERPNext
site compliant by itself. Each ERPNext operator must adapt it to their own company, hosting setup,
retention rules, legal basis for processing, data protection contact, enabled ERPNext features, and
app configuration.

Replace all placeholders before publishing this notice.

## Responsible operator

The responsible operator of this ERPNext site is:

- Operator legal name: `[Operator legal name]`
- Address: `[Operator address]`
- Company or registration number: `[Registration details, if applicable]`
- ERPNext site or service name: `[Site/service name]`
- Hosting setup/provider: `[Self-hosted / hosting provider / cloud region / relevant processors]`
- Data protection contact: `[Name, role, email, phone, postal address]`

The operator decides why and how personal data is processed in this ERPNext site, including data
processed through the Enable Banking integration.

## What data this app processes

When enabled and configured by the operator, this app connects ERPNext with Enable Banking APIs to
retrieve bank account information, balances, and booked transactions after a user completes the
required bank authorization flow.

Depending on the operator's configuration and the data returned by Enable Banking and the selected
bank or account servicing payment service provider (ASPSP), the app may process:

- Enable Banking authorization and session data, including authorization status, consent duration,
  provider authorization identifiers, provider session identifiers, selected ASPSP, PSU type,
  validity dates, and reauthorization state.
- Bank account data, including account names, masked account identifiers, currencies, product or
  account metadata, account usage, account type, account status, stable account identification
  hashes, and provider resource identifiers.
- Balance data, including booked balances, available balances, balance currency, balance timestamp,
  and normalized balance payloads.
- Transaction data imported into ERPNext Bank Transactions, including transaction date, amount,
  currency, direction, references, remittance information, counterparty details where provided by
  the bank, transaction code or type, and generated idempotency keys used to avoid duplicate imports.
- ERPNext mappings, including links between Enable Banking connections/accounts and ERPNext Company,
  GL Account, Bank Account, and Bank Transaction records.
- Operational data, including synchronization status, last sync timestamps, import counters,
  sanitized last error messages, and sanitized Error Logs.
- Credentials and key material configured by the operator, including the Enable Banking application
  ID and, if applicable, the RSA private key stored in ERPNext/Frappe encrypted password storage
  using the site's encryption key.

The exact data processed depends on the connected bank, the consent scope, the Enable Banking API
response, ERPNext configuration, and operator retention settings.

## Purpose of processing

The operator uses this app for purposes such as:

- Creating and maintaining bank authorization sessions through Enable Banking.
- Discovering connected bank accounts after user authorization.
- Importing account metadata, balances, and booked transactions into ERPNext.
- Mapping external bank accounts to ERPNext accounting records.
- Supporting bank transaction review, reconciliation, bookkeeping, and audit workflows.
- Monitoring synchronization health, troubleshooting operational errors, preventing duplicate
  transaction imports, and maintaining integration integrity.

The operator must document the legal basis for each processing purpose, such as contract
performance, legal obligation, legitimate interests, consent, or another applicable basis:

`[Describe legal basis and local law references here]`

## Storage in ERPNext

Data processed by this app is stored in the operator's ERPNext site and database. This may include
Enable Banking Settings, Enable Banking Authorization records, Enable Banking Connection records,
Enable Banking Account records, ERPNext Bank Account records, ERPNext Bank Transaction records,
Error Logs, audit/change history, database backups, and system logs.

The operator is responsible for the security and configuration of the ERPNext site, database,
backups, hosting infrastructure, user permissions, administrator access, and any connected support
or monitoring services.

## Sharing with Enable Banking, banks, and service providers

To provide the integration, relevant request and authorization data is exchanged with Enable
Banking and, through Enable Banking, the selected banks or ASPSPs. Users may be redirected to their
bank or authorization flow to grant, renew, or revoke access.

The operator may also share or make data accessible to:

- The operator's ERPNext hosting provider or infrastructure provider.
- Support, maintenance, monitoring, backup, or security providers used by the operator.
- Auditors, accountants, tax advisors, regulators, or other recipients where required or permitted
  by the operator's applicable law and business process.

The operator must list actual recipients, processors, countries, transfer mechanisms, and processor
agreements here:

`[Describe recipients, processors, international transfers, and safeguards here]`

## Security

This app uses ERPNext/Frappe access controls and stores configured private key material in
Frappe's encrypted password storage. Operational errors are intended to be stored in sanitized form
without provider sessions, credentials, or financial identifiers.

The operator remains responsible for implementing appropriate technical and organizational
measures, including:

- Limiting ERPNext access to authorized users and roles.
- Protecting administrator accounts, API keys, private keys, and site encryption keys.
- Securing the server, database, backups, TLS certificates, and network access.
- Reviewing logs and backups for their own retention and access controls.
- Maintaining ERPNext, Frappe, this app, and dependencies with appropriate security updates.
- Testing restore procedures and incident response processes.

## Retention

The operator must define retention periods for each data category according to their legal,
accounting, tax, contractual, and operational requirements.

Suggested retention table to adapt:

| Data category | Retention period | Reason/legal basis | Deletion or anonymization process |
| --- | --- | --- | --- |
| Enable Banking one-time authorization records | Consumed, cancelled, failed, and expired records are automatically deleted after 30 days by the app | `[Reason]` | App cleanup task |
| Active connection/session records | `[Retention period]` | `[Reason]` | `[Process]` |
| Account metadata and balances | `[Retention period]` | `[Reason]` | `[Process]` |
| Imported Bank Transactions | `[Retention period, often aligned with accounting/tax record retention]` | `[Reason]` | `[Process]` |
| ERPNext mappings | `[Retention period]` | `[Reason]` | `[Process]` |
| Logs, errors, and backups | `[Retention period]` | `[Reason]` | `[Process]` |
| Encrypted credentials/private key | Until replaced, cleared, or no longer required | `[Reason]` | Clear from Enable Banking Settings and rotate related credentials |

Deleting an Enable Banking Account record may not delete already-imported ERPNext accounting
records. Operators must define how accounting records, backups, and audit logs are retained or
removed.

## User rights

Depending on applicable law, data subjects may have rights to access, correction, deletion,
restriction, objection, portability, withdrawal of consent, or complaint to a supervisory authority.

Requests should be sent to:

`[Data protection contact and request process]`

The operator must verify the requester's identity and evaluate each request according to applicable
law, accounting obligations, tax obligations, audit requirements, contractual duties, and technical
limitations such as backups.

## Contact

For privacy questions about this ERPNext site and the Enable Banking integration, contact:

`[Operator privacy contact]`

For questions about Enable Banking's own processing, API terms, or infrastructure, consult Enable
Banking's own legal and privacy documentation. For questions about a bank's processing, consult the
relevant bank or ASPSP.
