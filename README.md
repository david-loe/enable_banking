### Enable Banking

Integrate Enable Banking APIs to automatically sync bank transactions.

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch develop
bench install-app enable_banking
```

### Configuration

Open **Enable Banking Settings** in ERPNext and enter the application ID, API URL, and registered
redirect URL. The form displays the complete callback API method URL for the current site:

```text
https://your-erpnext-site.example/api/method/enable_banking.onboarding.callback
```

Register that exact URL in the Enable Banking application and copy it into **Redirect URL**. For a
local site, ensure the hostname used by Enable Banking resolves to the Frappe site.

Configure the RSA private key using either:

- **Pasted Key**: use the **Private Key → Paste Private Key** action. The PEM content is encrypted
  using Frappe's site encryption key and stored in `__Auth`.
- **Uploaded Private File**: upload the PEM through the settings attachment field. The attachment
  must be private and stored on the ERPNext site.

Server filesystem paths and public or remote key files are not supported.

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
and scheduled jobs from creating duplicates.

The Enable Banking workspace links to Settings, Connections, Accounts, and Enable Banking Bank
Transactions. Account records show the last attempt, success, import counts, watermark, and
sanitized error. Connection records show session health and the most recent account import summary.

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

### Security and production

- Keep PEM keys in the encrypted password store or a private attachment. Never commit keys or
  sandbox credentials.
- Restrict the app to System Manager and Accounts Manager users.
- Use HTTPS callback URLs outside localhost and register the exact displayed callback URL.
- Create a separate Enable Banking application and RSA key for production. Sandbox applications and
  credentials must not be reused in production.
- API logs sanitize JWTs, authorization codes, private keys, and account identifiers.

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/enable_banking
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade
### CI

This app can use GitHub Actions for CI. The following workflows are configured:

- CI: Installs this app and runs unit tests on every push to `develop` branch.
- Linters: Runs [Frappe Semgrep Rules](https://github.com/frappe/semgrep-rules) and [pip-audit](https://pypi.org/project/pip-audit/) on every pull request.


### License

agpl-3.0
