"""Example queries that combine several catalog objects.

Each query is defined once here and listed both on the object that drives it and
in the schema-level ``vgi.example_queries``.
"""

from __future__ import annotations

from vgi_f1.functions import Example

SPRINT_VS_GRAND_PRIX_WINNERS = Example(
    "Sprint winner against Grand Prix winner on every 2024 sprint weekend.",
    "WITH sp AS (SELECT round, race_name, driver_name AS sprint_winner "
    "FROM f1.main.sprint_results(2024) WHERE position = 1), "
    "gp AS (SELECT round, driver_name AS grand_prix_winner "
    "FROM f1.main.race_results(2024) WHERE position = 1) "
    "SELECT round, race_name, sprint_winner, grand_prix_winner, "
    "sprint_winner = grand_prix_winner AS won_both "
    "FROM sp JOIN gp USING (round) ORDER BY round",
)

STINT_PACE = Example(
    "Max Verstappen's pace per stint in the 2024 Chinese Grand Prix, splitting his laps at "
    "each pit stop and leaving out in- and out-laps.",
    "WITH stops AS (SELECT lap FROM f1.main.pit_stops(2024, 5) WHERE driver_id = 'max_verstappen'), "
    "laps AS (SELECT l.lap, l.lap_time_seconds, "
    "1 + (SELECT count(*) FROM stops WHERE stops.lap < l.lap) AS stint "
    "FROM f1.main.lap_times(2024, 5, driver_id := 'max_verstappen') l) "
    "SELECT stint, min(lap) AS first_lap, max(lap) AS last_lap, "
    "min(lap_time_seconds) AS best_lap_seconds, median(lap_time_seconds) AS median_lap_seconds "
    "FROM laps WHERE lap NOT IN (SELECT lap FROM stops) AND lap NOT IN (SELECT lap + 1 FROM stops) "
    "GROUP BY stint ORDER BY stint",
)

TYRE_STRATEGY_BY_FINISH = Example(
    "Every driver's tyre sequence in the 2024 Bahrain Grand Prix (session 9472), in finishing order.",
    "SELECT r.position, d.name_acronym, d.team_name, count(*) AS stints, "
    "string_agg(st.compound, ' > ' ORDER BY st.stint_number) AS strategy "
    "FROM f1.main.session_stints(9472) st "
    "JOIN f1.main.session_drivers(9472) d USING (driver_number) "
    "JOIN f1.main.session_result(9472) r USING (driver_number) "
    "GROUP BY r.position, d.name_acronym, d.team_name "
    "ORDER BY r.position NULLS LAST, d.name_acronym",
)

STANDINGS_WITH_LAST_RACE = Example(
    "Championship top ten with each driver's finish and points in the latest Grand Prix.",
    "SELECT s.position, s.driver_name, s.points, r.position AS last_race_finish, "
    "coalesce(r.points, 0) AS last_race_points "
    "FROM f1.main.current_driver_standings s "
    "LEFT JOIN f1.main.last_race_results r USING (driver_id) "
    "ORDER BY s.position LIMIT 10",
)

COMPOSED_EXAMPLES = (
    STANDINGS_WITH_LAST_RACE,
    SPRINT_VS_GRAND_PRIX_WINNERS,
    STINT_PACE,
    TYRE_STRATEGY_BY_FINISH,
)
