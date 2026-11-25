from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from day_ahead_load import assessment as ass
from day_ahead_load import guard
from day_ahead_load import modelling as md
from day_ahead_load import table as tb
from day_ahead_load import uncertainty as unc

TEST_DAY = date(2025, 10, 1)


def test_the_guard_uses_the_split_of_adr_0001() -> None:
    assert (guard.TEST_FIRST, guard.TEST_LAST) == tb.TEST
    assert guard.TEST_OPEN is False


def test_the_guard_refuses_any_test_day_and_accepts_the_others() -> None:
    guard.refuse_test_days([date(2025, 8, 31), date(2026, 9, 1)])
    with pytest.raises(guard.TestPeriodClosedError, match="2025-10-01"):
        guard.refuse_test_days([date(2025, 8, 31), TEST_DAY])


def test_paired_comparisons_refuse_test_days() -> None:
    days = pd.Series([TEST_DAY + timedelta(days=k // 48) for k in range(7 * 48)])
    truth = pd.Series(np.full(len(days), 100.0))
    with pytest.raises(guard.TestPeriodClosedError):
        md.paired_gap(truth, np.full(len(days), 101.0), np.full(len(days), 102.0), days, TEST_DAY)


def test_the_ratio_to_the_naive_forecast_refuses_test_days() -> None:
    days = [TEST_DAY] * 48
    truth = np.full(48, 100.0)
    with pytest.raises(guard.TestPeriodClosedError):
        ass.ratio_interval(truth, truth + 1, truth + 2, days, TEST_DAY)


def test_calibration_refuses_residuals_of_test_days() -> None:
    rows = pd.DataFrame(
        {
            "jour": [TEST_DAY] * 48,
            "demi_heure": range(48),
            "jour_semaine": 2,
            "ferie": False,
            "pont": False,
            "noel": False,
            "temperature_2m": 15.0,
        }
    )
    residuals = pd.Series(np.zeros(48), index=rows.index)
    with pytest.raises(guard.TestPeriodClosedError):
        unc.calibrate(pd.Series(np.zeros(48)), rows, residuals, rows, unc.group_q1)
