# API Authentication and Authorization

ACME Data Platform supports two credential types: **API keys** for server-to-server
integrations and **OAuth 2.0** for applications acting on behalf of a user.

## API keys

API keys are issued per project from the console under Settings > API Keys. A key is
shown exactly once at creation and cannot be recovered afterwards; if it is lost, revoke
it and issue a new one. Keys are presented as a bearer token:

    Authorization: Bearer acme_live_XXXXXXXXXXXXXXXX

Keys are prefixed by environment: `acme_live_` for production and `acme_test_` for the
sandbox. Sandbox keys never touch production data and are rate limited independently.

### Rotation

Keys do not expire automatically. Policy requires rotation every 90 days. Two active
keys may exist per project simultaneously, which allows zero-downtime rotation: issue the
new key, deploy it, verify traffic has moved using the Key Usage panel, then revoke the
old key. Revocation takes effect within 60 seconds globally.

## OAuth 2.0

ACME implements the authorization code flow with PKCE. Public clients must use PKCE;
the `client_secret` flow is available only to confidential clients registered as such.

- Authorization endpoint: `https://auth.acmedata.io/oauth/authorize`
- Token endpoint: `https://auth.acmedata.io/oauth/token`

Access tokens are JWTs valid for 60 minutes. Refresh tokens are valid for 30 days and
are single-use: each refresh returns a new refresh token and invalidates the previous
one. Reusing a consumed refresh token is treated as a compromise indicator and revokes
the entire token family.

## Scopes

Scopes are granular and additive. The commonly used set is:

- `datasets:read` -- list and describe datasets
- `datasets:write` -- create and update datasets
- `datasets:purge` -- permanently delete datasets and records
- `records:write` -- append records
- `query:execute` -- run SQL queries
- `admin:members` -- manage project membership

`datasets:purge` and `admin:members` are considered privileged and cannot be granted to
sandbox keys.

## Failure modes

A missing or malformed `Authorization` header returns `401 UNAUTHENTICATED`. A valid
credential lacking the required scope returns `403 INSUFFICIENT_SCOPE`, and the error
message names the specific scope required. A revoked key returns `401 KEY_REVOKED`.
