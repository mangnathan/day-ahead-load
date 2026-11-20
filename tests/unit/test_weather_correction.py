from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from day_ahead_load import weather_correction as wcor
from day_ahead_load import weather_features as wf

HUMIDITY = "relative_humidity_2m"


def frame(start: str, end: str, value: float = 0.0) -> pd.DataFrame:
    index = pd.date_range(start, end, freq="h", tz="UTC")
    return pd.DataFrame({name: value for name in (*wf.VARIABLES, HUMIDITY)}, index=index)


def test_mean_gap_is_computed_by_month_and_utc_hour_on_2017_to_training_end_only() -> None:
    era5 = frame("2016-06-01", "2024-06-30 23:00")
    index = pd.DatetimeIndex(era5.index)
    ifs = era5.copy()
    for name in wcor.BOUNDS:
        ifs[name] = index.hour + 0.01 * index.month
    outside = (index < pd.Timestamp("2017-01-01", tz="UTC")) | (
        index >= pd.Timestamp("2024-03-15", tz="UTC")
    )
    ifs.loc[outside, list(wcor.BOUNDS)] = 1e6  # hors de la période : ne doit pas compter
    gap = wcor.mean_gap(era5, ifs)
    assert gap.at[(7, 13), wf.TEMPERATURE] == pytest.approx(13.07)
    assert gap.at[(3, 0), "cloud_cover"] == pytest.approx(0.03)
    assert HUMIDITY not in gap.columns


def test_mean_gap_refuses_missing_month_hour_pairs() -> None:
    era5 = frame("2017-01-01", "2017-06-30 23:00")
    with pytest.raises(ValueError, match="incomplet"):
        wcor.mean_gap(era5, era5)


def test_corrected_values_stay_within_physical_bounds_and_humidity_is_untouched() -> None:
    keys = pd.MultiIndex.from_product([range(1, 13), range(24)], names=wcor.KEYS)
    gap = pd.DataFrame(
        {
            wf.TEMPERATURE: -5.0,
            wf.RADIATION: -5.0,
            "cloud_cover": 5.0,
            "wind_speed_10m": -3.0,
        },
        index=keys,
    )
    era5 = frame("2015-01-01", "2015-01-01 02:00")
    era5[wf.TEMPERATURE] = -10.0
    era5["cloud_cover"] = 98.0
    era5["wind_speed_10m"] = 1.0
    era5[HUMIDITY] = 99.0
    out = wcor.corrected(era5, gap)
    assert (out[wf.TEMPERATURE] == -15.0).all()  # pas de borne
    assert (out[wf.RADIATION] == 0.0).all()
    assert (out["cloud_cover"] == 100.0).all()
    assert (out["wind_speed_10m"] == 0.0).all()
    assert (out[HUMIDITY] == 99.0).all()
    assert np.array_equal(out.index, era5.index)
