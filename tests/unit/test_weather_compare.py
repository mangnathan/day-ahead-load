from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from day_ahead_load import weather_compare as wc
from day_ahead_load.weather_points import POINTS

PARIS_POINT = POINTS[0]


def write_run(root: Path, run: str, values: list[float]) -> None:
    times = pd.date_range(f"{run} 00:00", periods=len(values), freq="1h")
    payload = {
        "timezone": "GMT",
        "utc_offset_seconds": 0,
        "hourly": {"time": [t.strftime("%Y-%m-%dT%H:%M") for t in times], "temperature_2m": values},
    }
    path = root / "ecmwf_00utc" / PARIS_POINT.commune / f"run-{run}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"reponse": payload}), encoding="utf-8")


def test_day_d_comes_from_the_run_of_d_minus_1_and_follows_paris_time(tmp_path: Path) -> None:
    write_run(tmp_path, "2024-03-30", list(np.arange(72.0)))
    # 31/03/2024 : passage à l'heure d'été, 23 heures à Paris (23 h UTC le 30 → 21 h UTC le 31).
    forecast = wc.forecast_series(tmp_path, PARIS_POINT, [date(2024, 3, 31)])
    assert len(forecast) == 23
    assert forecast["echeance_h"].min() == 23 and forecast["echeance_h"].max() == 45


def test_autumn_day_has_25_hours() -> None:
    index = pd.date_range("2024-10-26 12:00", periods=60, freq="1h", tz="UTC")
    frame = pd.DataFrame({"x": 0.0}, index=index)
    assert len(wc.paris_day(frame, date(2024, 10, 27))) == 25


def test_gap_uses_common_hours_only() -> None:
    index = pd.date_range("2024-01-01", periods=4, freq="1h", tz="UTC")
    forecast = pd.Series([1.0, 2.0, np.nan, 4.0], index=index)
    reference = pd.Series([0.0, 0.0, 0.0, np.nan], index=index)
    result = wc.gap(forecast, reference)
    assert result["heures"] == 2 and result["mae"] == 1.5 and result["biais"] == 1.5


def test_index_is_missing_when_a_point_is_missing() -> None:
    index = pd.date_range("2024-01-01", periods=2, freq="1h", tz="UTC")
    a, b = POINTS[0], POINTS[1]
    series = {a: pd.Series([10.0, 10.0], index=index), b: pd.Series([20.0, np.nan], index=index)}
    out = wc.weighted_index(series, {a.region: 0.75, b.region: 0.25})
    assert out.iloc[0] == pytest.approx(12.5)
    assert np.isnan(out.iloc[1])


def test_overlapping_chunks_are_refused(tmp_path: Path) -> None:
    for name in ("a", "b"):
        payload = {
            "timezone": "GMT",
            "utc_offset_seconds": 0,
            "hourly": {"time": ["2024-01-01T00:00"], "temperature_2m": [1.0]},
        }
        path = tmp_path / "era5" / PARIS_POINT.commune / f"{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"reponse": payload}), encoding="utf-8")
    with pytest.raises(ValueError, match="recouvrent"):
        wc.archive_series(tmp_path, "era5", PARIS_POINT)
