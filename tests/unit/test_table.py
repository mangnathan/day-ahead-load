from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from day_ahead_load import table as tb
from day_ahead_load import weather_features as wf

PARIS = "Europe/Paris"


def instants(first: str, last: str, value: float = 50_000.0) -> pd.DataFrame:
    """Sortie simulée de diagnostics.with_local_instants : demi-heures consolidées."""
    local = pd.date_range(
        pd.Timestamp(first).tz_localize(PARIS),
        pd.Timestamp(last).tz_localize(PARIS),
        freq="30min",
        inclusive="left",
    )
    return pd.DataFrame({"nature": "Données consolidées", "instant": local, "consommation": value})


def flat_weather(first: date, last: date) -> tuple[pd.DataFrame, pd.DataFrame]:
    index = pd.date_range(
        pd.Timestamp(first - timedelta(days=4), tz="UTC"),
        pd.Timestamp(last + timedelta(days=2), tz="UTC"),
        freq="h",
    )
    archive = pd.DataFrame({name: 10.0 for name in wf.VARIABLES}, index=index)
    frames = {}
    day = first - timedelta(days=4)
    while day <= last:
        hours = pd.date_range(pd.Timestamp(day, tz="UTC"), periods=72, freq="h")
        frames[day] = pd.DataFrame({name: 5.0 for name in wf.VARIABLES}, index=hours)
        day += timedelta(days=1)
    return archive, pd.concat(frames, names=["calcul", "heure"])


def test_grid_has_46_and_50_half_hours_on_clock_change_days() -> None:
    grid = tb.half_hour_grid(date(2025, 3, 30), date(2025, 10, 26))
    sizes = grid.groupby("jour").size()
    assert sizes[date(2025, 3, 30)] == 46
    assert sizes[date(2025, 10, 26)] == 50
    assert sizes[date(2025, 6, 1)] == 48


def test_level_uses_the_52_weeks_before_the_end_of_published_consolidated_data() -> None:
    old = instants("2023-01-01", "2024-04-02", value=1.0)
    window = instants("2024-04-02", "2025-04-01", value=2.0)
    unpublished = instants("2025-04-01", "2025-07-01", value=1e9)
    target = tb.target_utc(pd.concat([old, window, unpublished], ignore_index=True))
    # Décision le 09/06/2025 à midi : consolidé publié jusqu'au 01/04/2025 exclu (M+3).
    level = tb.level_by_day(target, [date(2025, 6, 10)])
    assert level.iloc[0] == 2.0


def test_level_is_missing_when_the_window_starts_before_the_data() -> None:
    target = tb.target_utc(instants("2024-01-01", "2025-01-01"))
    assert np.isnan(tb.level_by_day(target, [date(2024, 6, 10)]).iloc[0])


def test_test_target_is_masked_unless_opened() -> None:
    first, last = date(2025, 8, 30), date(2025, 9, 2)
    data = instants("2024-01-01", "2025-09-03")
    archive, runs = flat_weather(first, last)
    closed = tb.build(data, archive, runs, first, last)
    test_rows = closed["periode"] == "test"
    assert test_rows.any()
    assert closed.loc[test_rows, tb.TARGET].isna().all()
    assert closed.loc[~test_rows, tb.TARGET].notna().all()
    opened = tb.build(data, archive, runs, first, last, open_test=True)
    assert opened.loc[test_rows, tb.TARGET].notna().all()


def test_training_rows_use_the_archive_and_later_rows_the_forecast() -> None:
    first, last = date(2024, 3, 13), date(2024, 3, 16)
    archive, runs = flat_weather(first, last)
    built = tb.build(instants("2023-01-01", "2024-03-17"), archive, runs, first, last)
    training = built["periode"] == "entrainement"
    assert (built.loc[training, "source_meteo"] == tb.SOURCE_TRAIN).all()
    assert (built.loc[training, wf.TEMPERATURE] == 10.0).all()
    assert (built.loc[~training, "source_meteo"] == tb.SOURCE_FORECAST).all()
    assert (built.loc[~training, wf.TEMPERATURE] == 5.0).all()
