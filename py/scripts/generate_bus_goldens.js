#!/usr/bin/env node
/**
 * Generate parity goldens for the bus module by running skkuverse-server's
 * REAL transform code over its captured fixtures.
 *
 * Why this exists
 * ---------------
 * Bus is moving out of skkuverse-server into this repo. The migration's
 * actual correctness criterion is "the Python normaliser produces the same
 * bus_cache payload the TypeScript poller produced" — the server's API reads
 * those documents directly, so a difference breaks the app in a way no
 * crawler test would notice.
 *
 * The server's `__fixtures__/` hold raw UPSTREAM responses, not the
 * normalised payloads, so the expected values have to come from executing
 * the TypeScript. Transcribing it into this script by hand would only prove
 * that two hand-written implementations agree; requiring the compiled
 * services proves the port matches what actually ran in production.
 *
 * Nothing in skkuverse-server is modified. This reads its `dist/` and its
 * `__fixtures__/`, and writes only into this repo.
 *
 * Determinism
 * -----------
 * Both pollers read the wall clock (`moment()`), and both derive
 * `estimatedTime` and their staleness decisions from it. Each fixture
 * records the instant it was captured, so the clock is frozen to that
 * instant per replay — which is also what makes the goldens stable across
 * runs rather than drifting with the current date.
 *
 * State
 * -----
 * Both pollers carry state across ticks (HSSC's sticky event timestamps,
 * Jongro's per-station dwell clocks), so fixtures are replayed in
 * chronological order against ONE service instance per route. That is the
 * whole point: a per-file replay would exercise only the cold path and
 * would never catch a dwell-time bug.
 *
 * Usage
 * -----
 *     node py/scripts/generate_bus_goldens.js [--server <path>] [--days N]
 *
 * Output:
 *   py/tests/fixtures/bus/<api>/<date>.json  — real captures, in order
 *   py/tests/fixtures/bus/_dense/<api>.json  — see below
 *
 * The dense replays
 * -----------------
 * The captures are 30 minutes apart. Jongro's dwell clock expires a
 * station's recorded time after 10 minutes, so EVERY replayed tick finds
 * the previous record already expired, re-records it, and reports
 * estimatedTime 0 — the accumulation path, which is the normal case at the
 * real 40s cadence, is never reached. A parity corpus with a hole exactly
 * where the trickiest logic lives is not much of a proof.
 *
 * So one real capture is additionally replayed against a SYNTHETIC tick
 * schedule at the production interval, long enough to cross the expiry.
 * Same real transform code, same real upstream payload; only the clock is
 * arranged. That exercises accumulate-then-expire, which is what the
 * Python port most needs held to.
 */

"use strict";

const fs = require("node:fs");
const path = require("node:path");

// ── paths ────────────────────────────────────────────────────────────────
const argv = process.argv.slice(2);
function argValue(flag, fallback) {
  const i = argv.indexOf(flag);
  return i >= 0 && argv[i + 1] ? argv[i + 1] : fallback;
}

const CRAWLER_ROOT = path.resolve(__dirname, "..", "..");
const SERVER_ROOT = path.resolve(
  argValue("--server", path.join(CRAWLER_ROOT, "..", "skkuverse-server")),
);
const FIXTURES_IN = path.join(SERVER_ROOT, "__fixtures__");
const GOLDENS_OUT = path.join(CRAWLER_ROOT, "py", "tests", "fixtures", "bus");
const MAX_DAYS = Number(argValue("--days", "0")) || Infinity;

function die(message) {
  console.error(`error: ${message}`);
  process.exit(1);
}

if (!fs.existsSync(FIXTURES_IN)) {
  die(`no __fixtures__ at ${FIXTURES_IN} (pass --server <path>)`);
}
const DIST = path.join(SERVER_ROOT, "dist", "src");
if (!fs.existsSync(DIST)) {
  die(`no dist/ at ${DIST} — run \`npm run build\` in skkuverse-server first`);
}

// ── the server's config module exits the process on a missing variable, and
//    it is imported transitively by the pollers. None of these values are
//    used: every network call is stubbed below. They exist only to get past
//    the fail-loud check. Deliberately obvious placeholders so that a real
//    request escaping the stub would fail rather than reach an upstream.
const PLACEHOLDER_ENV = {
  MONGO_URL: "mongodb://127.0.0.1:27017/golden-generator-never-connects",
  API_HSSC_NEW_PROD: "https://invalid.example/never-called",
  API_STATION_HEWA: "https://invalid.example/never-called",
  SEOUL_BUS_SERVICE_KEY: "placeholder%2Fkey",
  NAVER_MAP_STYLE_ID: "placeholder",
  NAVER_API_KEY_ID: "placeholder",
  NAVER_API_KEY: "placeholder",
  MONGO_BUILDING_DB_NAME: "placeholder",
  MONGO_AD_DB_NAME: "placeholder",
  MONGO_NOTICES_DB_NAME: "placeholder",
  NOTICES_SERVICE_START_DATE: "2026-03-09",
  FCM_FUNCTION_URL: "https://invalid.example/never-called",
  FCM_API_KEY: "placeholder",
  INTERNAL_DISPATCH_TOKEN: "placeholder",
  NODE_ENV: "test",
  LOG_LEVEL: "silent",
};
for (const [key, value] of Object.entries(PLACEHOLDER_ENV)) {
  if (!process.env[key]) process.env[key] = value;
}

// ── frozen clock ─────────────────────────────────────────────────────────
// moment() bottoms out in `new Date()` / Date.now(), so replacing the global
// is enough to make both pollers' time-dependent maths reproducible.
const RealDate = Date;
let frozenMs = RealDate.now();

class FrozenDate extends RealDate {
  constructor(...args) {
    if (args.length === 0) super(frozenMs);
    else super(...args);
  }
  static now() {
    return frozenMs;
  }
}
global.Date = FrozenDate;

function freezeAt(isoTimestamp) {
  const ms = RealDate.parse(isoTimestamp);
  if (Number.isNaN(ms)) die(`unparseable fixture timestamp: ${isoTimestamp}`);
  frozenMs = ms;
}

// ── stubs ────────────────────────────────────────────────────────────────
// axios is replaced wholesale: the pollers must never reach a network, and a
// request for a URL we did not script is a bug in this generator rather than
// something to paper over with an empty response.
// require.resolve, not require(<dir>): resolving the directory goes through
// the package "exports" map and can hand back a DIFFERENT module instance
// than the one the compiled pollers get, in which case the adapter below is
// installed on an axios nobody calls and every request escapes to the network.
const axiosModule = require(require.resolve("axios", { paths: [SERVER_ROOT] }));
const axios = axiosModule.default || axiosModule;
// `undefined` means "nothing scripted" — distinct from a capture whose
// data really is null/absent, which several transport-error captures are.
let scriptedResponse = undefined;

// Swapped at the ADAPTER, not by reassigning axios.get: the module object is
// frozen, and the adapter is the documented seam anyway. Everything above it
// — interceptors, response transforms — still runs, so the pollers see the
// same shape they see in production.
axios.defaults.adapter = async (requestConfig) => {
  if (scriptedResponse === undefined) {
    throw new Error(
      `axios called for ${requestConfig.url} with no scripted response`,
    );
  }
  return {
    data: scriptedResponse,
    status: 200,
    statusText: "OK",
    headers: {},
    config: requestConfig,
  };
};

// The poller constructors want a registry and a cache. Neither is exercised:
// registerPoller is what onModuleInit would call (we never call it), and the
// cache is where the payload we are here to capture gets handed over.
class CapturingCache {
  constructor() {
    this.writes = [];
  }
  async write(key, data) {
    this.writes.push({ key, data });
  }
}
const NOOP_REGISTRY = { registerPoller() {} };

// ── the real transforms ──────────────────────────────────────────────────
const { HsscPollerService } = require(
  path.join(DIST, "bus", "fetchers", "hssc.poller.service.js"),
);
const { JongroPollerService } = require(
  path.join(DIST, "bus", "fetchers", "jongro.poller.service.js"),
);
// `jongroRoutes` is built and deep-frozen at import time, and its loader
// fail-loud validates the routes JSON and the service key format — so a
// malformed registry stops this generator here rather than producing
// plausible-looking goldens.
const { jongroRoutes: ROUTES } = require(
  path.join(DIST, "bus", "registry", "jongro-registry.js"),
);

// ── replay ───────────────────────────────────────────────────────────────
function listDays() {
  return fs
    .readdirSync(FIXTURES_IN)
    .filter((name) => /^\d{4}-\d{2}-\d{2}$/.test(name))
    .sort()
    .slice(0, MAX_DAYS);
}

function readCaptures(day, api) {
  const dir = path.join(FIXTURES_IN, day, api);
  if (!fs.existsSync(dir)) return [];
  return fs
    .readdirSync(dir)
    .filter((f) => f.endsWith(".json"))
    .sort() // filenames are HHmm, so lexical order IS chronological
    .map((f) => JSON.parse(fs.readFileSync(path.join(dir, f), "utf8")));
}

/**
 * Replay one API's captures for one day through a fresh service instance.
 *
 * `drive` runs one tick: it is handed the capture and must leave whatever
 * the poller wrote in the cache. Returning the cache write rather than the
 * service's getter is deliberate — the cache document is the contract the
 * server actually reads.
 */
async function replayDay(captures, { makeService, drive, cacheKey }) {
  const cache = new CapturingCache();
  const service = makeService(cache);
  const out = [];
  for (const capture of captures) {
    freezeAt(capture.timestamp);
    scriptedResponse = "data" in capture ? capture.data : null;
    const before = cache.writes.length;
    await drive(service);
    scriptedResponse = undefined; // a second request per tick must not
                                  // silently reuse this one's payload
    // The pollers write the cache fire-and-forget (`.catch()` without an
    // await), so the promise may not have settled when the method returns.
    // One turn of the microtask queue is enough — CapturingCache.write
    // resolves immediately.
    await new Promise((resolve) => setImmediate(resolve));
    const written = cache.writes
      .slice(before)
      .filter((w) => w.key === cacheKey);
    out.push({
      at: capture.timestamp,
      // No write is meaningful, not missing: an upstream error or an
      // unusable header code leaves the previous document in place, and the
      // Python port has to make the same choice.
      payload: written.length ? written[written.length - 1].data : null,
    });
  }
  return out;
}

/**
 * Derived rather than a hardcoded date list, so it keeps working when the
 * fixture corpus changes.
 */
const _listDayCache = new Map();
function listDayIsInteresting(day, days, api) {
  if (day === days[0] || day === days[days.length - 1]) return true;
  let errorDays = _listDayCache.get(api);
  if (!errorDays) {
    errorDays = new Set(
      days.filter((d) =>
        readCaptures(d, api).some((c) => {
          const cd = c.data?.msgHeader?.headerCd;
          const items = c.data?.msgBody?.itemList;
          return (
            (cd && !(cd === "0" || cd === "4")) ||
            !Array.isArray(items) ||
            // [] and null are different answers downstream (write an empty
            // list vs write nothing), so a day whose only distinguishing
            // feature is an empty itemList has to survive the sampling.
            // `!items` would be false here, since ![] is false in JS.
            items.length === 0
          );
        }),
      ),
    );
    _listDayCache.set(api, errorDays);
  }
  return errorDays.has(day);
}

function writeGolden(api, day, rows) {
  const dir = path.join(GOLDENS_OUT, api);
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(
    path.join(dir, `${day}.json`),
    JSON.stringify(rows, null, 2) + "\n",
  );
}

async function main() {
  const days = listDays();
  if (days.length === 0) die(`no dated directories under ${FIXTURES_IN}`);
  console.log(`replaying ${days.length} day(s) from ${FIXTURES_IN}`);

  let written = 0;

  for (const day of days) {
    // ── HSSC ──
    const hssc = readCaptures(day, "hssc");
    if (hssc.length) {
      const rows = await replayDay(hssc, {
        cacheKey: "hssc",
        makeService: (cache) => new HsscPollerService(NOOP_REGISTRY, cache),
        drive: (svc) => svc.updateHSSCBusList(),
      });
      writeGolden("hssc", day, rows);
      written += 1;
    }

    // ── Jongro, per route and per direction ──
    for (const route of ROUTES) {
      for (const [kind, api] of [
        ["list", `jongro${route.code}_list`],
        ["loc", `jongro${route.code}_loc`],
      ]) {
        const captures = readCaptures(day, api);
        if (!captures.length) continue;
        // The list transform is a stateless field rename, so consecutive
        // ticks prove nothing that one tick does not — and keeping all 17
        // days of it costs ~9.5MB of committed JSON, almost all of it
        // distinct `eta` strings that are copied through untouched.
        // Keep the days that carry something: the first and last, and any
        // day where the upstream errored (a null payload, which is the one
        // list-side branch worth pinning).
        if (kind === "list" && !listDayIsInteresting(day, days, api)) continue;
        const rows = await replayDay(captures, {
          cacheKey:
            kind === "list"
              ? `jongro_stations_${route.code}`
              : `jongro_locations_${route.code}`,
          makeService: (cache) =>
            new JongroPollerService(NOOP_REGISTRY, cache, ROUTES),
          // `private` in TypeScript is erased at runtime; these are the
          // real methods the 40s tick calls, with the registry-composed
          // URLs the stubbed axios ignores.
          drive: (svc) =>
            kind === "list"
              ? svc.updateJongroBusList(route.listUrl, route.code)
              : svc.updateJongroBusLocation(route.locUrl, route.code),
        });
        writeGolden(api, day, rows);
        written += 1;
      }
    }
  }

  written += await denseReplays(days);
  console.log(`wrote ${written} golden file(s) to ${GOLDENS_OUT}`);
}

/**
 * Replay one real capture at the production tick interval.
 *
 * Deliberately NOT synthetic data: the payload is a real upstream response,
 * and the transform is the real compiled service. Only the tick schedule is
 * arranged, because the 30-minute capture cadence cannot reach the dwell
 * logic the 40-second one lives in.
 */
async function denseReplays(days) {
  const SPECS = [
    { api: "hssc", intervalMs: 10_000, ticks: 40 },
    ...ROUTES.flatMap((route) => [
      {
        api: `jongro${route.code}_loc`,
        intervalMs: 40_000,
        // 40 ticks x 40s = ~27 minutes: past the 10-minute dwell expiry
        // twice, so both accumulation and the reset are covered.
        ticks: 40,
        route,
        kind: "loc",
      },
    ]),
  ];

  let written = 0;
  for (const spec of SPECS) {
    const makeService = (cache) =>
      spec.kind === "loc"
        ? new JongroPollerService(NOOP_REGISTRY, cache, ROUTES)
        : new HsscPollerService(NOOP_REGISTRY, cache);
    const drive = (svc) =>
      spec.kind === "loc"
        ? svc.updateJongroBusLocation(spec.route.locUrl, spec.route.code)
        : svc.updateHSSCBusList();
    const cacheKey =
      spec.kind === "loc" ? `jongro_locations_${spec.route.code}` : "hssc";

    const capture = await findProducingCapture(days, spec.api, {
      makeService,
      drive,
      cacheKey,
    });
    if (!capture) {
      console.warn(`  dense: no capture for ${spec.api} yields items, skipped`);
      continue;
    }
    const base = RealDate.parse(capture.timestamp);
    const synthetic = Array.from({ length: spec.ticks }, (_, i) => ({
      timestamp: new RealDate(base + i * spec.intervalMs).toISOString(),
      data: capture.data,
    }));

    const rows = await replayDay(synthetic, { cacheKey, makeService, drive });

    const dir = path.join(GOLDENS_OUT, "_dense");
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(
      path.join(dir, `${spec.api}.json`),
      JSON.stringify(
        {
          source: capture.timestamp,
          intervalMs: spec.intervalMs,
          // The capture's own payload is embedded, not just referenced.
          // These are the ONLY parity goldens that can run without a
          // checkout of skkuverse-server, and they cover the stateful
          // paths — which is exactly what CI would otherwise skip.
          capture: capture.data,
          rows,
        },
        null,
        2,
      ) + "\n",
    );
    written += 1;
  }
  return written;
}

/**
 * The first capture that actually PRODUCES items, decided by running the
 * transform rather than by looking at the raw response.
 *
 * The difference matters for HSSC: its upstream never returns an empty
 * array — it pins the last six items indefinitely — so "raw data is
 * non-empty" is true around the clock and says nothing about whether buses
 * were running. Only the stale filter knows, and only the real transform
 * runs it.
 */
async function findProducingCapture(days, api, opts) {
  for (const day of days) {
    for (const capture of readCaptures(day, api)) {
      const [row] = await replayDay([capture], opts);
      if (row.payload && row.payload.length > 0) return capture;
    }
  }
  return null;
}

main().catch((err) => die(err && err.stack ? err.stack : String(err)));
