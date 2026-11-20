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


def calendar_table(first: date, days: int, period: str = "entrainement") -> pd.DataFrame:
    """Table fictive au calendrier cohérent : jour de la semaine et mois tirés du jour."""
    table = tiny_table(first, days, period)
    stamps = pd.to_datetime(table["jour"])
    table["jour_semaine"] = stamps.dt.day_of_week.to_numpy()
    table["mois"] = stamps.dt.month.to_numpy()
    for flag in ("ferie", "lundi_pentecote", "pont", "noel"):
        table[flag] = 0.0
    table[tb.LEVEL] = 50_000.0
    return table.reset_index(drop=True)


def test_day_type_puts_holidays_with_sundays_and_keeps_pentecost_monday_working() -> None:
    table = pd.DataFrame(
        {
            "jour_semaine": [0, 5, 5, 6, 0],
            "ferie": [False, False, True, False, False],
            "lundi_pentecote": [False, False, False, False, True],
        }
    )
    assert md.day_type(table).tolist() == [0, 1, 2, 2, 0]


def test_linear_design_crosses_heating_with_the_three_hour_slice_and_the_month() -> None:
    table = calendar_table(date(2017, 2, 6), 1)  # lundi 06/02/2017
    table["temperature_2m"] = 5.0
    means = table[md._linear_inputs(with_level=True)].mean()
    x = md.linear_design(table, means)
    row = x.iloc[13]  # demi-heure 13 : 6 h 30, tranche 6 h-9 h
    assert row["chauffage_tranche_2"] == 10.0
    assert row[[f"chauffage_tranche_{b}" for b in range(8) if b != 2]].eq(0).all()
    assert row["chauffage_mois_02"] == 10.0
    assert (x["climatisation_tranche_2"] == 0).all()
    assert x.shape[1] == 200 and not x.isna().any().any()


def test_linear_design_fills_missing_inputs_with_the_training_mean() -> None:
    table = calendar_table(date(2017, 2, 6), 1)
    means = pd.Series({name: 12.0 for name in md._linear_inputs(with_level=False)})
    table["temperature_lissee_72h"] = np.nan
    x = md.linear_design(table, means)
    assert (x["chauffage_temperature_lissee_72h"] == 3.0).all()
    assert tb.LEVEL not in x.columns


def test_ratio_variant_multiplies_the_predicted_ratio_back_by_the_level() -> None:
    train = calendar_table(date(2017, 1, 2), 28)
    train[tb.LEVEL] = np.linspace(40_000.0, 60_000.0, len(train))
    train[tb.TARGET] = 1.2 * train[tb.LEVEL]
    validation = calendar_table(date(2024, 3, 15), 7, "validation")
    validation[tb.LEVEL] = 70_000.0  # hors des valeurs de l'entraînement
    result = md.grid_forecast(
        pd.concat([train, validation], ignore_index=True), "lineaire", "rapport"
    )
    assert np.allclose(result.forecast.to_numpy(), 84_000.0)
    assert result.rank is not None and result.columns is not None
    assert result.rank <= result.columns


def test_grid_forecast_refuses_test_rows_and_unknown_cells() -> None:
    table = pd.concat(
        [calendar_table(date(2017, 1, 2), 7), calendar_table(date(2025, 9, 1), 1, "test")],
        ignore_index=True,
    )
    with pytest.raises(ValueError, match="validation"):
        md.grid_forecast(table, "lightgbm", "sans")
    with pytest.raises(ValueError, match="inconnue"):
        md.grid_forecast(table, "lineaire", "logarithme")


def test_lightgbm_with_level_in_the_grid_is_the_same_model_as_validation_forecast() -> None:
    table = pd.concat(
        [calendar_table(date(2017, 1, 2), 30), calendar_table(date(2024, 3, 15), 2, "validation")],
        ignore_index=True,
    )
    grid = md.grid_forecast(table, "lightgbm", "niveau")
    single, rows = md.validation_forecast(table, md.TRAIN_FIRST)
    pd.testing.assert_series_equal(grid.forecast, single)
    assert grid.train_rows == rows
