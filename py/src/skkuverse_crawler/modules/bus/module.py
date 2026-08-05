"""The three bus pollers as scheduled modules.

Snapshot archetype (adr-008 ①): one document per key, replaced wholesale.
There is no pagination, no per-item diff and no seen index — the entire
storage story is `SnapshotSink`, which wiring injects. These classes never
reach for it, and cannot: `modules/` may import neither `plugins/` nor
`shared.db`, which is what lets the same three objects run against a fake
sink in a test, against Mongo in production, and (via `cli.py`) against
nothing at all.

Everything stateful was already written as a pure function taking the
previous state as an argument (`hssc.normalize`, `jongro.normalize_loc`).
What lives here is the part that could not be: the instance that carries
that state between ticks, the HTTP client, and the translation from an
upstream answer into the core event vocabulary.

**The down-signal is one rule.** `source_down` is true exactly when the
tick emitted a hard failure — a fetch that raised, a payload that would
not parse, an upstream error code. It is NOT true for a tick that simply
had nothing to publish: Jongro's `headerCd "4"` arrives every night when
no bus is running, and counting that as a failure would page someone at
2am, daily, forever.

**Grace times are generous on purpose.** These modules fetch *current*
state, so a tick that starts late is not a tick that reads stale data —
the only thing worth preventing is pile-up, and `max_instances=1` +
`coalesce=True` already do that (the same guard as the TypeScript
poller's `inFlight` flag). The scheduler's ten-second default, applied to
a ten-second poller, would drop ticks whenever the event loop was busy.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from datetime import datetime, timezone
from typing import Any

import httpx

from ...core.events import (
    CrawlEvent,
    ItemCrawled,
    ItemFailed,
    ItemSkipped,
    ListFetchFailed,
    SourceFinished,
    SourceStarted,
)
from ...core.module import ModuleConfig
from ...core.ports import Sink, SourceSpec
from ...core.results import SourceResult
from ...core.runner import run_events
from ...shared.logger import get_logger
from . import campus_eta, hssc, jongro
from .client import UpstreamError, fetch_json
from .models import CacheSnapshot
from .registry import JongroRoute, load_routes, validate_service_key
from .sources import BusSource, CacheKey, document_id
from .time_ko import KoreanTimeFormatError

logger = get_logger("bus")

SinkFactory = Callable[[], Awaitable[Sink]]
ResultsHook = Callable[[list[SourceResult]], Awaitable[None]]
ClientFactory = Callable[[], httpx.AsyncClient]

# `article_no` on the generic failure events is an int, and these modules
# have no article numbers. adr-008 ③ deferred `article_no: int -> key: str`
# past 1.0 on the grounds that no consumer wanted it and the change has
# three stringify points that must agree forever. This constant is what
# that deferral costs, made visible in one place rather than sprinkled as
# a literal zero through five call sites.
NO_ITEM_NUMBER = 0


def _new_client() -> httpx.AsyncClient:
    return httpx.AsyncClient()


class _BusModule:
    """Tick scaffolding shared by the three pollers.

    Subclasses supply `source`, `source_name`, `config` and `_events`.

    The HTTP client is created once per instance and closed in
    `shutdown()`. A ten-second poller that built a client per tick would
    throw away every connection it opened, which is most of what it does.
    """

    source: BusSource
    source_name: str

    def __init__(
        self,
        *,
        sink_factory: SinkFactory,
        shadow_writes: bool = True,
        on_results: ResultsHook | None = None,
        client_factory: ClientFactory = _new_client,
    ) -> None:
        self._sink_factory = sink_factory
        self._shadow_writes = shadow_writes
        self._on_results = on_results
        self._client_factory = client_factory
        self._client: httpx.AsyncClient | None = None

    @property
    def config(self) -> ModuleConfig:  # pragma: no cover - subclass duty
        raise NotImplementedError

    async def run(self, now: datetime | None = None, **kwargs: Any) -> dict:
        """One tick.

        ``now`` is an argument for the same reason the normalisers take one:
        every derived value here — dwell times, stale filtering, the
        published `eventDate` — is a function of the current instant, and a
        module that read the clock internally could only be tested by
        moving the clock. The scheduler calls this with no arguments.
        """
        sink = await self._sink_factory()
        await sink.prepare(
            SourceSpec(source_id=self.source.value, name=self.source_name)
        )
        result = SourceResult(
            source_id=self.source.value, source_name=self.source_name
        )
        # UTC, aware. Everything downstream that needs Korean local time
        # converts explicitly (time_ko); passing a naive local `now` is how
        # a port like this silently drifts nine hours.
        now = now or datetime.now(timezone.utc)
        try:
            await run_events(
                self._events(self._http(), now=now), sink, result=result
            )
        except Exception as exc:  # noqa: BLE001 — see below
            # Broad on purpose, and it must stay broad. The generators catch
            # the failures they can name; anything else — an upstream shape
            # no parser anticipated, a Mongo blip inside the sink, a route
            # code missing from CacheKey — would otherwise escape past
            # _on_results, and a tick that records NO health state is worse
            # than one that records failure: consecutiveFailures stays where
            # it was, so the alert can never fire and the daily summary calls
            # the module healthy while it writes nothing.
            #
            # modules/notices/orchestrator.py keeps the same guard for the
            # same reason, with the same instruction not to narrow it.
            result.errors += 1
            result.source_down = True
            result.last_error = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "bus_tick_failed",
                module=self.source.value,
                err=type(exc).__name__,
                err_msg=str(exc)[:200],
            )
        if self._on_results is not None:
            await self._on_results([result])
        return {
            "written": result.inserted + result.updated,
            "skipped": result.skipped,
            "errors": result.errors,
            "down": result.source_down,
        }

    async def shutdown(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ── helpers for subclasses ────────────────────────────────────────────

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = self._client_factory()
        return self._client

    def _snapshot(
        self, key: CacheKey, payload: Any, now: datetime
    ) -> CacheSnapshot:
        """One stored document.

        `fetchedAt` is the module's own notion of freshness — when the
        upstream answered — and is distinct from the `_updatedAt` the sink
        stamps, which says when the write happened. They diverge exactly
        when a tick is slow, which is when the difference matters.
        """
        return CacheSnapshot(
            key=document_id(key, shadow_writes=self._shadow_writes),
            fields={"data": payload, "fetchedAt": now},
        )

    def _events(
        self, client: httpx.AsyncClient, *, now: datetime
    ) -> AsyncIterator[CrawlEvent]:  # pragma: no cover - subclass duty
        raise NotImplementedError

    def _no_data_events(
        self, envelope: jongro.Envelope, where: str, errors: list[str]
    ) -> CrawlEvent:
        """Classify an empty body by the header code that came with it.

        `read_envelope` returns NO_DATA whenever `itemList` is not a list,
        whatever the code — that is a faithful port of the TypeScript's
        `if (!apiData) return;` and must not change, because the parity
        goldens are the migration's correctness criterion.

        What the header code IS allowed to change is the health signal,
        which writes nothing either way. `"4"` means "no results" and
        arrives every night; `"0"` means the upstream claimed success and
        then sent no body, which is it misbehaving. Collapsing the two
        would make a permanently empty upstream indistinguishable from 2am
        — no alert, no log, four documents quietly going stale.
        """
        code = envelope.header_code
        if code == jongro.NO_RESULTS_CODE:
            return ItemSkipped(
                source_id=self.source.value,
                article_no=NO_ITEM_NUMBER,
                reason=f"{where}: no data (headerCd={code})",
            )
        message = f"{where}: empty body with headerCd={code}"
        errors.append(message)
        return ItemFailed(
            source_id=self.source.value, article_no=NO_ITEM_NUMBER, error=message
        )

    def _finished(self, errors: Sequence[str]) -> SourceFinished:
        return SourceFinished(
            source_id=self.source.value,
            stopped_by="upstream_error" if errors else "ok",
            source_down=bool(errors),
            last_error=errors[0] if errors else "",
        )


class BusHsscModule(_BusModule):
    """Campus shuttle, every ten seconds.

    The sticky-timestamp state is `self._previous`: the payload published
    last tick, which `hssc.normalize` reads to carry a bus's FIRST
    sighting forward so `estimatedTime` accumulates into a dwell instead of
    resetting to zero every ten seconds.

    It is assigned before the write, matching the TypeScript, which sets
    `filteredHSSCStations` and then fires the cache write off unawaited.
    """

    source = BusSource.HSSC
    source_name = "HSSC 셔틀"

    def __init__(self, *, endpoint: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        if not endpoint:
            # Assembly time, not tick time. The family gate should already
            # have refused, so reaching this means something built the
            # module directly — better a sentence now than a request to ""
            # every ten seconds.
            raise ValueError(
                "BusHsscModule needs an endpoint "
                "(Config.hssc_api_url / API_HSSC_NEW_PROD)"
            )
        self._endpoint = endpoint
        self._previous: list[dict[str, Any]] = []

    @property
    def config(self) -> ModuleConfig:
        return ModuleConfig(
            name=self.source.value,
            interval_seconds=10,
            misfire_grace_time=30,
        )

    async def _events(
        self, client: httpx.AsyncClient, *, now: datetime
    ) -> AsyncIterator[CrawlEvent]:
        sid = self.source.value
        yield SourceStarted(source_id=sid, source_name=self.source_name)

        try:
            raw = await fetch_json(client, self._endpoint)
        except UpstreamError as exc:
            yield ListFetchFailed(source_id=sid, page=0, error=str(exc))
            yield self._finished([str(exc)])
            return

        try:
            rows = hssc.parse(raw)
            if rows is None:
                # Distinct from `[]`, which is a real "no buses running".
                # A non-array is the upstream misbehaving, and the stored
                # document must be left alone.
                raise hssc.HsscPayloadError("response was not an array")
            payload = hssc.normalize(self._previous, rows, now=now)
        except (hssc.HsscPayloadError, KoreanTimeFormatError) as exc:
            yield ItemFailed(source_id=sid, article_no=NO_ITEM_NUMBER, error=str(exc))
            yield self._finished([str(exc)])
            return

        self._previous = payload
        yield ItemCrawled(
            source_id=sid, item=self._snapshot(CacheKey.HSSC, payload, now)
        )
        yield self._finished([])


class BusJongroModule(_BusModule):
    """Jongro 02/07, every forty seconds — four documents per tick.

    One module rather than four because `BusSource` values are also the
    `--module` selector and the crawl-health identity (adr-008: one string,
    one place). The cost is that a single route failing is reported against
    the whole poller; the benefit is that "which module do I restart" has
    one answer.

    `source_down` is set when ANY of the four sub-fetches hard-fails, not
    only when all of them do. A route that has gone quietly dark is exactly
    the failure this migration must not introduce, and the alert threshold
    — eight consecutive ticks, about five minutes — is what filters the
    transient case, not the predicate.
    """

    source = BusSource.JONGRO
    source_name = "종로 마을버스"

    def __init__(
        self,
        *,
        service_key: str,
        routes: tuple[JongroRoute, ...] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        # Both raise at construction, which is boot. An un-encoded service
        # key produces a well-formed request that never authenticates, and
        # a bad route file drops every position report for one station
        # while looking exactly like "no bus is there" — neither fails in a
        # way a running poller would show you.
        validate_service_key(service_key)
        self._service_key = service_key
        self._routes = load_routes() if routes is None else routes
        # route code -> {stationId: ISO stamp}. The dwell clock, per route.
        self._dwell: dict[str, dict[str, str]] = {}

    @property
    def config(self) -> ModuleConfig:
        return ModuleConfig(
            name=self.source.value,
            interval_seconds=40,
            misfire_grace_time=120,
        )

    async def _events(
        self, client: httpx.AsyncClient, *, now: datetime
    ) -> AsyncIterator[CrawlEvent]:
        sid = self.source.value
        yield SourceStarted(source_id=sid, source_name=self.source_name)

        errors: list[str] = []
        for route in self._routes:
            async for event in self._list_events(client, route, now, errors):
                yield event
            async for event in self._loc_events(client, route, now, errors):
                yield event
        yield self._finished(errors)

    async def _list_events(
        self,
        client: httpx.AsyncClient,
        route: JongroRoute,
        now: datetime,
        errors: list[str],
    ) -> AsyncIterator[CrawlEvent]:
        sid = self.source.value
        try:
            raw = await fetch_json(client, route.list_url(self._service_key))
        except UpstreamError as exc:
            message = f"{route.id} list: {exc}"
            errors.append(message)
            yield ListFetchFailed(source_id=sid, page=0, error=message)
            return

        envelope = jongro.read_envelope(raw)
        match envelope.outcome:
            case jongro.Outcome.OK:
                yield ItemCrawled(
                    source_id=sid,
                    item=self._snapshot(
                        CacheKey.jongro_stations(route.code),
                        jongro.normalize_list(envelope.items),
                        now,
                    ),
                )
            case jongro.Outcome.NO_DATA:
                yield self._no_data_events(envelope, f"{route.id} list", errors)
            case jongro.Outcome.UPSTREAM_ERROR:
                message = f"{route.id} list: headerCd={envelope.header_code}"
                errors.append(message)
                yield ItemFailed(
                    source_id=sid, article_no=NO_ITEM_NUMBER, error=message
                )

    async def _loc_events(
        self,
        client: httpx.AsyncClient,
        route: JongroRoute,
        now: datetime,
        errors: list[str],
    ) -> AsyncIterator[CrawlEvent]:
        sid = self.source.value
        try:
            raw = await fetch_json(client, route.loc_url(self._service_key))
        except UpstreamError as exc:
            message = f"{route.id} loc: {exc}"
            errors.append(message)
            yield ListFetchFailed(source_id=sid, page=0, error=message)
            return

        envelope = jongro.read_envelope(raw)
        match envelope.outcome:
            case jongro.Outcome.OK:
                # The dwell clock advances only on a usable answer. Letting
                # it advance on an error would age out every station during
                # an outage and report a fresh 0-second dwell on recovery.
                payload, self._dwell[route.code] = jongro.normalize_loc(
                    self._dwell.get(route.code, {}),
                    envelope.items,
                    route.mapping,
                    now=now,
                )
                yield ItemCrawled(
                    source_id=sid,
                    item=self._snapshot(
                        CacheKey.jongro_locations(route.code), payload, now
                    ),
                )
            case jongro.Outcome.NO_DATA:
                yield self._no_data_events(envelope, f"{route.id} loc", errors)
            case jongro.Outcome.UPSTREAM_ERROR:
                message = f"{route.id} loc: headerCd={envelope.header_code}"
                errors.append(message)
                yield ItemFailed(
                    source_id=sid, article_no=NO_ITEM_NUMBER, error=message
                )


class BusCampusEtaModule(_BusModule):
    """Inter-campus driving ETA, every ten minutes.

    Stateless, and the only one of the three that is. The TypeScript keeps
    a last-good copy in memory to serve when both directions fail; here the
    stored document already is that copy, so a failing tick writes nothing
    and the previous answer stands with its own `fetchedAt` on it.

    It writes only when BOTH directions succeed, mirroring the
    TypeScript's "only cache fully successful responses". A half-empty ETA
    is worse than a stale one when it lands in a document that persists.

    Its target collection has no TTL, which is why it is not `bus_cache`
    (see wiring.CAMPUS_ETA_COLLECTION): at this cadence the server's
    sixty-second expiry would leave the document absent nine minutes out
    of every ten.
    """

    source = BusSource.CAMPUS_ETA
    source_name = "캠퍼스 간 이동시간"

    def __init__(self, *, api_key_id: str, api_key: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        if not api_key_id or not api_key:
            raise ValueError(
                "BusCampusEtaModule needs both Naver credentials "
                "(NAVER_API_KEY_ID, NAVER_API_KEY)"
            )
        self._headers = {
            campus_eta.KEY_ID_HEADER: api_key_id,
            campus_eta.KEY_HEADER: api_key,
        }

    @property
    def config(self) -> ModuleConfig:
        return ModuleConfig(
            name=self.source.value,
            interval_seconds=600,
            misfire_grace_time=300,
            # The only one with a warm-up run. Ten seconds until the first
            # shuttle document is not a gap; ten MINUTES until the first
            # ETA document is. run_scheduler awaits these before installing
            # its signal handler, so each one is paid for at boot.
            run_on_start=True,
        )

    async def _events(
        self, client: httpx.AsyncClient, *, now: datetime
    ) -> AsyncIterator[CrawlEvent]:
        sid = self.source.value
        yield SourceStarted(source_id=sid, source_name=self.source_name)

        legs: dict[str, campus_eta.EtaLeg | None] = {}
        errors: list[str] = []
        # Sequential rather than the TypeScript's Promise.allSettled. Two
        # 5-second requests once every ten minutes is not worth the
        # concurrency, and doing them in order keeps each failure attached
        # to the direction that produced it.
        for name, (start, goal) in campus_eta.LEGS:
            try:
                raw = await fetch_json(
                    client,
                    campus_eta.directions_url(start, goal),
                    headers=self._headers,
                    timeout=campus_eta.TIMEOUT_SECONDS,
                )
                legs[name] = campus_eta.read_leg(raw)
            except (UpstreamError, campus_eta.CampusEtaPayloadError) as exc:
                message = f"{name}: {exc}"
                errors.append(message)
                legs[name] = None
                yield ItemFailed(
                    source_id=sid, article_no=NO_ITEM_NUMBER, error=message
                )

        # Splatted, not `legs.get("inja")`. The LEGS table names the payload
        # fields, and `.get` would answer None for a name that no longer
        # exists — every tick would then write nothing while reporting
        # success. A TypeError names the drift on the first tick instead.
        data = campus_eta.EtaData(**legs)
        if data.complete:
            yield ItemCrawled(
                source_id=sid,
                item=self._snapshot(CacheKey.CAMPUS_ETA, data.as_fields(), now),
            )
        yield self._finished(errors)
