"""Typed names for everything that selects behaviour in this module.

No bare strings. A cache key is a document `_id` in a collection another
service reads, and a module name is what `--module` and the health record
key on — both are the kind of value where a typo produces a plausible
result rather than an error. As `str` subclasses they drop straight into
Mongo filters and log fields while still being `mypy`-checkable and
enumerable.

Same reasoning as `modules/notices/config/source_ids.SourceId`, which is
generated for the same reason.
"""

from __future__ import annotations

from enum import Enum


class BusSource(str, Enum):
    """Module names, which are also the identity health state is keyed on.

    Value == `ModuleConfig.name` == the `--module` selector == the
    `SourceResult.source_id`. One string, one place.
    """

    HSSC = "bus-hssc"
    JONGRO = "bus-jongro"
    CAMPUS_ETA = "bus-campus-eta"


class CacheKey(str, Enum):
    """`bus_cache` document ids.

    These are a contract with skkuverse-server, which reads them by name —
    changing one is a breaking change for the app, not a rename. The
    Jongro members are per route code because the server's endpoints are.
    """

    HSSC = "hssc"
    JONGRO_STATIONS_02 = "jongro_stations_02"
    JONGRO_STATIONS_07 = "jongro_stations_07"
    JONGRO_LOCATIONS_02 = "jongro_locations_02"
    JONGRO_LOCATIONS_07 = "jongro_locations_07"
    CAMPUS_ETA = "campus_eta"

    @classmethod
    def jongro_stations(cls, code: str) -> CacheKey:
        return cls(f"jongro_stations_{code}")

    @classmethod
    def jongro_locations(cls, code: str) -> CacheKey:
        return cls(f"jongro_locations_{code}")


# Until the cutover the crawler writes beside the server rather than over
# it. Both would otherwise upsert the same _id, last writer wins, and the
# "compare the two" step of the migration would have nothing to compare.
SHADOW_SUFFIX = "__shadow"


def shadow(key: CacheKey) -> str:
    """Derived, never hand-written — a typo here writes a document the
    comparison step would then silently not find."""
    return f"{key.value}{SHADOW_SUFFIX}"
