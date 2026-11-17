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


def test_cross_validation_trains_only_on_earlier_days_and_is_reproducible() -> None:
    table = tiny_table(date(2018, 12, 1), 62)
    first = md.cross_validate(table, years=[2019])
    assert first == md.cross_validate(table, years=[2019])
    assert first[0].train_rows == 31 * 48
    assert first[0].scored_rows == 31 * 48
