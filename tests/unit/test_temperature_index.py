from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from day_ahead_load import temperature_index as ti


def test_normalize_keeps_mainland_regions_only() -> None:
    weights = ti.normalize({"11": 2.0, "94": 5.0, **{r: 1.0 for r in ti.MAINLAND_REGIONS[1:]}})
    assert set(weights) == set(ti.MAINLAND_REGIONS)
    assert weights["11"] == pytest.approx(2 / 13)
    assert sum(weights.values()) == pytest.approx(1.0)


def test_thermosensitive_weights_use_winter_minus_summer() -> None:
    rows = []
    for region in ti.MAINLAND_REGIONS:
        winter = 300.0 if region == "11" else 200.0
        rows += [{"region": region, "date": pd.Timestamp("2020-01-15"), "conso_mw": winter}]
        rows += [{"region": region, "date": pd.Timestamp("2020-07-15"), "conso_mw": 100.0}]
    weights = ti.thermosensitive_weights(pd.DataFrame(rows))
    assert weights["11"] == pytest.approx(200 / (200 + 11 * 100))


def test_national_index_leaves_incomplete_days_missing() -> None:
    rows = [
        {"region": r, "date": pd.Timestamp("2020-01-01"), "tmoy": 10.0} for r in ti.MAINLAND_REGIONS
    ]
    rows += [{"region": "11", "date": pd.Timestamp("2020-01-02"), "tmoy": 5.0}]
    weights = {r: 1 / 12 for r in ti.MAINLAND_REGIONS}
    index = ti.national_index(pd.DataFrame(rows), weights)
    assert index.iloc[0] == pytest.approx(10.0)
    assert np.isnan(index.iloc[1])


def test_cross_validation_recovers_heating_sensitivity() -> None:
    dates = pd.date_range("2016-01-01", "2019-12-31", freq="D")
    rng = np.random.default_rng(1)
    temp = pd.Series(
        12 + 8 * np.sin(2 * np.pi * dates.day_of_year / 365) + rng.normal(0, 2, len(dates)),
        index=dates,
    )
    conso = 50_000 + 2_400 * np.maximum(15 - temp, 0) + rng.normal(0, 300, len(dates))
    result = ti.cross_validate(lambda _: temp, pd.Series(conso, index=dates), 2016, [2018, 2019])
    assert result["par_annee_de_test"]["2019"][
        "sensibilite_chauffage_mw_par_degre"
    ] == pytest.approx(2_400, rel=0.05)
