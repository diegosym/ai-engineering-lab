# Authentication and Token Management

The Identity Service issues credentials to two kinds of caller: human-facing
integrations and the gateways themselves. This document describes both.

## Credential Types

| Type | Holder | Form |
|---|---|---|
| Tenant access token | Dashboards and integrations | Short-lived bearer token |
| API key | Long-running integrations | Static secret, one per client |
| Gateway device credential | CG-200 hardware | Per-device certificate |

Bearer tokens are presented to the Identity Service for validation on each
request; API keys are validated at the API edge.

## Token Lifetime

- Access token: **1 hour**
- Refresh grant: **30 days**
- Device certificate: **5 years**

An expired access token is rejected with 401. Clients refresh proactively,
typically at the halfway point of the token lifetime.

## Credential Rotation

Tenant access credentials are **rotated every 90 days**. Rotation issues a new
secret and keeps the previous one valid for an overlap window of 24 hours so
deployed clients can pick up the change without downtime.

Rotation is performed by the tenant administrator from the management console.
Automatic rotation is not enabled by default; tenants may schedule it once per
quarter or per year, but the default cadence remains every 90 days.

Gateway device certificates are renewed by the Deployer during scheduled
maintenance and do not follow the tenant rotation schedule.

## Scopes

- `read:series` — query timeseries data
- `write:series` — submit readings
- `admin:tenants` — manage tenant configuration

Tokens carry only the scopes granted to the issuing client. Scope changes take
effect on the next token issue, not on the current one.

## Identity Endpoint Limits

Validation and issuance requests against the Identity Service are limited to
**60 requests per minute per tenant**. This is deliberately much tighter than
the public API limit, because validation is CPU-bound signature checking.

Exceeding the identity limit returns 429 with a retry hint; clients back off
using the uplink retry schedule.

## Failure Modes

- Unknown issuer → 401, no detail leaked
- Expired token → 401 with `error=token_expired`
- Revoked credential → 401 immediately, propagation under 5 seconds
- Identity Service unreachable → API edge fails closed; requests are rejected
  rather than admitted unvalidated
