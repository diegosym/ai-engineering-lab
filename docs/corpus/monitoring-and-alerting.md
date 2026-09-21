# Monitoring and Alerting (Pulse)

Pulse is the observability layer for Cirrus. It collects metrics from every
component, evaluates alert rules, and notifies the on-call engineer.

## Metrics

Each component exposes a small, fixed metric set:

- request and batch counters
- latency histograms
- queue depth gauges
- error counters by class

Metric names are namespaced by component, for example
`ingest_write_latency_seconds`.

## Service Level Objectives

| Objective | Target |
|---|---|
| API availability | 99.5% per month |
| Ingest success rate | 99.9% of accepted batches |
| Query latency (p95) | Under 300 ms |

Availability is measured as successful responses divided by total requests,
excluding requests rejected for throttling or bad credentials.

The 99.5% monthly availability target leaves an error budget of roughly 3 hours
and 39 minutes of failed requests per month. When the budget is exhausted,
feature work pauses and reliability work takes priority.

## Alert Rules and Thresholds

| Condition | Severity | Action |
|---|---|---|
| Ingest error rate above 1% for 5 minutes | critical | Page on-call |
| Queue depth above 100,000 for 10 minutes | warning | Ticket |
| Availability below 99.5% month-to-date | warning | Notify lead |
| Certificate expiring within 14 days | warning | Ticket |
| Single gateway silent for 30 minutes | info | Ticket |

Alerts fire only after the condition holds for the stated window; single
spikes never page anyone.

## Dashboards

Three standard dashboards exist: Ingest Health, API Health, and Fleet Status.
Dashboards are read-only views over the same metric store that feeds alerting,
so a dashboard and an alert never disagree about the underlying number.

## On-call Rotation

A single primary engineer carries the pager for one week, with a named backup.
Escalation proceeds from primary to backup to the engineering lead after 15
minutes without acknowledgement.
