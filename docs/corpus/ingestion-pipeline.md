# Ingestion Pipeline

The Ingest Service turns arriving batches into durable rows. It is the only
component permitted to write to the Time-Series Store.

## Stages

1. **Receive** — accept the batch on the uplink listener.
2. **Validate** — check schema, tenant, and timestamp sanity.
3. **Normalize** — resolve channel identifiers to series identifiers.
4. **Write** — append to the store in a single transaction per batch.

A batch failing validation is rejected whole; partial acceptance is not
supported.

## Batching and Flushing

The gateway ships a batch when either condition is met first:

- the batch reaches **500 samples**, or
- the flush interval of **45 seconds** elapses

The flush interval is deliberately longer than the sampling interval so that
steady-state traffic stays well under connection limits. Low-traffic channels
therefore appear in the pipeline at a coarser granularity than they are
sampled.

## Buffering and Replay

Queued readings are retained on the gateway for **24 hours**. When the uplink
returns after an outage, the gateway replays the queue oldest-first, in the
same batch format as live traffic.

Readings older than the replay window are dropped locally rather than shipped
in a burst. Recovering older data depends on what the store still holds; see
the retention documentation.

## Ordering and Idempotency

Within a series, writes are ordered by sample timestamp. Every batch carries a
unique identifier, so a re-sent batch is applied once — duplicate identifiers
are acknowledged without rewriting data.

## Acknowledgement and Re-delivery

The Ingest Service acknowledges only after the transaction commits. An
unacknowledged batch is re-delivered by the transport layer up to three times
before the gateway treats it as failed and re-queues it locally. This
re-delivery counter is a transport detail and is distinct from the uplink
retry schedule.

## Backpressure

When write latency exceeds 2 seconds, the Ingest Service stops accepting new
batches on the affected shard and lets the queue absorb pressure. Backpressure
signals are surfaced as metrics rather than as errors to the gateway.
