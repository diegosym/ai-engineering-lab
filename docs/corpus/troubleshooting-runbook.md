# Troubleshooting Runbook

Procedures for diagnosing common Cirrus faults in the field. Follow the
sections in order; most incidents resolve at the first two steps.

## Common Symptoms

| Symptom | Likely area |
|---|---|
| No readings for one building | Gateway power or network |
| Gaps in one subsystem only | Sensor wiring or channel configuration |
| API returns 429 constantly | Client not honouring retry hints |
| API returns 401 after a deploy | Credential rotation overlap missed |
| Dashboard latency spikes | Query range crossing the retention boundary |

## First Response

1. Check Fleet Status in Pulse for the affected gateway.
2. Confirm the gateway is reporting a firmware version.
3. If the gateway is silent, check power and link lights.
4. If it is reporting but data is missing, check channel configuration.

Silence longer than 30 minutes raises an informational ticket automatically;
there is no need to open one manually.

## Diagnosing Missing Data

Compare the gateway's local queue state against what the store received. If
the queue is draining but rows are absent, validation is rejecting the batch —
check the batch rejection counter in Pulse for the reason class.

Never ask a customer to power-cycle a gateway during business hours unless
readings have been absent for more than two hours; a reboot discards
in-progress queue state that has not yet been flushed.

## Escalation

- Field hardware issues → building facilities contact
- Pipeline issues past 30 minutes → on-call primary
- Suspected data loss → on-call primary and engineering lead immediately

## Deprecated: Legacy Rollback Procedure (superseded)

> **DEPRECATED — do not follow this section.**
> It described the pre-2024 rollout scheme and is retained only for historical
> reference. Current rollback behaviour, including batch size and soak
> intervals, is defined in the deployment and rollout documentation.

The legacy procedure instructed operators to redeploy the previous artifact in
batches of 10 gateways with a 30-minute soak. Those batch and soak parameters
are no longer in effect.

## Known Limitations

- The runbook does not cover store-level corruption; escalate instead.
- Sensor calibration procedures live in the installation guide.
