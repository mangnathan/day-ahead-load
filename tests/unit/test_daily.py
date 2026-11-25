from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from day_ahead_load import daily, frozen
from day_ahead_load import modelling as md
from day_ahead_load import table as tb
from day_ahead_load import weather_features as wf

DAY = date(2026, 11, 26)


def synthetic_run(run_day: date, value: float) -> pd.DataFrame:
    hours = pd.date_range(pd.Timestamp(run_day, tz="UTC"), periods=72, freq="h")
    hour_of_day = hours.hour.to_numpy(dtype=float)
    return pd.DataFrame(
        {
            "temperature_2m": value + 0.1 * hour_of_day,
            "cloud_cover": 50.0,
            "wind_speed_10m": 5.0,
            "shortwave_radiation": np.maximum(0.0, 300.0 - 25.0 * np.abs(hour_of_day - 12.0)),
        },
        index=hours,
    )


def runs_until(last: date, poison_after: date | None = None) -> pd.DataFrame:
    runs = {}
    for k in range(daily.RUN_DAYS_BACK, -2, -1):  # de D-4 à D+1
        run_day = DAY - timedelta(days=k)
        if run_day > last:
            continue
        value = 1e9 if poison_after and run_day > poison_after else 8.0 + k
        runs[run_day] = synthetic_run(run_day, value)
    return daily.runs_frame(runs)


@pytest.fixture(scope="module")
def model_text() -> str:
    rng = np.random.default_rng(0)
    x = pd.DataFrame({name: rng.normal(size=2_000) for name in md.FEATURES})
    y = pd.Series(50_000.0 + 1_000.0 * x["temperature_2m"])
    return str(md.fit(x, y).model_to_string())


OFFSETS = {
    str(s): {
        "0.025": -2_000.0,
        "0.1": -1_000.0,
        "0.5": 0.0,
        "0.9": 1_000.0,
        "0.975": 2_000.0,
        "0.4616": -50.0,
    }
    for s in range(48)
}


def test_delivered_day_and_deadline_follow_paris_time() -> None:
    assert daily.delivered_day(datetime(2026, 11, 25, 8, 20, tzinfo=UTC)) == DAY
    assert daily.deadline(DAY) == pd.Timestamp("2026-11-25T11:00Z")  # heure d'hiver
    assert daily.deadline(date(2026, 7, 1)) == pd.Timestamp("2026-06-30T10:00Z")  # heure d'été


def test_status_and_run_readiness() -> None:
    assert daily.on_time(datetime(2026, 11, 25, 10, 59, tzinfo=UTC), DAY) == "à l'heure"
    assert daily.on_time(datetime(2026, 11, 25, 11, 1, tzinfo=UTC), DAY) == "en retard"
    deposit = datetime(2026, 11, 25, 6, 30, tzinfo=UTC)
    assert not daily.run_ready(datetime(2026, 11, 25, 8, 20, tzinfo=UTC), deposit)
    assert daily.run_ready(datetime(2026, 11, 25, 8, 31, tzinfo=UTC), deposit)


def test_end_to_end_forecast_for_a_given_day(model_text: str) -> None:
    inputs = daily.Inputs(DAY, runs_until(DAY - timedelta(days=1)), 52_000.0)
    out = daily.forecast(inputs, model_text, OFFSETS)
    assert isinstance(out, pd.DataFrame)
    assert len(out) == 48
    assert (out["q0.025"] <= out["q0.1"]).all() and (out["q0.9"] <= out["q0.975"]).all()
    assert np.allclose(out["achat_q"], out["prevision"] - 50.0)
    content = daily.core(DAY, out, inputs, {"modele_sha256": "x"})
    assert content["calculs_meteo_utilises"]["temperature_2m"][-1] == "2026-11-25T00:00Z"
    # Le lissage sur 72 h lit aussi les premières heures des calculs des jours précédents.
    assert content["calculs_meteo_utilises"]["temperature_2m"][0] == "2026-11-22T00:00Z"
    assert content["calculs_meteo_utilises"]["cloud_cover"] == ["2026-11-25T00:00Z"]
    assert len(daily.content_sha256(content)) == 64
    assert daily.content_sha256(content) == daily.content_sha256(dict(content))


def test_nothing_published_after_noon_the_day_before_changes_the_forecast(
    model_text: str,
) -> None:
    clean = daily.Inputs(DAY, runs_until(DAY - timedelta(days=1)), 52_000.0)
    with_later = daily.Inputs(
        DAY, runs_until(DAY + timedelta(days=1), DAY - timedelta(days=1)), 52_000.0
    )
    a = daily.forecast(clean, model_text, OFFSETS)
    b = daily.forecast(with_later, model_text, OFFSETS)
    assert isinstance(a, pd.DataFrame) and isinstance(b, pd.DataFrame)
    pd.testing.assert_frame_equal(a, b)


def test_a_missing_input_gives_an_absence_not_a_forecast(model_text: str) -> None:
    no_level = daily.forecast(
        daily.Inputs(DAY, runs_until(DAY - timedelta(days=1)), None), model_text, OFFSETS
    )
    assert isinstance(no_level, daily.Absence) and "niveau" in no_level.cause
    only_last_run = daily.runs_frame(
        {DAY - timedelta(days=1): synthetic_run(DAY - timedelta(days=1), 8.0)}
    )
    short = daily.forecast(daily.Inputs(DAY, only_last_run, 52_000.0), model_text, OFFSETS)
    assert isinstance(short, daily.Absence) and "temperature_lissee_72h" in short.cause


def test_a_forecast_file_is_never_overwritten(tmp_path: Path) -> None:
    path = tmp_path / "previsions" / f"{DAY}.json"
    assert daily.write_once(path, "premiere")
    assert not daily.write_once(path, "seconde")
    assert path.read_text(encoding="utf-8") == "premiere"


def test_the_level_is_the_only_path_from_test_period_consumption() -> None:
    stamps = pd.date_range("2025-06-01T00:00Z", "2026-11-01T00:00Z", freq="30min")
    target = pd.Series(50_000.0, index=stamps)
    poisoned = target.copy()
    in_test = (stamps >= pd.Timestamp("2025-09-01", tz="UTC")) & (
        stamps < pd.Timestamp("2026-09-01", tz="UTC")
    )
    poisoned[in_test] = 1e9
    level = float(tb.level_by_day(target, [DAY]).iloc[0])
    level_poisoned = float(tb.level_by_day(poisoned, [DAY]).iloc[0])
    runs = runs_until(DAY - timedelta(days=1))
    a, _ = daily.features(daily.Inputs(DAY, runs, level))
    b, _ = daily.features(daily.Inputs(DAY, runs, level_poisoned))
    assert level != level_poisoned
    others = [c for c in a.columns if c != tb.LEVEL]
    pd.testing.assert_frame_equal(a[others], b[others])
    assert set(wf.VARIABLES) <= set(others)
    assert frozen.PURCHASE_Q == 0.4616


def test_levels_are_filled_only_for_decisions_still_to_come() -> None:
    now = datetime(2026, 12, 9, 6, 0, tzinfo=UTC)
    existing = {"2026-12-05": None, "2026-12-08": 51_000.0, "2026-12-15": None}
    computed = {
        "2026-12-05": 52_000.0,
        "2026-12-08": 99_999.0,
        "2026-12-15": 52_500.0,
        "2026-12-20": 52_600.0,
    }
    out = daily.merge_levels(existing, computed, now)
    assert out["2026-12-05"] is None  # décision passée : jamais rattrapée
    assert out["2026-12-08"] == 51_000.0  # valeur publiée : inchangée
    assert out["2026-12-15"] == 52_500.0 and out["2026-12-20"] == 52_600.0
