# Cirrus API — Rate Limits

The Cirrus API throttles every client to protect shared capacity. This
document is the authoritative source for those limits.

## Default Limits

| Scope | Limit |
|---|---|
| Per API key | 600 requests per minute |
| Per-key burst bucket | 100 requests |
| Per tenant, aggregate | 2,000 requests per minute |
| Concurrent connections per key | 20 |

The burst bucket refills continuously at a rate of 10 requests per second. A
request is admitted when the bucket holds one token; otherwise it is rejected
with 429.

Limits are evaluated per API key first and per tenant second, so one noisy key
can be throttled without affecting the rest of the tenant.

## Throttled Responses

A rejected request receives:

```
HTTP/1.1 429 Too Many Requests
Retry-After: 12
X-RateLimit-Limit: 600
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 1712345678
```

`Retry-After` is expressed in seconds. Clients are expected to honour it
rather than retry immediately.

## Read Versus Write

Read endpoints count fully against the limit. Export endpoints, which stream
large results, count as ten requests each.

## Exemptions

Service tokens issued for internal components are exempt from the per-key
limit but still count against the tenant aggregate. Exemptions are granted by
configuration, never by a request header.

## Changing Limits

Limits are versioned with the API. A change is announced one release in
advance and applies to new keys immediately and to existing keys at their next
rotation.
