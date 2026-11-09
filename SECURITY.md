# Security policy

This is a portfolio project. Nothing in it is deployed, and it holds no real passenger data:
Harrowgate International, its airlines, shops and passengers are fictional, and every scenario in
the evaluation suite is synthetic.

## Report a vulnerability

Please report privately through GitHub: open the **Security** tab of this repository and choose
**Report a vulnerability** (private vulnerability reporting is on). Please do not open a public issue.
You should get a first reply within a week.

## Controls in place

- Secret scanning with push protection, Dependabot alerts and security updates
- CodeQL (`security-and-quality`) on every push and weekly
- gitleaks over the full git history in CI
- Every GitHub Action pinned to a commit SHA; workflow tokens are read-only
- `main` is protected: no force-push or deletion, and pull requests need the CI checks
- The deploy workflow is manual, gated by `DEPLOY_ENABLED`, and logs in with OIDC (no client secret)
- Agents hold read-only tools; only the executor can run writes, and only with a policy-signed token
- Traces mask names and emails and replace passenger ids with keyed pseudonyms
- The Microsoft Foundry resource has key authentication disabled; the app uses a managed identity
