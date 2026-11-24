from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from day_ahead_load import assessment as ass

FIRST = date(2024, 3, 15)


def half_hours(weeks: int) -> list[date]:
    return [FIRST + timedelta(days=k // 48) for k in range(weeks * 7 * 48)]


def test_ratio_of_steady_errors_has_a_tight_interval() -> None:
    days = half_hours(3)
    truth = np.full(len(days), 100.0)
    ratio, low, high = ass.ratio_interval(
        truth, np.full(len(days), 102.0), np.full(len(days), 104.0), days, FIRST
    )
    assert (ratio, low, high) == pytest.approx((0.5, 0.5, 0.5))


def test_ratio_interval_widens_when_weeks_disagree() -> None:
    days = half_hours(4)
    truth = np.full(len(days), 100.0)
    week = np.asarray([(d - FIRST).days // 7 for d in days])
    model = np.where(week % 2 == 0, 101.0, 104.0)
    ratio, low, high = ass.ratio_interval(truth, model, np.full(len(days), 105.0), days, FIRST)
    assert ratio == pytest.approx(0.5)
    assert low < ratio < high


def test_blocks_refuse_days_before_the_first_block() -> None:
    with pytest.raises(ValueError, match="antérieur"):
        ass.blocks([FIRST - timedelta(days=1)], FIRST)


def test_breakdown_gives_mape_and_signed_bias_per_group() -> None:
    truth = np.array([100.0, 100.0, 200.0, 200.0])
    forecast = np.array([110.0, 90.0, 220.0, 220.0])
    out = ass.breakdown(truth, forecast, ["a", "a", "b", "b"])
    assert out.loc["a", "mape_pct"] == pytest.approx(10.0)
    assert out.loc["a", "biais_mw"] == pytest.approx(0.0)
    assert out.loc["b", "biais_mw"] == pytest.approx(20.0)
    assert out.loc["b", "biais_pct"] == pytest.approx(10.0)
    assert out["demi_heures"].tolist() == [2, 2]


def test_seasons_are_meteorological() -> None:
    assert ass.season([12, 2, 3, 6, 9, 11]) == [
        "hiver",
        "hiver",
        "printemps",
        "ete",
        "automne",
        "automne",
    ]


def test_temperature_bands_put_each_edge_in_the_band_above() -> None:
    values = np.array([-0.1, 0.0, 4.9, 5.0, 14.9, 15.0, 30.0])
    assert ass.temperature_band(values) == ["< 0", "0-5", "0-5", "5-10", "10-15", "> 15", "> 15"]
    with pytest.raises(ValueError, match="manquante"):
        ass.temperature_band(np.array([np.nan]))


def test_permutation_importance_is_zero_for_an_unused_variable() -> None:
    rng = np.random.default_rng(0)
    x = pd.DataFrame({"utile": rng.normal(size=500), "inutile": rng.normal(size=500)})
    truth = 1_000.0 + 50.0 * x["utile"].to_numpy()

    def predict(frame: pd.DataFrame) -> np.ndarray:
        return np.asarray(1_000.0 + 50.0 * frame["utile"].to_numpy())

    out = ass.permutation_importance(predict, x, truth)
    assert out["inutile"] == 0.0
    assert out["utile"] > 1.0
