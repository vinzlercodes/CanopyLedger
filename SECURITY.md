# Security policy

CanopyLedger is a synthetic reference application. Do not submit real borrower, farmer, customer,
market, document, location, or credential data to this project.

## Report a vulnerability

Please report security vulnerabilities privately through the repository’s
[GitHub security-advisory form](https://github.com/vinzlercodes/CanopyLedger/security/advisories/new).
Do not open a public issue, discussion, or pull request for a suspected vulnerability.

Include a clear description, affected version or commit, reproduction steps, impact, and any safe
proof of concept. Remove credentials, access tokens, and sensitive data before sending a report.

If the advisory form is unavailable, contact the repository owner privately through GitHub rather
than disclosing the issue publicly. We will acknowledge valid reports, investigate them, and coordinate
the disclosure of a fix when one is available.

## Supported versions

Security fixes are considered for the latest release and the default branch. This reference project
is not offered as a managed production service.

## Secure use

Keep secrets in environment variables or your deployment’s secret store. Never commit `.env` files,
private keys, live banking or trading credentials, or real financial and document data. The local
demo identities are public synthetic fixtures and must never be adapted as a production authentication
mechanism.
