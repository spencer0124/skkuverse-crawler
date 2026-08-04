# Bus parity goldens

Generated, not hand-written. **Do not edit these by hand** — regenerate:

```bash
cd skkuverse-server && npm run build     # only if dist/ is stale
node py/scripts/generate_bus_goldens.js  # from the crawler repo root
```

## What they are

Bus is moving out of `skkuverse-server` into this repo. The migration's real
correctness criterion is that the Python normaliser produces the **same
`bus_cache` payload the TypeScript poller produced** — the server's API reads
those documents directly, so a difference breaks the app in a way no crawler
test would catch.

The server's `__fixtures__/` hold raw *upstream* responses, not normalised
payloads, so the expected values come from **executing the server's compiled
transforms** over them. Transcribing the TypeScript by hand would only prove
that two hand-written implementations agree.

Each file is an array of `{ at, payload }` in capture order. `payload: null`
means the poller wrote nothing that tick — an upstream error or an unusable
header code leaves the previous document in place, and the Python port must
make the same choice. `payload: []` is different: it means the poller wrote an
empty list, which is how "no buses are running" is expressed.

## Why the days differ per API

| directory | days | why |
|---|---|---|
| `hssc/`, `jongro*_loc/` | all 17 | **stateful** — sticky event timestamps and per-station dwell clocks chain across ticks, so continuity is the point |
| `jongro*_list/` | 3 | **stateless** field rename. Consecutive ticks prove nothing one tick does not, and all 17 days cost ~9.5MB of committed JSON that is mostly distinct `eta` strings copied through untouched. The generator keeps the first day, the last day, and any day the upstream errored — derived, so it survives a change to the corpus |

## What the corpus does NOT cover

Worth stating, because a corpus this large invites the assumption that it
covers everything:

- **Upstream error codes.** Every one of the 3,091 captured Jongro ticks
  carries `headerCd` `"0"` or `"4"`. `Outcome.UPSTREAM_ERROR` has no parity
  coverage at all and is pinned only by hand-written unit tests. That gap
  is not academic — it hid a real divergence, where a falsy `headerCd`
  made the port refuse to write while the TypeScript published normally.
- **Non-integer `seq`, duplicate `(line_no, stop_no)`, sub-second
  timestamps.** All absent from the captures, all places the two
  implementations can disagree. See `tests/bus/test_pure_layer.py`,
  `TestDivergencesFoundByReview`.

The captures record what the upstreams happened to send over 17 days, not
what they are capable of sending.

## `_dense/` — the part the real captures cannot reach

Captures are 30 minutes apart. Jongro's dwell clock expires a station's
recorded time after **10 minutes**, so every replayed tick finds the previous
record already expired and reports `estimatedTime: 0`. The accumulation
path — normal at the real 40s cadence — is never exercised. A parity corpus
with a hole exactly where the trickiest logic lives is not much of a proof.

So one real capture is replayed against a **synthetic tick schedule** at the
production interval, long enough to cross the expiry twice. Same real
transform, same real upstream payload; only the clock is arranged.

Each `_dense` file embeds the capture it replays, so **these are the only
parity tests that run without a checkout of `skkuverse-server`** — which
means they are the only ones CI runs. They were chosen for that on
purpose: they cover the stateful paths, which is where a port is most
likely to be subtly wrong.

- `hssc.json` — 10s ticks. `estimatedTime` climbs by 10 per tick as the sticky
  timestamp is reused, then items drop out when the stale filter catches them.
- `jongro0*_loc.json` — 40s ticks. `estimatedTime` runs `0, 40, 80 … 600` and
  resets, which is the dwell expiry.

## Determinism

Both pollers read the wall clock and derive `estimatedTime` and their
staleness decisions from it, so the generator freezes `Date` to each capture's
recorded instant. Without that, everything older than the stale window is
filtered and every payload comes out empty — which is exactly what happened
the first time.
