# Long Section Fixture

Intro paragraph before the long section, used to verify preamble handling.

## Endless Detail

The first paragraph of the long section describes connection handling in
enough prose to occupy meaningful space, covering retries, timeouts, and the
conditions under which a request is considered failed rather than merely slow.

The second paragraph continues the discussion with backoff schedules, jitter
ranges, and the number of attempts permitted before a batch returns to the
local queue for later retransmission over a healthy session.

The third paragraph shifts attention to classification of failures, noting
which status codes are retryable, which are permanent, and why credential
problems must never be retried blindly by an automated client.

The fourth paragraph explains how pause hints from throttling responses
interact with the backoff schedule, and clarifies that such pauses are not
counted among the permitted attempts for a given batch of readings.

The fifth paragraph discusses observability: which counters and histograms
are emitted, how a fleet-wide retry storm appears on a dashboard, and what
an on-call engineer should check first when the pattern emerges at dawn.

The sixth and final paragraph wraps up with maintenance guidance, including
how defaults are versioned, where they are documented, and the review process
applied whenever a tuning parameter is proposed for change.

## Short Tail

Small closing section that must never receive overlap from the long section.
