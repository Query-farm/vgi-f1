"""Run every table function's process() over recorded fixtures, without a SQL engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pyarrow as pa
import pytest

from vgi_f1 import api, ergast, openf1
from vgi_f1.functions import PageState
from vgi_f1.worker import F1_CATALOG


class _Out:
    def __init__(self) -> None:
        self.batches: list[pa.RecordBatch] = []
        self.cache_controls: list[Any] = []
        self.finished = False

    def emit(self, batch: pa.RecordBatch, *, cache_control: Any = None) -> None:
        self.batches.append(batch)
        self.cache_controls.append(cache_control)

    def finish(self) -> None:
        self.finished = True


@dataclass
class _Params:
    args: Any
    output_schema: pa.Schema


def _run(function: type, args: Any, schema: pa.Schema | None = None, *, batches: int = 1) -> _Out:
    """Drive process() tick by tick, as the framework does, until the scan finishes."""
    out = _Out()
    params = _Params(args=args, output_schema=schema or function.FIXED_SCHEMA)
    state = function.initial_state(params)
    for _tick in range(50):
        function.process(params, state, out)
        if out.finished:
            break
    assert out.finished
    assert len(out.batches) == batches
    return out


CASES = [
    (ergast.CurrentDriverStandingsFunction, None, 5),
    (ergast.CurrentConstructorStandingsFunction, None, 4),
    (ergast.CurrentScheduleFunction, None, 3),
    (ergast.LastRaceResultsFunction, None, 5),
    (ergast.SeasonsFunction, None, 3),
    (ergast.ScheduleFunction, ergast.SeasonArgs(season=2024), 3),
    (ergast.ConstructorStandingsFunction, ergast.SeasonRoundArgs(season=2024, round=None), 3),
    (ergast.DriverStandingsFunction, ergast.SeasonRoundArgs(season=2024, round=None), 3),
    (ergast.RaceResultsFunction, ergast.SeasonRoundArgs(season=2024, round=None), 6),
    (ergast.SprintResultsFunction, ergast.SeasonRoundArgs(season=2024, round=None), 3),
    (ergast.QualifyingResultsFunction, ergast.SeasonRoundArgs(season=2024, round=5), 3),
    (ergast.LapTimesFunction, ergast.LapArgs(season=2024, round=5, driver_id=None), 6),
    (ergast.LapTimesFunction, ergast.LapArgs(season=2024, round=5, driver_id="max_verstappen"), 6),
    (ergast.PitStopsFunction, ergast.RaceArgs(season=2024, round=5), 4),
    (ergast.DriversFunction, ergast.OptionalSeasonArgs(season=2024), 3),
    (ergast.ConstructorsFunction, ergast.OptionalSeasonArgs(season=2024), 3),
    (ergast.CircuitsFunction, ergast.OptionalSeasonArgs(season=2024), 3),
    (ergast.DriverResultsFunction, ergast.DriverResultsArgs(driver_id="hamilton", season=None), 2),
    (openf1.MeetingsFunction, openf1.MeetingArgs(season=2024), 2),
    (openf1.SessionsFunction, openf1.SessionListArgs(season=2024, session_name="Race"), 2),
    (openf1.SessionDriversFunction, openf1.SessionArgs(session_key=9472), 3),
    (openf1.SessionResultFunction, openf1.SessionArgs(session_key=9472), 6),
    (openf1.SessionResultFunction, openf1.SessionArgs(session_key=9468), 3),
    (openf1.SessionLapsFunction, openf1.SessionDriverArgs(session_key=9472, driver_number=None), 3),
    (openf1.SessionStintsFunction, openf1.SessionArgs(session_key=9472), 3),
    (openf1.SessionPitsFunction, openf1.SessionArgs(session_key=9472), 3),
    (openf1.SessionWeatherFunction, openf1.SessionArgs(session_key=9472), 3),
    (openf1.RaceControlFunction, openf1.SessionArgs(session_key=9472), 3),
    (openf1.TeamRadioFunction, openf1.SessionDriverArgs(session_key=9472, driver_number=None), 3),
]


@pytest.mark.parametrize(
    ("function", "args", "rows"), CASES, ids=lambda value: getattr(value, "__name__", None)
)
def test_function_emits_fixture_rows(function: type, args: Any, rows: int, fixture_transport) -> None:
    paged = function is ergast.RaceResultsFunction and args.round is None
    out = _run(function, args, batches=2 if paged else 1)
    assert sum(batch.num_rows for batch in out.batches) == rows
    assert out.batches[0].schema == function.FIXED_SCHEMA
    assert out.cache_controls[0] is not None
    assert out.cache_controls[0].ttl > 0


def test_every_catalog_function_has_a_fixture_case() -> None:
    covered = {function.Meta.name for function, _args, _rows in CASES}
    assert covered == {function.Meta.name for function in F1_CATALOG.schemas[0].functions}


def test_projection_follows_the_bound_schema(fixture_transport) -> None:
    schema = pa.schema([ergast.CurrentDriverStandingsFunction.FIXED_SCHEMA.field("driver_id")])
    out = _run(ergast.CurrentDriverStandingsFunction, None, schema)
    assert out.batches[0].schema.names == ["driver_id"]


def test_round_and_driver_filters_reach_the_url(fixture_transport) -> None:
    _run(ergast.QualifyingResultsFunction, ergast.SeasonRoundArgs(season=2024, round=5))
    _run(ergast.LapTimesFunction, ergast.LapArgs(season=2024, round=5, driver_id="max_verstappen"))
    _run(openf1.SessionLapsFunction, openf1.SessionDriverArgs(session_key=9472, driver_number=1))
    paths = [request.url.path for request in fixture_transport]
    assert "/ergast/f1/2024/5/qualifying.json" in paths
    assert "/ergast/f1/2024/5/drivers/max_verstappen/laps.json" in paths
    assert fixture_transport[-1].url.params["driver_number"] == "1"


def test_null_optional_filters_are_omitted(fixture_transport) -> None:
    _run(openf1.SessionsFunction, openf1.SessionListArgs(season=2024, session_name=None))
    assert "session_name" not in fixture_transport[-1].url.params
    assert fixture_transport[-1].url.params["year"] == "2024"


def test_paged_scan_streams_one_batch_per_upstream_page(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = {
        0: api.JolpicaPage(items=[{"season": "1950", "url": "a"}], ttl=60, context={}, next_offset=100),
        100: api.JolpicaPage(items=[{"season": "1951", "url": "b"}], ttl=60, context={}, next_offset=None),
    }
    offsets: list[int] = []

    def fake_page(path: str, list_key: str, *, offset: int, historical: bool) -> api.JolpicaPage:
        offsets.append(offset)
        return pages[offset]

    monkeypatch.setattr(api, "fetch_jolpica_page", fake_page)
    out = _run(ergast.SeasonsFunction, None, batches=2)
    assert offsets == [0, 100]
    assert [batch.column("season").to_pylist() for batch in out.batches] == [[1950], [1951]]
    assert out.cache_controls[0].ttl == 60
    assert out.cache_controls[1] is None


def test_page_state_round_trips_for_http_transport() -> None:
    state = PageState(offset=300)
    assert PageState.deserialize_from_bytes(state.serialize_to_bytes()).offset == 300


def test_unknown_session_returns_no_rows(fixture_transport) -> None:
    out = _run(openf1.SessionStintsFunction, openf1.SessionArgs(session_key=1))
    assert out.batches[0].num_rows == 0


def test_required_and_optional_arguments() -> None:
    def parameters(function: type) -> dict[str, bool]:
        return {parameter.name: parameter.required for parameter in function.get_metadata().parameters}

    assert parameters(ergast.RaceResultsFunction) == {"season": True, "round": False}
    assert parameters(ergast.LapTimesFunction) == {"season": True, "round": True, "driver_id": False}
    assert parameters(ergast.DriverResultsFunction) == {"driver_id": True, "season": False}
    assert parameters(openf1.SessionsFunction) == {"season": True, "session_name": False}
    assert parameters(openf1.TeamRadioFunction) == {"session_key": True, "driver_number": False}
    assert parameters(ergast.CurrentDriverStandingsFunction) == {}
