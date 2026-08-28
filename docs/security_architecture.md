# Security Architecture

The product is intended for commercial deployment, so security must be part of
the foundation rather than a later patch.

## Phase 1 Foundation

- Environment-based configuration with `ERP_` prefix.
- No committed real `.env` files or secrets.
- Production validation rejects the default development secret.
- RBAC foundation tables for users, roles, permissions, and assignments.
- PBKDF2 password hashing.
- HMAC-hashed bearer session tokens stored in `auth_sessions`.
- Fernet-encrypted connector secrets derived from `ERP_SECRET_KEY`.
- First-use setup is allowed only while no users exist.
- Audit logging for setup, settings, catalog, customers, inventory, orders,
  connector, backup, and licensing foundations.
- License activation stores only an HMAC hash of the submitted license key and
  writes a signed offline grace envelope without the raw key.
- Backup and restore-plan APIs require permissions; restore-plan is
  non-destructive in V1.
- `.gitignore` blocks runtime databases, auth caches, release builds, and key
  material.

## Required Future Controls

- Continued role enforcement on every protected endpoint as modules expand.
- Secret rotation workflow for WooCommerce keys and local connector credentials.
- Tenant/company guards on all company-scoped queries.
- Structured security logs.
- Backup encryption and restore authorization.
- Persistent production license service storage, operator authentication, key
  rotation, and monitoring.
