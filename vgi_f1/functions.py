"""Shared construction of fixed-schema, read-only F1 table functions.

Every F1 function has the same shape: validate typed arguments, fetch an
upstream resource (rate-limited and cached by :mod:`vgi_f1.api`), flatten it
to the function's Arrow schema, and emit it with the cache lifetime that
applies to that resource. Paged Jolpica-F1 resources stream one batch per
upstream page, carrying the next offset in serializable scan state, so the
first rows arrive after one request even when a season needs several pages.
:func:`table_function` builds those classes so each function's definition only
states what differs: its name, arguments, schema, fetcher, and metadata.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar

import pyarrow as pa
from vgi.cache_control import CacheControl
from vgi.metadata import FunctionExample
from vgi.table_function import (
    ProcessParams,
    TableCardinality,
    TableFunctionGenerator,
    bind_fixed_schema,
    init_single_worker,
)
from vgi_rpc import ArrowSerializableDataclass
from vgi_rpc.rpc import OutputCollector

from vgi_f1 import api
from vgi_f1.meta import result_columns_schema
from vgi_f1.schemas import Row, batch_from_rows


@dataclass(frozen=True, slots=True)
class Fetched:
    """Flattened rows plus the freshness lifetime, in seconds, to advertise."""

    rows: list[Row]
    ttl: int


@dataclass(frozen=True, slots=True)
class Paged:
    """A Jolpica-F1 resource to stream page by page through ``flatten``."""

    path: str
    list_key: str
    flatten: Callable[[Any], list[Row]]
    historical: bool = False


@dataclass(kw_only=True)
class PageState(ArrowSerializableDataclass):
    """Scan position carried between ``process()`` ticks (and HTTP requests)."""

    offset: int = 0


@dataclass(frozen=True, slots=True)
class Example:
    """One documented example query."""

    description: str
    sql: str


def _cache_control(ttl: int) -> CacheControl | None:
    return CacheControl(ttl=ttl) if ttl > 0 else None


def emit(rows: Sequence[Row], ttl: int, output_schema: pa.Schema, out: OutputCollector) -> None:
    """Emit rows as one batch in the bound column order and finish the scan."""
    out.emit(batch_from_rows(rows, output_schema), cache_control=_cache_control(ttl))
    out.finish()


def emit_page(source: Paged, state: PageState, output_schema: pa.Schema, out: OutputCollector) -> None:
    """Emit the page at ``state.offset``; finish after the last page, else advance the offset."""
    page = api.fetch_jolpica_page(
        source.path, source.list_key, offset=state.offset, historical=source.historical
    )
    # Cache policy is advertised on the first batch of a result.
    cache_control = _cache_control(page.ttl) if state.offset == 0 else None
    out.emit(batch_from_rows(source.flatten(page.items), output_schema), cache_control=cache_control)
    if page.next_offset is None:
        out.finish()
    else:
        state.offset = page.next_offset


def table_function(
    *,
    name: str,
    args: type | None,
    schema: pa.Schema,
    fetch: Callable[[Any], Fetched | Paged],
    title: str,
    description: str,
    category: str,
    doc_llm: str,
    doc_md: str,
    examples: Sequence[Example],
    estimate: int,
    maximum: int,
    source: str,
) -> type[TableFunctionGenerator[Any]]:
    """Build a decorated ``TableFunctionGenerator`` class for one F1 resource."""
    meta_tags = {
        "provider": source,
        "vgi.category": category,
        "vgi.title": title,
        "vgi.result_columns_schema": result_columns_schema(schema),
        "vgi.doc_llm": doc_llm,
        "vgi.doc_md": doc_md,
        "vgi.example_queries": json.dumps(
            [{"description": example.description, "sql": example.sql} for example in examples]
        ),
    }
    function_examples = [
        FunctionExample(sql=example.sql, description=example.description.removesuffix("."))
        for example in examples
    ]
    categories = ["formula-1", category]

    class _Function(TableFunctionGenerator[args, PageState]):  # type: ignore[valid-type]
        FIXED_SCHEMA: ClassVar[pa.Schema] = schema

        class Meta:
            """Function discovery metadata."""

        Meta.name = name
        Meta.description = description
        Meta.categories = categories
        Meta.projection_pushdown = True
        Meta.tags = meta_tags
        Meta.examples = function_examples

        @classmethod
        def cardinality(cls, params: object) -> TableCardinality:
            """Return the planner estimate for this resource."""
            return TableCardinality(estimate=estimate, max=maximum)

        @classmethod
        def initial_state(cls, params: ProcessParams[Any]) -> PageState:
            """Start every scan at the first upstream page."""
            return PageState()

        @classmethod
        def process(cls, params: ProcessParams[Any], state: PageState, out: OutputCollector) -> None:
            """Fetch, flatten, and emit the resource (one upstream page per tick when paged)."""
            fetched = fetch(params.args)
            if isinstance(fetched, Paged):
                emit_page(fetched, state, params.output_schema, out)
            else:
                emit(fetched.rows, fetched.ttl, params.output_schema, out)

    class_name = "".join(part.capitalize() for part in name.split("_")) + "Function"
    _Function.__name__ = class_name
    _Function.__qualname__ = class_name
    _Function.__doc__ = description
    return init_single_worker(bind_fixed_schema(_Function))
