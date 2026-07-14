# Stage 2 — Reroute Rules

If any taskcard scores below 4/5 on any dimension in Stage 3:

1. Do not average the score up or accept a below-4 dimension as "close enough."
2. Do not silently re-narrate the same evidence with more confident language.
3. Re-open the taskcard's `machine_state` from `CLOSED`/`completed_verified`
   back to `open`, with the specific failing dimension(s) recorded.
4. Identify whether the gap is: (a) missing evidence that already exists but
   wasn't captured (→ capture it, no code change), (b) a real implementation
   gap (→ new sub-taskcard, code change required), or (c) a real regression
   (→ STOP, this becomes a blocking finding, escalate before continuing any
   other lane).
5. Re-score only after the gap is closed with new evidence — never re-score
   from narrative alone.

## Application
This rule set is defined here in Stage 2 for Stage 3 to apply. Whether it
was invoked (and for which taskcard/dimension, if so) is recorded in
`stage3-execution/`, not here — this file must not be back-filled with a
Stage 3 outcome claim before Stage 3 actually runs.
