# Deployment and Rollout

All changes to configuration and firmware reach gateways through the Deployer.
This document defines the current rollout procedure and is the source of truth
for rollout parameters.

## Environments

- **Staging** — internal fleet, mirrors production configuration
- **Production** — customer fleet

Nothing ships to production without passing staging for at least 24 hours.

## Canary

A change first reaches **5% of gateways**, selected across at least three
tenants. The canary runs for **30 minutes** with automatic halt on any critical
alert from Pulse.

## Staged Rollout

After the canary, the change advances in **batches of 25 gateways**, with a
**10-minute soak** between batches. A batch is considered healthy when it
reports expected telemetry and raises no warning-severity alerts.

The full fleet therefore progresses 25 gateways at a time; there is no
single-step full-fleet deployment outside of emergency changes.

## Rollback

Rollback re-promotes the previously known-good artifact through the same
batching scheme, in reverse order. Gateways retain the last two firmware
images locally, so a rollback needs no download for most devices.

Emergency changes skip the canary but never skip batching.

## Versioning

Every deployed artifact carries a semantic version and a content hash. The
gateway records the version it is running in each batch header, which lets
Pulse report fleet version distribution directly.

## Configuration Drift

The Deployer reconciles gateways every 6 hours. A gateway that has drifted
from desired state is reported and corrected at the next reconciliation, not
immediately, so a manual field fix survives a working day before being
overwritten.
