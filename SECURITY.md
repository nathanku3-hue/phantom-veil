# Security Policy - Phantom Veil

## Reporting Vulnerabilities

If you discover a security vulnerability in this project, please report it via a private security advisory on GitHub or email security@phantom-veil.example.com. Do not open a public issue. We will respond within 48 hours to coordinate a fix.

## Credential Rotation

If any credentials, API keys, or secrets are accidentally committed or leaked:
1. Revoke the compromised credential immediately.
2. Trigger the Credential Rotation procedure for all associated services.
3. Purge the commit history using git-filter-repo or a similar tool.

## Agent Security Boundaries

This project runs AI-assisted developers and agents. To prevent unauthorized execution:
1. All agent runs must be bounded to the local sandbox directory.
2. Agents do not have access to push directly to origin/main without human review.
3. No credentials should be supplied to prompt templates or agent files.
