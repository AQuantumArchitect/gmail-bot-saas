# Supabase Service Overview for Email-Bot SaaS

Your backend now sits on top of Supabase’s managed schemas. This document **exhaustively** lists every built-in table and capability available, so your API layer can use them directly—no hidden reliance on external docs.

---

## 🔐 `auth` schema — Authentication & Identity

| Table                          | Description                                                                                       |
|--------------------------------|---------------------------------------------------------------------------------------------------|
| **auth.users**                 | Core user record (id, email, encrypted_password, phone, confirmation timestamps, metadata, ban/anon flags). Primary key for all references. |
| **auth.identities**            | Linked OAuth/SAML identities: provider, JSONB profile data, last_sign_in_at.                      |
| **auth.sessions**              | Session entries: user_id, created_at, updated_at, IP, user_agent, factor_id, AAL, not_after.     |
| **auth.audit_log_entries**     | Immutable log of auth events: id, payload, created_at, ip_address.                                |
| **auth.flow_state**            | PKCE and 3rd‑party flow state: auth_code, challenge, provider tokens, timestamps.                |
| **auth.one_time_tokens**       | Magic-link, invite, reset tokens: token_type, token_hash, relates_to, created_at.                |
| **auth.refresh_tokens**        | Low-level refresh token chains: token, session_id, revoked flag.                                  |
| **auth.mfa_factors**           | Registered MFA factors: TOTP/WebAuthn credentials, type/status, user_id.                         |
| **auth.mfa_challenges**        | MFA challenge attempts: otp_code/web_authn_data, factor_id, verified_at.                          |
| **auth.sso_providers**         | SAML providers list: id, resource_id, timestamps.                                                |
| **auth.sso_domains**           | Allowed domains for SSO: domain, provider_id.                                                    |
| **auth.saml_providers**        | SAML metadata XML/URL and mapping rules.                                                         |
| **auth.saml_relay_states**     | Temporary SAML redirect linking: request_id, flow_state_id, for_email.                            |
| **auth.schema_migrations**     | Internal versioning for auth schema updates.                                                     |

**RLS / JWT Helpers**
- `auth.uid()` → current user’s UUID  
- `auth.role()` → `authenticated`, `anon`, or `service_role`

---

## 🔐 `storage` schema — File Storage & Object Store

| Table                            | Description                                                         |
|----------------------------------|---------------------------------------------------------------------|
| **storage.buckets**              | Bucket definitions: ACL (public), file_size_limit, MIME types, owner |
| **storage.objects**              | Object metadata: id, bucket_id, name, path_tokens, metadata, version |
| **storage.s3_multipart_uploads** | Tracks in-flight multi-part uploads                                 |
| **storage.s3_multipart_uploads_parts** | Individual parts info                                     |
| **storage.migrations**           | Versioning for storage schema changes                              |

**APIs**
- **Pre-signed URLs** for upload/download  
- **Row-level** ACL: `storage.objects.owner` with RLS policies  

---

## 🔐 `vault` schema — Secrets Management

| Table            | Description                                              |
|------------------|----------------------------------------------------------|
| **vault.secrets**| Encrypted secrets storage: `name`, `secret` (pgcrypto), nonce, timestamps. |

Use stored secrets for encryption keys (e.g., OAuth tokens) via `pgp_sym_encrypt()` / `pgp_sym_decrypt()`.

---

## 🔌 Extensions Enabled

| Extension               | Provided Functions                                       |
|-------------------------|----------------------------------------------------------|
| `uuid-ossp`             | `gen_random_uuid()`                                       |
| `pgcrypto`              | `pgp_sym_encrypt()`, `pgp_sym_decrypt()`, cryptographic hashes |
| `pg_stat_statements`    | Query performance logging                                |

---

## ⚡ Auto-Generated APIs & Realtime

| Feature        | Details                                                                 |
|----------------|-------------------------------------------------------------------------|
| **REST**       | PostgREST endpoints for **all** tables in `public`, `auth`, `storage`   |
| **GraphQL**    | Optional GraphQL endpoint via Hasura (if enabled)                       |
| **Realtime**   | `realtime` subscriptions on `public.*` via WAL replication logs         |

**Security**: All endpoints obey RLS policies. Use JWT (`Authorization: Bearer <token>`) to authenticate.

---

> This document is your **complete reference** for everything Supabase offers out‑of‑the‑box. Your API layer can call these tables, functions, and endpoints directly—no missing pieces.

