# Uplink Networking and Retry Policy

This document defines how a gateway reaches the cloud, how long it waits, and
what it does when an attempt fails. It is the authoritative source for retry
behaviour.

## Connection Model

The gateway opens a mutually authenticated TLS session to the uplink endpoint
and publishes batches over MQTT. Sessions are long-lived; the gateway
reconnects only after a session ends or is deemed stale.

Endpoint addressing, certificate provisioning, and DNS failover are managed
centrally and pushed as configuration.

## Retry Policy

Failed publish attempts are retried with **exponential backoff**:

- initial delay **1 second**
- multiplier **×2** per attempt
- jitter of **±20%** applied to every delay
- maximum **5 attempts** per batch

After the fifth failed attempt the batch is **not discarded**: it returns to
the local queue and is eligible for retransmission when a healthy session
returns. Backoff counters reset once a publish is acknowledged.

## Timeouts

| Timer | Value |
|---|---|
| TCP/TLS connection timeout | 30 seconds |
| Publish acknowledgement wait | 10 seconds |
| Session idle before health probe | 120 seconds |

The 30-second connection timeout applies only to establishing a session; it is
unrelated to how often queued data is flushed.

## Failure Classification

Retryable:

- connection refused or reset
- timeouts
- server-side (5xx) failures
- 429 responses carrying a retry hint

Not retryable:

- 401 and 403 responses — credential problems, see the authentication document
- 400 malformed payload
- 413 oversized batch

## Interaction with Rate Limits

A 429 from the API edge pauses the uplink for the advertised interval before
the next attempt. This pause is separate from the backoff schedule and is not
counted as one of the five attempts.
