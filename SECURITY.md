# Security Policy

## Supported Versions

This project currently supports security fixes on the latest `main` branch.

## Reporting a Vulnerability

Please do **not** open public issues for suspected vulnerabilities.

Report privately via GitHub Security Advisories:

1. Open the repository on GitHub.
2. Go to **Security** → **Advisories** → **Report a vulnerability**.
3. Include reproduction steps, impact, and affected files/versions.

## Secrets and Sensitive Data

This repository must not contain:

- Real API keys or tokens
- Local config with credentials (for example `local.config.json`)
- Private keys/certificates (`.pem`, `.key`, `.p12`, `.pfx`, etc.)
- Runtime outputs that may contain sensitive document names or content

Use `local.config.sample.json` as a template and keep real credentials local only.
