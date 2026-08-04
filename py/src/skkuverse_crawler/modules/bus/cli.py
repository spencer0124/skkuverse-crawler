"""`bus --once` — fetch one tick and print it.

Exists before anything is scheduled, and before anything is written,
because it is how you check the normaliser against a live upstream by
hand. The parity tests prove the port matches the TypeScript over
captured responses; this is what tells you the upstream still looks like
those captures.

Writes nothing. Storage arrives in a later phase, wired in by
`wiring.py` — a module does not reach for its own sink.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from typing import Any

import click

from ...shared.logger import configure_logging, get_logger
from . import hssc, jongro
from .client import UpstreamError, fetch_json
from .registry import RouteConfigError, load_routes, validate_service_key
from .sources import BusSource

logger = get_logger("bus_cli")


@click.command("bus")
@click.option("--once", is_flag=True, required=True, help="Run a single tick.")
@click.option(
    "--poller",
    type=click.Choice([s.value for s in BusSource], case_sensitive=False),
    required=True,
    help="Which upstream to poll.",
)
@click.option("--json", "as_json", is_flag=True, help="Print the payload as JSON.")
def bus_cli(once: bool, poller: str, as_json: bool) -> None:
    """Fetch one bus tick and print it (no storage)."""
    from ...env import init_config

    config = init_config()
    configure_logging(config)
    # click.Choice already rejected anything else, so this cannot raise —
    # but going through the enum means the rest of the function handles a
    # typed value rather than a string that happens to look right.
    source = BusSource(poller.lower())
    asyncio.run(_run_once(source, config, as_json=as_json))


async def _run_once(source: BusSource, config: Any, *, as_json: bool) -> None:
    import httpx

    now = datetime.now(timezone.utc)
    async with httpx.AsyncClient() as client:
        try:
            payloads = await _collect(source, config, client, now=now)
        except RouteConfigError as exc:
            # Same treatment as the HSSC "not configured" path. Without
            # this the jongro route dies with a raw traceback while the
            # hssc one prints a sentence — and the CI check only exercises
            # hssc, so it could not have caught the difference.
            raise click.ClickException(str(exc)) from exc
        except UpstreamError as exc:
            # Not a traceback: an unreachable upstream is an operational
            # fact, and the exit code is what a script reads.
            click.echo(f"upstream unavailable: {exc}", err=True)
            raise SystemExit(1) from exc

    for key, payload in payloads:
        if as_json:
            sys.stdout.write(
                json.dumps({"key": key, "payload": payload}, ensure_ascii=False) + "\n"
            )
        else:
            count = "no write" if payload is None else f"{len(payload)} item(s)"
            click.echo(f"{key}: {count}")


async def _collect(
    source: BusSource, config: Any, client: Any, *, now: datetime
) -> list[tuple[str, list[dict[str, Any]] | None]]:
    """One tick's worth of (cache key, payload) pairs.

    `None` means the upstream said nothing usable and the stored document
    should stand — kept distinct from `[]`, which is a real statement that
    nothing is running.

    State starts empty every invocation, so `estimatedTime` reads 0 here
    where a running poller would show an accumulated dwell. That is
    inherent to a single tick, not a bug.
    """
    if source is BusSource.HSSC:
        if not config.hssc_api_url:
            raise click.ClickException(
                "the HSSC endpoint is not configured "
                "(set API_HSSC_NEW_PROD or API_HSSC_NEW_DEV)"
            )
        rows = hssc.parse(await fetch_json(client, config.hssc_api_url))
        if rows is None:
            return [("hssc", None)]
        return [("hssc", hssc.normalize([], rows, now=now))]

    if source is BusSource.JONGRO:
        validate_service_key(config.seoul_bus_service_key)
        key = config.seoul_bus_service_key
        out: list[tuple[str, list[dict[str, Any]] | None]] = []
        for route in load_routes():
            listing = jongro.read_envelope(
                await fetch_json(client, route.list_url(key))
            )
            out.append(
                (
                    f"jongro_stations_{route.code}",
                    jongro.normalize_list(listing.items)
                    if listing.outcome is jongro.Outcome.OK
                    else None,
                )
            )
            positions = jongro.read_envelope(
                await fetch_json(client, route.loc_url(key))
            )
            rows_loc: list[dict[str, Any]] | None = None
            if positions.outcome is jongro.Outcome.OK:
                rows_loc, _ = jongro.normalize_loc(
                    {}, positions.items, route.mapping, now=now
                )
            out.append((f"jongro_locations_{route.code}", rows_loc))
        return out

    raise click.ClickException(
        f"{source.value} has no --once implementation yet "
        "(campus ETA arrives with the scheduled modules)"
    )
