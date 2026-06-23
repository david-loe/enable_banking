<p align="center" >
<a href="https://enable-banking.com/">
    <img  src="./assets/enable-banking-logo-animated.svg">
</a>
</p>
<p align="center">
Integrate <a href="https://enablebanking.com/">Enable Banking APIs</a> in ERPNext to automatically sync bank transactions.
</p>

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
bench get-app https://github.com/david-loe/enable_banking
bench install-app enable_banking
```

### Configuration

Open **Enable Banking Settings** as a System Manager and enter the application ID and registered
redirect URL. The form displays the complete callback API method URL for the current site:

```text
https://your-erpnext-site.example/api/method/enable_banking.onboarding.callback
```

Register that exact URL in the Enable Banking application and copy it into **Redirect URL**. For a
local site, ensure the hostname used by Enable Banking resolves to the Frappe site.

Use **Private Key → Paste Private Key** to configure the RSA private key. Paste the PEM content or
choose a local `.pem` or `.key` file to populate the dialog. Selected files are read only in the
browser and are not uploaded as attachments. After confirmation, the PEM content is encrypted using
Frappe's site encryption key and stored in `__Auth`.

The API origin is fixed to `https://api.enablebanking.com`. A development or test deployment may
override it only through site configuration:

```bash
bench --site development.localhost set-config enable_banking_api_url https://example.test
```

The override must use HTTPS and must never be controlled through Desk.

After testing the configuration, enable the integration and use **Connect Bank**. Select the
company, an enabled Bank-type group GL account, the ASPSP, PSU type, and consent duration. The
duration is constrained by the maximum returned for the selected ASPSP.

After authorization, open each discovered **Enable Banking Account** and either map it to an
existing company Bank Account or create a new GL Account and Bank Account beneath the selected
parent.

### Synchronization

Use **Sync Now** on Enable Banking Settings to queue every mapped account, on a connection to
queue its mapped accounts, or on an individual account. Each account job:

1. verifies that the provider session still has status `AUTHORIZED`;
2. refreshes account details and balances;
3. imports booked transactions using the configured initial range or overlap range.

Automatic synchronization is disabled by default. To enable it, turn on **Automatic Sync** in
Enable Banking Settings, select **Every Hour**, **Four Times a Day**, or **Once a Day**, and enable
automatic sync on the relevant connections and accounts. The scheduler queues one job per mapped
account. A distributed account lock and transaction idempotency keys prevent overlapping manual
and scheduled jobs from creating duplicates. The settings also cap provider transaction pages and
the total transactions accepted per account run; exceeding either limit fails safely without
advancing the account watermark.

The Enable Banking workspace links to Settings, Connections, Accounts, and Enable Banking Bank
Transactions. Account records show the last attempt, success, import counts, watermark, and
sanitized error. Connection records show session health and the most recent account import summary.
Interrupted queued or in-progress jobs are detected by the hourly scheduler and marked retryable.
Operational failures also create sanitized Error Logs without provider sessions, credentials, or
financial identifiers.

### Consent renewal and recovery

When Enable Banking reports a session as cancelled, closed, expired, invalid, or revoked, the app
disables automatic synchronization for the connection and its accounts. Open the connection and use
**Reauthorize** to create a replacement consent. Accounts are matched by their stable identification
hash, so existing ERPNext mappings and imported transactions are retained.

Use **Close Connection** to revoke a session intentionally. Network or provider errors are recorded
as sanitized errors without disabling an otherwise authorized consent; retry **Sync Now** after the
provider recovers. If a transaction fails validation or insertion, the account watermark is not
advanced. Correct the reported mapping or currency issue and rerun synchronization; already-created
transactions are treated as duplicates.

Consumed, cancelled, failed, and expired one-time authorization records are deleted automatically
after 30 days.

### License

agpl-3.0

### Independent project notice

This is an independent, community-developed integration for ERPNext. It is not affiliated with,
endorsed by, sponsored by, or financially connected to Enable Banking Oy. “Enable Banking” and
related trademarks belong to their respective owners and are used only to identify the API with
which this software interoperates. Users must obtain their own Enable Banking account and comply
with the applicable API terms.
