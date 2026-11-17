from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from day_ahead_load import modelling as md
from day_ahead_load import table as tb


def tiny_table(first: date, days: int, period: str = "entrainement") -> pd.DataFrame:
    rng = np.random.default_rng(0)
    rows = []
    for k in range(days):
        day = first + timedelta(days=k)
        for slot in range(48):
            row: dict[str, object] = {name: float(rng.normal()) for name in md.FEATURES}
            temperature = float(rng.normal())
            row.update(
                {
                    "jour": day,
                    "periode": period,
                    "demi_heure": slot,
                    "temperature_2m": temperature,
                    tb.TARGET: 50_000.0 + 100.0 * temperature,
                }
            )
            rows.append(row)
    return pd.DataFrame(rows)


def test_mape_ignores_half_hours_without_target() -> None:
    truth = pd.Series([100.0, np.nan, 200.0])
    assert md.mape(truth, np.array([110.0, 5.0, 180.0])) == pytest.approx(10.0)


def test_cross_validation_refuses_validation_rows() -> None:
    table = pd.concat(
        [tiny_table(date(2018, 12, 30), 3), tiny_table(date(2024, 3, 15), 1, "validation")]
    )
    with pytest.raises(ValueError, match="entraînement"):
        md.cross_validate(table, years=[2019])


FIRST = date(2024, 3, 15)


def weeks(count: int) -> pd.Series:
    """Demi-heures de `count` semaines complètes à partir du premier jour de la validation."""
    return pd.Series([FIRST + timedelta(days=k // 48) for k in range(count * 7 * 48)])


def test_identical_forecasts_give_a_zero_gap_and_keep_the_simple_option() -> None:
    days = weeks(3)
    truth = pd.Series(np.full(len(days), 100.0))
    gap = md.paired_gap(truth, np.full(len(days), 105.0), np.full(len(days), 105.0), days, FIRST)
    assert (gap.difference, gap.low, gap.high) == (0.0, 0.0, 0.0)
    assert not gap.complex_retained


def test_a_steady_gain_beyond_one_percent_retains_the_complex_option() -> None:
    days = weeks(3)
    truth = pd.Series(np.full(len(days), 100.0))
    gap = md.paired_gap(truth, np.full(len(days), 105.0), np.full(len(days), 102.0), days, FIRST)
    assert gap.difference == pytest.approx(-3.0)
    assert gap.high == pytest.approx(-3.0)
    assert gap.relative_gain == pytest.approx(0.6)
    assert gap.complex_retained


def test_a_large_gain_carried_by_some_weeks_only_is_treated_as_noise() -> None:
    days = weeks(3)
    truth = pd.Series(np.full(len(days), 100.0))
    week = np.asarray([(d - FIRST).days // 7 for d in days])
    complex_ = np.where(week == 1, 109.0, 101.0)  # mieux deux semaines, pire la troisième
    gap = md.paired_gap(truth, np.full(len(days), 105.0), complex_, days, FIRST)
    assert gap.relative_gain > md.MIN_RELATIVE_GAIN
    assert gap.low < 0 < gap.high
    assert not gap.complex_retained


def test_paired_gap_ignores_half_hours_without_target_and_is_reproducible() -> None:
    days = weeks(2)
    truth = pd.Series(np.full(len(days), 100.0))
    truth.iloc[0] = np.nan
    simple = np.full(len(days), 105.0)
    complex_ = np.where(np.arange(len(days)) % 2 == 0, 103.0, 106.0)
    assert md.paired_gap(truth, simple, complex_, days, FIRST) == md.paired_gap(
        truth, simple, complex_, days, FIRST
    )


def test_validation_forecast_refuses_test_rows_and_starts_training_where_asked() -> None:
    table = pd.concat(
        [tiny_table(date(2016, 12, 30), 4), tiny_table(date(2024, 3, 15), 1, "validation")]
    )
    forecast, train_rows = md.validation_forecast(table, date(2017, 1, 1))
    assert train_rows == 2 * 48
    assert len(forecast) == 48
    with pytest.raises(ValueError, match="validation"):
        md.validation_forecast(
            pd.concat([table, tiny_table(date(2025, 9, 1), 1, "test")]), date(2017, 1, 1)
        )


def test_cross_validation_trains_only_on_earlier_days_and_is_reproducible() -> None:
    table = tiny_table(date(2018, 12, 1), 62)
    first = md.cross_validate(table, years=[2019])
    assert first == md.cross_validate(table, years=[2019])
    assert first[0].train_rows == 31 * 48
    assert first[0].scored_rows == 31 * 48
