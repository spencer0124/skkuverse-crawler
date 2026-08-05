"""The three pollers as scheduled modules.

The parity suite already proves the transforms. What is new here is
everything around them — which document id gets written, what a bad
upstream turns into, and whether the tick-to-tick state that makes dwell
times work survives being called by a scheduler rather than a replay loop.

The failure cases carry most of the weight. A poller that publishes an
empty list during an upstream outage looks identical, in every log, to one
publishing a correct "no buses are running"; the difference only exists in
which event was emitted, so that is what these assert.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest
import respx

from skkuverse_crawler.core.events import (
    ItemCrawled,
    ItemFailed,
    ItemSkipped,
    ListFetchFailed,
)
from skkuverse_crawler.modules.bus.campus_eta import SEOUL_CAMPUS
from skkuverse_crawler.modules.bus.module import (
    BusCampusEtaModule,
    BusHsscModule,
    BusJongroModule,
)
from skkuverse_crawler.modules.bus.registry import load_routes
from skkuverse_crawler.modules.bus.sources import BusSource

HSSC_ENDPOINT = "https://hssc.example/api"
TICK = datetime(2026, 3, 16, 0, 0, 0, tzinfo=timezone.utc)  # 09:00 KST


class _RecordingSink:
    """A Sink that keeps everything, so a test can assert on the events as
    well as on the documents."""

    def __init__(self) -> None:
        self.prepared: list = []
        self.events: list = []
        self.writes: list = []

    async def prepare(self, source) -> None:
        self.prepared.append(source)

    async def accept(self, event):
        self.events.append(event)
        if isinstance(event, ItemCrawled):
            self.writes.append(event.item)
        return None

    async def flush(self) -> None:
        return None

    # ── assertions helpers ────────────────────────────────────────────────

    def written(self) -> dict[str, object]:
        """key -> payload, for the documents this tick produced."""
        return {w.key: w.fields["data"] for w in self.writes}

    def of(self, *types) -> list:
        return [e for e in self.events if isinstance(e, types)]


@pytest.fixture()
def sink():
    return _RecordingSink()


@pytest.fixture()
def sink_factory(sink):
    async def factory():
        return sink

    return factory


# ── HSSC ──────────────────────────────────────────────────────────────────


def _hssc_row(*, line_no="1", stop_no="3", seq="5", get_date="2026-03-16 오전 8:58:46"):
    return {
        "line_no": line_no,
        "inout": "1",
        "stop_no": stop_no,
        "seq": seq,
        "stop_name": "농구장정류소",
        "get_date": get_date,
    }


def _hssc(sink_factory, **kwargs):
    return BusHsscModule(
        sink_factory=sink_factory, endpoint=HSSC_ENDPOINT, **kwargs
    )


class TestHssc:
    @respx.mock
    async def test_a_good_tick_writes_the_shadow_key(self, sink, sink_factory):
        respx.get(HSSC_ENDPOINT).mock(
            return_value=httpx.Response(200, json=[_hssc_row()])
        )
        summary = await _hssc(sink_factory).run(now=TICK)

        assert list(sink.written()) == ["hssc__shadow"], (
            "Phase 4 writes beside the server, never over it"
        )
        assert summary == {"written": 1, "skipped": 0, "errors": 0, "down": False}
        assert sink.prepared[0].source_id == BusSource.HSSC.value

    @respx.mock
    async def test_the_cutover_writes_the_live_key(self, sink, sink_factory):
        """`shadow_writes=False` is the whole of the Phase 5 cutover, so it
        is worth one test that it does what its name says."""
        respx.get(HSSC_ENDPOINT).mock(
            return_value=httpx.Response(200, json=[_hssc_row()])
        )
        await _hssc(sink_factory, shadow_writes=False).run(now=TICK)
        assert list(sink.written()) == ["hssc"]

    @respx.mock
    async def test_the_payload_carries_fetched_at_beside_the_data(
        self, sink, sink_factory
    ):
        respx.get(HSSC_ENDPOINT).mock(
            return_value=httpx.Response(200, json=[_hssc_row()])
        )
        await _hssc(sink_factory).run(now=TICK)
        fields = sink.writes[0].fields
        assert fields["fetchedAt"] == TICK
        assert "_updatedAt" not in fields, "that stamp belongs to the sink"

    @respx.mock
    async def test_an_empty_array_is_published_not_swallowed(
        self, sink, sink_factory
    ):
        """`[]` is a real statement that no buses are running, and it has to
        reach the document — the app renders an empty board from it."""
        respx.get(HSSC_ENDPOINT).mock(return_value=httpx.Response(200, json=[]))
        summary = await _hssc(sink_factory).run(now=TICK)
        assert sink.written() == {"hssc__shadow": []}
        assert summary["down"] is False

    @respx.mock
    async def test_the_sticky_timestamp_survives_between_ticks(
        self, sink, sink_factory
    ):
        """The scheduler calls the same instance forever, so the dwell state
        lives on it. Without this the app could never show "has been here 4
        minutes" — every tick would reset to zero."""
        respx.get(HSSC_ENDPOINT).mock(
            return_value=httpx.Response(200, json=[_hssc_row()])
        )
        module = _hssc(sink_factory)

        await module.run(now=TICK)
        await module.run(now=TICK + timedelta(seconds=10))

        first, second = (w.fields["data"][0] for w in sink.writes)
        assert first["eventDate"] == second["eventDate"], "first sighting carried"
        assert second["estimatedTime"] - first["estimatedTime"] == 10

    @respx.mock
    async def test_a_non_array_response_fails_loudly_and_writes_nothing(
        self, sink, sink_factory
    ):
        """Distinct from `[]`. The upstream pins the last six rows
        indefinitely and never sends an empty array, so a non-array is it
        misbehaving — publishing "no buses" from that would be an outage
        rendered as a fact."""
        respx.get(HSSC_ENDPOINT).mock(
            return_value=httpx.Response(200, json={"error": "nope"})
        )
        summary = await _hssc(sink_factory).run(now=TICK)

        assert sink.writes == []
        assert summary["down"] is True
        assert "not an array" in sink.of(ItemFailed)[0].error

    @respx.mock
    @pytest.mark.parametrize(
        "row,fragment",
        [
            ({k: v for k, v in _hssc_row().items() if k != "seq"}, "missing 'seq'"),
            (_hssc_row(seq="NaN"), "expected an integer"),
            (_hssc_row(get_date="2026-03-16 8:58:46"), "오전"),
        ],
        ids=["missing field", "non-integer seq", "unparseable timestamp"],
    )
    async def test_a_malformed_row_is_an_error_not_a_traceback(
        self, sink, sink_factory, row, fragment
    ):
        respx.get(HSSC_ENDPOINT).mock(return_value=httpx.Response(200, json=[row]))
        summary = await _hssc(sink_factory).run(now=TICK)

        assert sink.writes == []
        assert summary["down"] is True
        assert fragment in sink.of(ItemFailed)[0].error

    @respx.mock
    async def test_an_unreachable_upstream_leaves_the_document_alone(
        self, sink, sink_factory
    ):
        respx.get(HSSC_ENDPOINT).mock(return_value=httpx.Response(503))
        summary = await _hssc(sink_factory).run(now=TICK)

        assert sink.writes == []
        assert summary["down"] is True
        assert "HTTP 503" in sink.of(ListFetchFailed)[0].error

    @respx.mock
    async def test_the_error_never_carries_the_endpoint(self, sink, sink_factory):
        """For HSSC the URL IS the credential, and these strings are logged."""
        respx.get(HSSC_ENDPOINT).mock(return_value=httpx.Response(503))
        await _hssc(sink_factory).run(now=TICK)
        assert "hssc.example" not in sink.of(ListFetchFailed)[0].error

    async def test_an_empty_endpoint_is_refused_at_construction(self, sink_factory):
        with pytest.raises(ValueError, match="API_HSSC_NEW_PROD"):
            BusHsscModule(sink_factory=sink_factory, endpoint="")


# ── Jongro ────────────────────────────────────────────────────────────────


def _envelope(items, code="0"):
    return {"msgHeader": {"headerCd": code}, "msgBody": {"itemList": items}}


LIST_PATH = "/api/rest/arrive/getArrInfoByRouteAll"
LOC_PATH = "/api/rest/buspos/getBusPosByRouteSt"


def _jongro(sink_factory, **kwargs):
    return BusJongroModule(
        sink_factory=sink_factory, service_key="test-key", **kwargs
    )


def _station_id(code: str) -> str:
    """A real topisId for the route, so `normalize_loc` maps it instead of
    dropping it — an unmapped position is silently skipped, which would
    make a broken assertion look like a passing one."""
    route = next(r for r in load_routes() if r.code == code)
    return next(iter(route.mapping))


def _jongro_upstream(*, list_code="0", loc_code="0", fail_loc_for=None):
    """One handler for both endpoints and both routes.

    Code `"4"` sends a null `itemList`, because that is how the real
    overnight response arrives — `"4"` with a populated body would be
    `Outcome.OK`, and a test built on that would prove nothing about the
    night-time path it claims to cover.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        code = "02" if _is_route(request, "02") else "07"
        if request.url.path == LIST_PATH:
            items = None if list_code == "4" else [{"stId": "1", "stNm": "정류장"}]
            return httpx.Response(200, json=_envelope(items, code=list_code))
        if fail_loc_for is not None and code == fail_loc_for:
            return httpx.Response(500)
        items = (
            None
            if loc_code == "4"
            else [{"lastStnId": _station_id(code), "plainNo": "서울70사1234"}]
        )
        return httpx.Response(200, json=_envelope(items, code=loc_code))

    return handler


def _is_route(request: httpx.Request, code: str) -> bool:
    route = next(r for r in load_routes() if r.code == code)
    return request.url.params.get("busRouteId") == route.bus_route_id


class TestJongro:
    @respx.mock
    async def test_a_good_tick_writes_four_shadow_documents(self, sink, sink_factory):
        respx.route(host="ws.bus.go.kr").mock(side_effect=_jongro_upstream())
        summary = await _jongro(sink_factory).run(now=TICK)

        assert set(sink.written()) == {
            "jongro_stations_02__shadow",
            "jongro_locations_02__shadow",
            "jongro_stations_07__shadow",
            "jongro_locations_07__shadow",
        }
        assert summary == {"written": 4, "skipped": 0, "errors": 0, "down": False}

    @respx.mock
    async def test_the_overnight_no_data_code_is_not_a_failure(
        self, sink, sink_factory
    ):
        """`headerCd "4"` arrives every night when nothing is running.
        Counting it as down would page someone at 2am, daily, forever."""
        respx.route(host="ws.bus.go.kr").mock(
            side_effect=_jongro_upstream(list_code="4", loc_code="4")
        )
        summary = await _jongro(sink_factory).run(now=TICK)

        assert sink.writes == [], "the previous documents stand"
        assert summary["down"] is False
        assert summary["skipped"] == 4
        assert len(sink.of(ItemSkipped)) == 4

    @respx.mock
    async def test_an_upstream_error_code_is_a_failure(self, sink, sink_factory):
        respx.route(host="ws.bus.go.kr").mock(
            side_effect=_jongro_upstream(list_code="1", loc_code="1")
        )
        summary = await _jongro(sink_factory).run(now=TICK)

        assert sink.writes == []
        assert summary["down"] is True
        assert "headerCd=1" in sink.of(ItemFailed)[0].error

    @respx.mock
    async def test_one_dark_route_still_marks_the_source_down(
        self, sink, sink_factory
    ):
        """`source_down` on ANY sub-fetch failing, not all of them. A route
        that has quietly gone dark is exactly what this migration must not
        introduce; five minutes of consecutive ticks is what filters the
        transient case, not the predicate."""
        respx.route(host="ws.bus.go.kr").mock(
            side_effect=_jongro_upstream(fail_loc_for="07")
        )
        summary = await _jongro(sink_factory).run(now=TICK)

        assert summary["down"] is True
        assert summary["errors"] == 1
        assert "jongro_locations_07__shadow" not in sink.written()
        assert "jongro_locations_02__shadow" in sink.written(), (
            "one broken route must not suppress the others"
        )

    @respx.mock
    async def test_the_dwell_clock_survives_between_ticks(self, sink, sink_factory):
        """`estimatedTime` runs 0, 40, 80 … — how long a bus has been sitting
        at a station. Per route, so one route's outage cannot reset the
        other's clock."""
        respx.route(host="ws.bus.go.kr").mock(side_effect=_jongro_upstream())
        module = _jongro(sink_factory)

        await module.run(now=TICK)
        await module.run(now=TICK + timedelta(seconds=40))

        dwell = [
            w.fields["data"][0]["estimatedTime"]
            for w in sink.writes
            if w.key == "jongro_locations_02__shadow"
        ]
        assert dwell == [0, 40]

    @respx.mock
    async def test_a_failing_route_does_not_advance_its_dwell_clock(
        self, sink, sink_factory
    ):
        """Letting an error tick record a station time would age every
        station out during an outage and report a fresh 0-second dwell on
        recovery — a bus that "just arrived" after being there an hour."""
        module = _jongro(sink_factory)
        with respx.mock:
            respx.route(host="ws.bus.go.kr").mock(side_effect=_jongro_upstream())
            await module.run(now=TICK)
        with respx.mock:
            respx.route(host="ws.bus.go.kr").mock(
                side_effect=_jongro_upstream(loc_code="1")
            )
            await module.run(now=TICK + timedelta(seconds=40))
        with respx.mock:
            respx.route(host="ws.bus.go.kr").mock(side_effect=_jongro_upstream())
            await module.run(now=TICK + timedelta(seconds=80))

        dwell = [
            w.fields["data"][0]["estimatedTime"]
            for w in sink.writes
            if w.key == "jongro_locations_02__shadow"
        ]
        assert dwell == [0, 80], "the clock kept running through the failed tick"

    async def test_an_unencoded_service_key_is_refused_at_construction(
        self, sink_factory
    ):
        """An un-encoded key produces a well-formed request that simply
        never authenticates — nothing raises at tick time, every response
        is just an error."""
        from skkuverse_crawler.modules.bus.registry import RouteConfigError

        with pytest.raises(RouteConfigError, match="URL-encoded"):
            BusJongroModule(sink_factory=sink_factory, service_key="key with spaces")


# ── Campus ETA ────────────────────────────────────────────────────────────

NAVER_HOST = "naveropenapi.apigw.ntruss.com"


def _naver_ok(duration=1_800_000):
    return httpx.Response(
        200,
        json={
            "code": 0,
            "message": "ok",
            "route": {"traoptimal": [{"summary": {"duration": duration, "distance": 45_000}}]},
        },
    )


def _campus_eta(sink_factory, **kwargs):
    return BusCampusEtaModule(
        sink_factory=sink_factory, api_key_id="id", api_key="secret", **kwargs
    )


class TestCampusEta:
    @respx.mock
    async def test_both_directions_produce_one_document(self, sink, sink_factory):
        respx.route(host=NAVER_HOST).mock(return_value=_naver_ok())
        summary = await _campus_eta(sink_factory).run(now=TICK)

        assert list(sink.written()) == ["campus_eta__shadow"]
        payload = sink.written()["campus_eta__shadow"]
        assert payload["inja"]["durationText"] == "30분"
        assert payload["jain"]["durationText"] == "30분"
        assert summary["down"] is False

    @respx.mock
    async def test_the_credentials_travel_as_headers(self, sink_factory):
        route = respx.route(host=NAVER_HOST).mock(return_value=_naver_ok())
        await _campus_eta(sink_factory).run(now=TICK)

        headers = route.calls[0].request.headers
        assert headers["X-NCP-APIGW-API-KEY-ID"] == "id"
        assert headers["X-NCP-APIGW-API-KEY"] == "secret"

    @respx.mock
    async def test_both_directions_are_actually_fetched(self, sink_factory):
        route = respx.route(host=NAVER_HOST).mock(return_value=_naver_ok())
        await _campus_eta(sink_factory).run(now=TICK)

        starts = [c.request.url.params["start"] for c in route.calls]
        assert len(starts) == 2 and starts[0] == SEOUL_CAMPUS
        assert starts[0] != starts[1], "one direction fetched twice"

    @respx.mock
    async def test_a_half_answer_is_not_published(self, sink, sink_factory):
        """The TypeScript caches only fully successful responses. Here the
        document IS the cache, and a half-empty ETA that persists is worse
        than a stale one that says when it was taken."""
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            return _naver_ok() if calls["n"] == 1 else httpx.Response(500)

        respx.route(host=NAVER_HOST).mock(side_effect=handler)
        summary = await _campus_eta(sink_factory).run(now=TICK)

        assert sink.writes == [], "the previous answer stands"
        assert summary["down"] is True
        assert "jain" in sink.of(ItemFailed)[0].error

    @respx.mock
    async def test_a_nonzero_naver_code_is_a_failure_not_a_write(
        self, sink, sink_factory
    ):
        respx.route(host=NAVER_HOST).mock(
            return_value=httpx.Response(200, json={"code": 3, "message": "출발지 오류"})
        )
        summary = await _campus_eta(sink_factory).run(now=TICK)

        assert sink.writes == []
        assert summary["errors"] == 2, "both directions failed independently"
        assert summary["down"] is True

    async def test_missing_credentials_are_refused_at_construction(self, sink_factory):
        with pytest.raises(ValueError, match="NAVER_API_KEY"):
            BusCampusEtaModule(sink_factory=sink_factory, api_key_id="id", api_key="")


# ── shared scaffolding ────────────────────────────────────────────────────


class TestClientLifetime:
    @respx.mock
    async def test_one_client_is_reused_across_ticks(self, sink_factory):
        """A ten-second poller building a client per tick would throw away
        every connection it opened, which is most of what it does."""
        respx.get(HSSC_ENDPOINT).mock(return_value=httpx.Response(200, json=[]))
        module = _hssc(sink_factory)

        await module.run(now=TICK)
        first = module._client
        await module.run(now=TICK + timedelta(seconds=10))

        assert module._client is first

    @respx.mock
    async def test_shutdown_closes_it_and_a_later_tick_still_works(
        self, sink_factory
    ):
        respx.get(HSSC_ENDPOINT).mock(return_value=httpx.Response(200, json=[]))
        module = _hssc(sink_factory)

        await module.run(now=TICK)
        closed = module._client
        await module.shutdown()

        assert closed.is_closed
        assert module._client is None
        await module.run(now=TICK)  # rebuilds rather than reusing a closed client

    async def test_shutdown_before_any_tick_is_harmless(self, sink_factory):
        await _hssc(sink_factory).shutdown()


class TestSchedules:
    @pytest.mark.parametrize(
        "module_factory,name,interval,grace,warm",
        [
            (_hssc, "bus-hssc", 10, 30, False),
            (_jongro, "bus-jongro", 40, 120, False),
            (_campus_eta, "bus-campus-eta", 600, 300, True),
        ],
    )
    def test_the_cadences(self, sink_factory, module_factory, name, interval, grace, warm):
        """Grace must exceed the interval, not sit under it. These fetch
        CURRENT state, so a late tick is not a stale one — the scheduler's
        ten-second default would drop a ten-second poller's ticks whenever
        the event loop was busy, and misfire is judged before coalesce, so
        the dropped tick is not merged into the next."""
        from skkuverse_crawler.plugins.scheduler.runner import (
            DEFAULT_MISFIRE_GRACE_SECONDS,
        )

        config = module_factory(sink_factory).config
        assert config.name == name
        assert config.interval_seconds == interval
        assert config.cron_schedule is None
        assert config.misfire_grace_time == grace
        assert config.misfire_grace_time > DEFAULT_MISFIRE_GRACE_SECONDS
        assert config.run_on_start is warm

    def test_module_names_are_the_enum(self, sink_factory):
        """One string: the ModuleConfig name, the --module selector and the
        crawl-health source id are the same value from the same place."""
        assert {
            _hssc(sink_factory).config.name,
            _jongro(sink_factory).config.name,
            _campus_eta(sink_factory).config.name,
        } == {s.value for s in BusSource}
