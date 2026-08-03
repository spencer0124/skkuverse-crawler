"""In-memory Motor collection fake for characterization (golden) tests.

Why hand-rolled instead of mongomock-motor: the goldens need the *ordered
operation log* (``.ops``) — how many round trips, in what order, with what
arguments — not just the final state. mongomock cannot expose that.

Honesty contract: every operator this fake does not implement raises
``NotImplementedError`` instead of silently no-opping. A fake that ignores an
operator makes the goldens lie (a later ``$unset`` would pass the golden and
diverge only in production). The fidelity of what IS implemented is pinned by
``tests/conformance/`` which replays the same operations against a real
MongoDB.

Aggregation-pipeline updates (``update=[...]``) are implemented for the
shape update_checker's soft-delete counter uses: ``$set`` stages over
``$add``/``$ifNull``/``$cond``/``$gte``. Stages apply sequentially — stage
2 sees stage 1's output — which is the whole reason the counter reaches
its threshold on the third failure and not the fourth. Level-1
conformance pins that ordering against real Mongo.

Comparison and boolean coercion inside those expressions follow Mongo,
not Python: ``$gte`` ranks by BSON type first (``3 >= null`` is true,
``null >= 3`` is false), and ``$cond`` treats ``""`` and ``[]`` as true.

Known, deliberate gaps — all raise:

- pipeline stages other than ``$set``; expression operators outside the
  four above (including inside an untaken ``$cond`` branch, which Mongo
  rejects at parse time); pipeline updates with ``upsert=True``; an empty
  pipeline
- dotted field paths (``"$a.b"``) and ``$set`` keys, system variables
  (``"$$NOW"``), array-valued expressions, non-array operands, and
  ``$ifNull`` with fewer than two arguments
- ``$expr`` filters (used only by the ai_summary re-summary query)

The non-pipeline ``_apply_update`` still writes a dotted ``$set`` key as a
literal top-level key — unchanged from before this fake grew pipelines,
and unreachable from src/, but it is not the same guard.

BSON fidelity: datetimes are truncated to millisecond precision at write
time, because BSON stores milliseconds while ``datetime.now()`` carries
microseconds — without truncation, fake state and real-Mongo state can never
compare equal in the conformance suite.
"""
from __future__ import annotations

import copy
from datetime import datetime
from typing import Any

from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.errors import BulkWriteError, DuplicateKeyError

_MISSING = object()

_SUPPORTED_QUERY_OPS = {"$in", "$nin", "$ne", "$exists", "$gte", "$gt", "$not", "$or"}


def _trunc_ms(value: Any) -> Any:
    """Recursively truncate datetimes to millisecond precision (BSON fidelity)."""
    if isinstance(value, datetime):
        return value.replace(microsecond=(value.microsecond // 1000) * 1000)
    if isinstance(value, dict):
        return {k: _trunc_ms(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_trunc_ms(v) for v in value]
    return value


def _is_operator_doc(value: Any) -> bool:
    return isinstance(value, dict) and any(k.startswith("$") for k in value)


def _match_condition(actual: Any, cond: dict[str, Any]) -> bool:
    """Evaluate an operator document ({"$gte": 3, ...}) against a field value.

    Missing-field semantics follow real MongoDB: $ne/$nin match documents
    where the field is absent; $in/$gte/$gt do not; $exists checks presence.
    """
    for op, operand in cond.items():
        if op == "$in":
            if actual is _MISSING or actual not in operand:
                return False
        elif op == "$nin":
            if actual is not _MISSING and actual in operand:
                return False
        elif op == "$ne":
            # Mongo treats a missing field as null for $ne: {"$ne": True}
            # matches docs without the field, {"$ne": None} does not.
            if (None if actual is _MISSING else actual) == operand:
                return False
        elif op == "$exists":
            if bool(operand) != (actual is not _MISSING):
                return False
        elif op == "$gte":
            if actual is _MISSING or not actual >= operand:
                return False
        elif op == "$gt":
            if actual is _MISSING or not actual > operand:
                return False
        elif op == "$not":
            if _match_condition(actual, operand):
                return False
        else:
            raise NotImplementedError(f"FakeCollection: query operator {op!r} not implemented")
    return True


def _resolve_path(doc: Any, path: str) -> list[Any]:
    """Values at a dotted path, Mongo-style.

    Traversing an array fans out rather than indexing: ``editHistory.source``
    yields the ``source`` of every element, and the query matches when ANY
    of them matches. That is what makes ``{"editHistory.source": "tier2"}``
    mean "has a tier2 entry" rather than "the array has a source field".

    Returns a list because the caller must distinguish "no such path"
    (empty) from "the value is None" (``[None]``).
    """
    current: list[Any] = [doc]
    for part in path.split("."):
        nxt: list[Any] = []
        for value in current:
            if isinstance(value, list):
                nxt.extend(
                    item[part] for item in value
                    if isinstance(item, dict) and part in item
                )
            elif isinstance(value, dict) and part in value:
                nxt.append(value[part])
        current = nxt
        if not current:
            return []
    return current


def _validate_filter(filter_: dict[str, Any]) -> None:
    """Reject unsupported query shapes eagerly.

    Must run once per query, not per document — per-document validation
    silently passes on an empty collection, which is exactly the kind of
    fake-lies-by-omission this module exists to prevent.
    """
    for field, expected in filter_.items():
        if field == "$or":
            for sub in expected:
                _validate_filter(sub)
        elif field == "$expr":
            raise NotImplementedError(
                "FakeCollection: $expr not implemented (ai_summary query only)"
            )
        elif field.startswith("$"):
            raise NotImplementedError(f"FakeCollection: query operator {field!r} not implemented")
        elif _is_operator_doc(expected):
            for op, operand in expected.items():
                if op not in _SUPPORTED_QUERY_OPS:
                    raise NotImplementedError(
                        f"FakeCollection: query operator {op!r} not implemented"
                    )
                if op == "$not":
                    for inner_op in operand:
                        if inner_op not in _SUPPORTED_QUERY_OPS:
                            raise NotImplementedError(
                                f"FakeCollection: query operator {inner_op!r} not implemented"
                            )


def _matches(doc: dict[str, Any], filter_: dict[str, Any]) -> bool:
    for field, expected in filter_.items():
        if field == "$or":
            if not any(_matches(doc, sub) for sub in expected):
                return False
            continue
        if field == "$expr":
            raise NotImplementedError(
                "FakeCollection: $expr not implemented (ai_summary query only)"
            )
        if field.startswith("$"):
            raise NotImplementedError(f"FakeCollection: query operator {field!r} not implemented")
        if "." in field:
            # Any value along the path may satisfy the condition — Mongo's
            # array semantics, and the reason this is not a simple lookup.
            candidates = _resolve_path(doc, field)
            if _is_operator_doc(expected):
                if not any(_match_condition(v, expected) for v in candidates):
                    return False
            elif expected is None:
                if candidates and not any(v is None for v in candidates):
                    return False
            elif not any(v == expected for v in candidates):
                return False
            continue
        actual = doc.get(field, _MISSING)
        if _is_operator_doc(expected):
            if not _match_condition(actual, expected):
                return False
        elif expected is None:
            # Mongo equality-with-null also matches documents missing the field.
            if actual is not _MISSING and actual is not None:
                return False
        else:
            if actual is _MISSING or actual != expected:
                return False
    return True


def _project(doc: dict[str, Any], projection: dict[str, Any] | None) -> dict[str, Any]:
    if projection is None:
        return copy.deepcopy(doc)
    values = {k: v for k, v in projection.items() if k != "_id"}
    if not all(v in (1, True) for v in values.values()):
        raise NotImplementedError("FakeCollection: only include-style projections implemented")
    projected = {k: copy.deepcopy(doc[k]) for k in values if k in doc}
    if projection.get("_id", 1) and "_id" in doc:
        projected["_id"] = doc["_id"]
    return projected


_SUPPORTED_EXPR_OPS = {"$add", "$ifNull", "$cond", "$gte"}

# Mongo's canonical type ordering, trimmed to the types this fake stores.
# Comparison operators rank by type FIRST, which is why null >= 3 is false
# but 3 >= null is true — the asymmetry a "None means false" shortcut gets
# wrong in one direction.
_BSON_TYPE_RANK: list[tuple[Any, int]] = [
    (bool, 8),  # before int — bool is an int subclass in Python, not in BSON
    (datetime, 9),
    ((int, float), 2),
    (str, 3),
    (dict, 4),
    (list, 5),
]


def _bson_rank(value: Any) -> int:
    if value is None:
        return 1
    for types, rank in _BSON_TYPE_RANK:
        if isinstance(value, types):
            return rank
    raise NotImplementedError(f"FakeCollection: BSON ordering for {type(value).__name__}")


def _bson_cmp(left: Any, right: Any) -> int:
    """Three-way compare under Mongo's type-then-value ordering."""
    left_rank, right_rank = _bson_rank(left), _bson_rank(right)
    if left_rank != right_rank:
        return -1 if left_rank < right_rank else 1
    if left_rank in (1, 4, 5):  # null, object, array — equal-by-type is enough here
        return 0
    if left == right:
        return 0
    return -1 if left < right else 1


def _expr_truthy(value: Any) -> bool:
    """Mongo's boolean coercion: only false/null/0/missing are false.

    Notably "" and [] are TRUE — Python's truthiness disagrees, and that
    disagreement silently flips a $cond branch.
    """
    if value is None or value is False:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return True


def _validate_expr(expr: Any) -> None:
    """Reject expression shapes this fake does not model — once, before
    evaluation, like Mongo's parse-time operator check.

    Separate from _eval_expr so that an unsupported operator hidden in an
    untaken $cond branch still raises (Mongo rejects the whole pipeline at
    parse time) while evaluation itself stays lazy.
    """
    if isinstance(expr, str) and expr.startswith("$"):
        if expr.startswith("$$"):
            raise NotImplementedError(
                f"FakeCollection: system variable {expr!r} not implemented"
            )
        if "." in expr:
            raise NotImplementedError("FakeCollection: dotted field paths not implemented")
        return
    if isinstance(expr, list):
        # Mongo evaluates array elements; treating one as a literal would
        # silently store {"m": ["$n", 2]} instead of ["$n", 2] resolved.
        raise NotImplementedError("FakeCollection: array-valued expressions not implemented")
    if not isinstance(expr, dict):
        return
    if len(expr) != 1:
        raise NotImplementedError(f"FakeCollection: multi-key expression {set(expr)}")
    op, operand = next(iter(expr.items()))
    if op not in _SUPPORTED_EXPR_OPS:
        raise NotImplementedError(f"FakeCollection: expression operator {op!r} not implemented")
    if op == "$cond":
        if not isinstance(operand, dict):
            raise NotImplementedError("FakeCollection: array-form $cond not implemented")
        for key in ("if", "then", "else"):
            _validate_expr(operand[key])
        return
    if not isinstance(operand, list):
        raise NotImplementedError(f"FakeCollection: non-array operand for {op!r}")
    if op == "$ifNull" and len(operand) < 2:
        raise NotImplementedError(f"FakeCollection: {op!r} needs at least two arguments")
    for item in operand:
        _validate_expr(item)


def _eval_expr(expr: Any, doc: dict[str, Any]) -> Any:
    """Evaluate one validated aggregation expression against ``doc``.

    A missing field path evaluates to None — what ``$ifNull`` exists to
    catch. Call _validate_expr first; this assumes supported shapes.
    """
    if isinstance(expr, str) and expr.startswith("$"):
        return doc.get(expr[1:])
    if not isinstance(expr, dict):
        return expr
    op, operand = next(iter(expr.items()))
    if op == "$add":
        values = [_eval_expr(a, doc) for a in operand]
        if any(v is None for v in values):
            return None
        return sum(values)
    if op == "$ifNull":
        values = [_eval_expr(a, doc) for a in operand]
        for value in values[:-1]:
            if value is not None:
                return value
        return values[-1]
    if op == "$cond":
        branch = "then" if _expr_truthy(_eval_expr(operand["if"], doc)) else "else"
        return _eval_expr(operand[branch], doc)
    # $gte
    left, right = (_eval_expr(a, doc) for a in operand)
    return _bson_cmp(left, right) >= 0


def _apply_pipeline_update(doc: dict[str, Any], pipeline: list[Any]) -> None:
    """Apply an aggregation-pipeline update in place.

    Stages run in order and each sees the previous stage's output; within
    one stage every expression is evaluated against the stage's input, so
    values are computed before any is assigned.

    Staged through a working copy so a mid-pipeline raise leaves the
    stored document untouched — real Mongo rolls the whole update back,
    and a half-applied document is a state it could never produce.
    """
    if not pipeline:
        raise NotImplementedError(
            "FakeCollection: empty pipeline update (Mongo requires atomic operators)"
        )
    working = copy.deepcopy(doc)
    for stage in pipeline:
        if not isinstance(stage, dict) or set(stage) != {"$set"}:
            raise NotImplementedError(
                f"FakeCollection: pipeline stage {set(stage) if isinstance(stage, dict) else stage} "
                f"not implemented (only $set)"
            )
        for key, value in stage["$set"].items():
            if "." in key:
                raise NotImplementedError("FakeCollection: dotted $set keys not implemented")
            _validate_expr(value)
        computed = {key: _eval_expr(value, working) for key, value in stage["$set"].items()}
        for key, value in computed.items():
            working[key] = _trunc_ms(copy.deepcopy(value))
    doc.clear()
    doc.update(working)


def _apply_update(doc: dict[str, Any], update: dict[str, Any], *, insert: bool) -> None:
    for op, spec in update.items():
        if op == "$set":
            for key, value in spec.items():
                doc[key] = _trunc_ms(copy.deepcopy(value))
        elif op == "$setOnInsert":
            if insert:
                for key, value in spec.items():
                    doc[key] = _trunc_ms(copy.deepcopy(value))
        elif op == "$inc":
            for key, value in spec.items():
                doc[key] = doc.get(key, 0) + value
        elif op == "$push":
            for key, value in spec.items():
                array = doc.setdefault(key, [])
                if isinstance(value, dict) and "$each" in value:
                    unknown = set(value) - {"$each", "$slice"}
                    if unknown:
                        raise NotImplementedError(
                            f"FakeCollection: $push modifiers {unknown} not implemented"
                        )
                    array.extend(_trunc_ms(copy.deepcopy(v)) for v in value["$each"])
                    if "$slice" in value:
                        slice_n = value["$slice"]
                        if slice_n >= 0:
                            raise NotImplementedError(
                                "FakeCollection: non-negative $slice not implemented"
                            )
                        doc[key] = array[slice_n:]
                else:
                    array.append(_trunc_ms(copy.deepcopy(value)))
        else:
            raise NotImplementedError(f"FakeCollection: update operator {op!r} not implemented")


class _UpdateResult:
    def __init__(self, matched_count: int, modified_count: int, upserted_id: Any):
        self.matched_count = matched_count
        self.modified_count = modified_count
        self.upserted_id = upserted_id


class _BulkWriteResult:
    def __init__(self, matched_count: int, modified_count: int, upserted_count: int):
        self.matched_count = matched_count
        self.modified_count = modified_count
        self.upserted_count = upserted_count


class FakeCursor:
    def __init__(self, docs: list[dict[str, Any]]):
        self._docs = docs

    def sort(self, key_or_list: Any, direction: int | None = None) -> FakeCursor:
        keys = [(key_or_list, direction or 1)] if isinstance(key_or_list, str) else key_or_list
        for key, sort_dir in reversed(list(keys)):
            self._docs.sort(key=lambda d: d[key], reverse=sort_dir == -1)
        return self

    def limit(self, n: int) -> FakeCursor:
        if n:
            self._docs = self._docs[:n]
        return self

    def __aiter__(self) -> FakeCursor:
        self._iter = iter(self._docs)
        return self

    async def __anext__(self) -> dict[str, Any]:
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration from None


class FakeCollection:
    """Duck-typed stand-in for AsyncIOMotorCollection.

    ``.ops`` is the ordered log of every operation with its arguments —
    the goldens' primary artifact. ``bulk_write`` is recorded as ONE entry
    carrying its op list, so "exactly one bulk_write per page" is assertable.
    """

    def __init__(self, name: str = "notices"):
        self.name = name
        self.docs: list[dict[str, Any]] = []
        self.ops: list[tuple[str, dict[str, Any]]] = []
        self._unique_indexes: list[tuple[str, ...]] = []

    # -- helpers ----------------------------------------------------------

    def _record(self, op_name: str, **args: Any) -> None:
        self.ops.append((op_name, copy.deepcopy(args)))

    def _find_docs(self, filter_: dict[str, Any]) -> list[dict[str, Any]]:
        _validate_filter(filter_)
        return [doc for doc in self.docs if _matches(doc, filter_)]

    def _check_unique(self, candidate: dict[str, Any]) -> None:
        for key_fields in self._unique_indexes:
            key = tuple(candidate.get(f) for f in key_fields)
            for existing in self.docs:
                if existing is candidate:
                    continue
                if tuple(existing.get(f) for f in key_fields) == key:
                    raise DuplicateKeyError(
                        f"E11000 duplicate key error (fake): {dict(zip(key_fields, key))}"
                    )

    def _upsert_insert(self, filter_: dict[str, Any], update: dict[str, Any]) -> ObjectId:
        seeded = {
            k: copy.deepcopy(v)
            for k, v in filter_.items()
            if not k.startswith("$") and not _is_operator_doc(v)
        }
        _apply_update(seeded, update, insert=True)
        seeded["_id"] = ObjectId()
        self._check_unique(seeded)
        self.docs.append(seeded)
        return seeded["_id"]

    def _apply_update_one(
        self, filter_: dict[str, Any], update: dict[str, Any], upsert: bool
    ) -> _UpdateResult:
        if isinstance(update, list) and upsert:
            raise NotImplementedError(
                "FakeCollection: pipeline update with upsert not implemented "
                "(no caller needs it — see module docstring)"
            )
        matched = self._find_docs(filter_)
        if matched:
            doc = matched[0]
            before = copy.deepcopy(doc)
            if isinstance(update, list):
                _apply_pipeline_update(doc, update)
            else:
                _apply_update(doc, update, insert=False)
            return _UpdateResult(1, int(doc != before), None)
        if not upsert:
            return _UpdateResult(0, 0, None)
        return _UpdateResult(0, 0, self._upsert_insert(filter_, update))

    # -- Motor surface ----------------------------------------------------

    def find(
        self, filter_: dict[str, Any] | None = None, projection: dict[str, Any] | None = None
    ) -> FakeCursor:
        filter_ = filter_ or {}
        self._record("find", filter=filter_, projection=projection)
        return FakeCursor([_project(doc, projection) for doc in self._find_docs(filter_)])

    async def count_documents(self, filter_: dict[str, Any]) -> int:
        self._record("count_documents", filter=filter_)
        return len(self._find_docs(filter_))

    async def create_index(
        self,
        keys: Any,
        unique: bool = False,
        name: str | None = None,
        partialFilterExpression: dict[str, Any] | None = None,  # noqa: N803 (pymongo kwarg)
        **kwargs: Any,
    ) -> str:
        if kwargs:
            raise NotImplementedError(f"FakeCollection: create_index kwargs {set(kwargs)}")
        key_list = [(keys, 1)] if isinstance(keys, str) else list(keys)
        self._record(
            "create_index",
            keys=key_list,
            unique=unique,
            name=name,
            partialFilterExpression=partialFilterExpression,
        )
        fields = tuple(field for field, _ in key_list)
        if unique and fields not in self._unique_indexes:
            self._unique_indexes.append(fields)
        return name or "_".join(f"{f}_{d}" for f, d in key_list)

    async def update_one(
        self, filter_: dict[str, Any], update: dict[str, Any], upsert: bool = False
    ) -> _UpdateResult:
        self._record("update_one", filter=filter_, update=update, upsert=upsert)
        return self._apply_update_one(filter_, update, upsert)

    async def find_one_and_update(
        self,
        filter_: dict[str, Any],
        update: dict[str, Any],
        return_document: bool = ReturnDocument.BEFORE,
    ) -> dict[str, Any] | None:
        self._record(
            "find_one_and_update", filter=filter_, update=update, return_document=return_document
        )
        matched = self._find_docs(filter_)
        if not matched:
            return None
        doc = matched[0]
        before = copy.deepcopy(doc)
        if isinstance(update, list):
            _apply_pipeline_update(doc, update)
        else:
            _apply_update(doc, update, insert=False)
        return copy.deepcopy(doc) if return_document == ReturnDocument.AFTER else before

    async def bulk_write(self, requests: list[Any], ordered: bool = True) -> _BulkWriteResult:
        if ordered:
            raise NotImplementedError(
                "FakeCollection: ordered bulk_write not implemented (src always uses ordered=False)"
            )
        recorded = []
        for request in requests:
            if type(request).__name__ != "UpdateOne":
                raise NotImplementedError(
                    f"FakeCollection: bulk op {type(request).__name__} not implemented"
                )
            # pymongo.UpdateOne exposes no public accessors; conformance pins these.
            # _upsert is None (not False) when unspecified — normalize for stable ops.
            recorded.append(
                {
                    "filter": request._filter,
                    "update": request._doc,
                    "upsert": bool(request._upsert),
                }
            )
        self._record("bulk_write", ops=recorded, ordered=ordered)

        matched = modified = upserted = 0
        write_errors = []
        for index, op in enumerate(recorded):
            try:
                result = self._apply_update_one(op["filter"], op["update"], op["upsert"])
            except DuplicateKeyError as exc:
                write_errors.append({"index": index, "code": 11000, "errmsg": str(exc)})
                continue
            matched += result.matched_count
            modified += result.modified_count
            upserted += int(result.upserted_id is not None)
        if write_errors:
            raise BulkWriteError(
                {"writeErrors": write_errors, "nMatched": matched, "nModified": modified}
            )
        return _BulkWriteResult(matched, modified, upserted)


class FakeDatabase:
    """Minimal ``get_db()`` stand-in: name → FakeCollection, created lazily."""

    def __init__(self) -> None:
        self.collections: dict[str, FakeCollection] = {}

    def __getitem__(self, name: str) -> FakeCollection:
        if name not in self.collections:
            self.collections[name] = FakeCollection(name)
        return self.collections[name]
