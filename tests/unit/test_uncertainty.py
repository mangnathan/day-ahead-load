from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from day_ahead_load import uncertainty as unc


def rows(first: date, days: int, **columns: object) -> pd.DataFrame:
    out = []
    for k in range(days):
        day = first + timedelta(days=k)
        for slot in range(48):
            out.append(
                {
                    "jour": day,
                    "demi_heure": slot,
                    "jour_semaine": day.weekday(),
                    "ferie": False,
                    "pont": False,
                    "noel": False,
                    "temperature_2m": 15.0,
                    **columns,
                }
            )
    return pd.DataFrame(out)


def test_day_kind_puts_bridges_and_christmas_with_sundays_and_keeps_pentecost_working() -> None:
    table = pd.DataFrame(
        {
            "jour_semaine": [0, 5, 6, 2, 4, 1, 5],
            "ferie": [False, False, False, True, False, False, True],
            "pont": [False, False, False, False, True, False, False],
            "noel": [False, False, False, False, False, True, False],
        }
    )
    assert unc.day_kind(table).tolist() == [0, 1, 2, 2, 2, 2, 2]


def test_window_stops_at_the_end_of_month_minus_three_and_spans_twelve_months() -> None:
    assert unc.window(pd.Period("2024-09", "M")) == (date(2023, 7, 1), date(2024, 6, 30))
    assert unc.window(pd.Period("2025-06", "M")) == (date(2024, 4, 1), date(2025, 3, 31))


def test_decision_month_is_the_month_of_the_day_before() -> None:
    months = unc.decision_month([date(2024, 9, 1), date(2024, 9, 2)])
    assert [str(m) for m in months] == ["2024-08", "2024-09"]


def test_days_with_fewer_than_90_days_of_residuals_are_not_judged() -> None:
    residual_rows = rows(date(2024, 3, 15), 108)  # du 15/03 au 30/06/2024
    residuals = pd.Series(np.zeros(len(residual_rows)), index=residual_rows.index)
    target = rows(date(2024, 9, 1), 2)
    point = pd.Series(np.full(len(target), 50_000.0), index=target.index)
    out = unc.calibrate(point, target, residuals, residual_rows, unc.group_q1)
    first_day = np.asarray(target["jour"] == date(2024, 9, 1))
    assert not out.judged[first_day].any()  # décidé en août : résidus jusqu'au 31/05, 78 jours
    assert out.judged[~first_day].all()  # décidé en septembre : 108 jours
    assert set(out.residual_days[first_day]) == {78}


def test_quantiles_add_the_residual_quantiles_of_the_group_to_the_point_forecast() -> None:
    residual_rows = rows(date(2024, 3, 15), 108)
    residuals = pd.Series(
        np.where(residual_rows["demi_heure"] == 0, 1_000.0, -500.0), index=residual_rows.index
    )
    target = rows(date(2024, 9, 2), 1)
    point = pd.Series(np.full(len(target), 50_000.0), index=target.index)
    out = unc.calibrate(point, target, residuals, residual_rows, unc.group_q1)
    assert (out.quantiles.iloc[0] == 51_000.0).all()
    assert (out.quantiles.iloc[1] == 49_500.0).all()


def test_residuals_published_after_the_decision_are_never_used() -> None:
    residual_rows = rows(date(2024, 3, 15), 200)
    clean = pd.Series(np.zeros(len(residual_rows)), index=residual_rows.index)
    poisoned = clean.copy()
    late = np.asarray(pd.to_datetime(residual_rows["jour"]) > pd.Timestamp(date(2024, 6, 30)))
    poisoned[late] = 1e9
    target = rows(date(2024, 9, 2), 3)
    point = pd.Series(np.full(len(target), 50_000.0), index=target.index)
    a = unc.calibrate(point, target, clean, residual_rows, unc.group_q2)
    b = unc.calibrate(point, target, poisoned, residual_rows, unc.group_q2)
    pd.testing.assert_frame_equal(a.quantiles, b.quantiles)


def test_small_q3_groups_fall_back_on_their_q2_group_and_are_counted() -> None:
    residual_rows = rows(date(2024, 3, 15), 108)
    cold = np.asarray(residual_rows["jour"] == date(2024, 3, 15))  # un seul jour froid
    residual_rows.loc[cold, "temperature_2m"] = 2.0
    residuals = pd.Series(np.where(cold, 9_000.0, 0.0), index=residual_rows.index)
    target = rows(date(2024, 9, 2), 1, temperature_2m=2.0)
    point = pd.Series(np.zeros(len(target)), index=target.index)
    out = unc.calibrate(point, target, residuals, residual_rows, unc.group_q3, unc.group_q2)
    q2 = unc.calibrate(point, target, residuals, residual_rows, unc.group_q2)
    pd.testing.assert_frame_equal(out.quantiles, q2.quantiles)
    assert len(out.fallbacks) == len(target)


def test_pinball_coverage_and_width() -> None:
    truth = np.array([100.0, 100.0])
    assert unc.pinball(truth, np.array([90.0, 110.0]), 0.9).tolist() == pytest.approx([9.0, 1.0])
    quantiles = pd.DataFrame(
        {
            "0.025": [80.0, 101.0],
            "0.1": [90.0, 102.0],
            "0.5": [100.0, 103.0],
            "0.9": [110.0, 104.0],
            "0.975": [120.0, 105.0],
        }
    )
    assert unc.covered(truth, quantiles, "80").tolist() == [True, False]
    assert unc.width(quantiles, "95").tolist() == [40.0, 4.0]
    assert unc.admissible(80.0, 95.0)
    assert not unc.admissible(74.9, 95.0)
    assert not unc.admissible(80.0, 98.1)


def test_j7_point_reads_the_same_wall_clock_time_a_week_before() -> None:
    wall = pd.date_range("2024-09-01", periods=10 * 48, freq="30min")
    target = pd.Series(np.arange(len(wall), dtype=float), index=wall)
    out = unc.j7_point(target, pd.DatetimeIndex([pd.Timestamp("2024-09-08 13:30")]))
    assert out.tolist() == [target[pd.Timestamp("2024-09-01 13:30")]]
