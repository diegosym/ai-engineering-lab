# Cirrus Gateway CG-200 — Hardware and Sampling

The CG-200 is the edge device installed in each monitored building. It reads
sensor values, timestamps them, queues them, and hands them to the uplink.

## Sensor Interfaces

- 8× one-wire temperature and humidity probes
- 4× 4–20 mA analogue inputs for power and current transformers
- 2× RS-485 buses for third-party meters
- 1× dry-contact input for door and breaker state

All inputs are electrically isolated in pairs. Wiring conventions are
documented in the installation guide, not here.

## Sampling Behaviour

Each configured channel is sampled every **15 seconds**. Sampling is driven by
a hardware timer, so a slow or saturated uplink never changes the sampling
rate. A missed sample is recorded as a gap rather than backfilled with an
estimate.

Channels may be grouped into sampling profiles (fast, normal, audit), but the
default profile is normal, which uses the 15-second interval above.

## Local Storage

The gateway has 8 GB of flash dedicated to queued readings. Flash endurance is
sized for the expected write volume over a five-year service life. Queue
eviction policy and replay behaviour are described in the ingestion
documentation.

## Timekeeping

The gateway runs NTP synchronisation and holds time within 50 ms of stratum-2
references. If time drift exceeds 1 second, the gateway flags the next batch
so downstream systems can adjust timestamps.

## Power and Enclosure

- Input: 24 V DC or Power-over-Ethernet
- Typical draw: 9 W
- Operating range: −10 °C to 50 °C
- DIN-rail mount, IP20 rating

## Firmware

Firmware images are signed and versioned. The gateway reports its firmware
version in every batch header. Firmware rollout follows the staged procedure
described in the deployment documentation.
