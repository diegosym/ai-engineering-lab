# Time-Series Storage and Retention

The Time-Series Store holds every accepted reading, plus rollups derived from
it. This document defines what is kept, for how long, and what happens when a
window closes.

## Data Model

Readings are written as raw samples keyed by tenant, series, and timestamp.
Series are grouped by building, subsystem, and channel.

Rollups are computed continuously from raw samples:

- **15-minute rollups** — mean, min, max, and count per series
- **hourly rollups** — derived from the 15-minute rollups
- **daily rollups** — derived from hourly rollups

Rollups are computed idempotently, so reprocessing a window produces the same
values.

## Retention Windows

| Tier | Retention | Purpose |
|---|---|---|
| Raw samples | 35 days | High-resolution investigation and replay support |
| 15-minute rollups | 400 days | Trending and year-over-year comparison |
| Hourly rollups | 3 years | Long-range reporting |
| Daily rollups | 10 years | Compliance and archival |

When a tier expires, rows are removed by the background compaction job; there
is no per-tenant override for raw samples. Tenants needing longer raw history
must export it through the API before the window closes.

## Deletion

Tenant-initiated deletion removes data immediately across all tiers and is
recorded in an audit log that contains no readings, only the scope and
timestamp of the request.

## Query Patterns

Point lookups and short ranges are served directly from raw samples. Ranges
wider than 35 days are served from rollups, and the API states explicitly
which tier answered each series.

Queries that span the boundary between raw and rolled-up data return both,
with the source tier marked per datapoint so callers can tell the difference.

## Capacity

Compaction runs nightly. Sustained ingest above the rated tenant limits
increases compaction time but does not block writes; capacity alerts are raised
by Pulse, not by the store itself.
