# Cirrus Platform — Architecture Overview

Cirrus is a building energy-monitoring platform. It collects readings from
sensors installed throughout a building, transports them to a central
pipeline, stores them as time series, and exposes them to downstream consumers
through a versioned HTTP API.

This document describes the system as a whole. Detailed behaviour lives in the
subsystem documents.

## Components

| Component | Role |
|---|---|
| Cirrus Gateway (CG-200) | Edge device that samples sensors and buffers readings locally |
| Uplink | TLS connection carrying batches from a gateway to the cloud |
| Ingest Service | Validates, batches, and writes incoming readings |
| Time-Series Store | Durable storage for raw readings and rollups |
| Cirrus API | Public read API for dashboards and integrations |
| Identity Service | Issues and rotates access tokens |
| Pulse | Metrics, dashboards, and alerting |
| Deployer | Ships configuration and firmware in controlled stages |

## Data Flow

1. A gateway samples each sensor on a fixed interval.
2. Readings accumulate in a local queue.
3. The gateway opens an uplink and ships batches to the Ingest Service.
4. The Ingest Service validates the payload and writes it to the store.
5. The Cirrus API serves queries against the store.
6. Pulse observes every stage and raises alerts when a stage misbehaves.

Transport-level failures are handled by retries at the uplink. Queue pressure
and partial writes are handled by buffering inside the Ingest Service.

## Multi-tenancy

Each customer deployment is a **tenant**. A tenant owns gateways, API keys,
and retention settings. Data is isolated per tenant at the store and API
layers.

## Glossary

- **Sample** — one reading from one sensor at one instant.
- **Batch** — a group of samples sent together over the uplink.
- **Flush** — the act of sending a queued batch before it is full.
- **Tenant** — one customer deployment and everything it owns.
- **Token** — a short-lived credential presented to the Identity Service.
- **Rate limit** — a per-key ceiling on request volume.
- **Retry** — a repeated attempt at an operation that failed transiently.
- **Rollup** — samples aggregated into a coarser time bucket.

## Design Principles

- Prefer predictable behaviour over clever behaviour.
- Every subsystem degrades independently; no single failure stops collection.
- Defaults are documented once, in one place, and versioned with the code.
