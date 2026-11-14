from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from day_ahead_load import references as refs

POISON = 1e9
DAY = pd.Timestamp("2025-06-10")


@pytest.fixture(scope="module")
def series() -> tuple[pd.Series, pd.Series]:
    rng = np.random.default_rng(20261114)
    half = pd.date_range("2023-01-01", "2025-12-31 23:30", freq="30min")
    quarter = pd.date_range("2023-01-01", "2025-12-31 23:45", freq="15min")
    conso = pd.Series(50_000 + rng.normal(0, 3_000, len(half)), index=half)
    forecast = pd.Series(50_000 + rng.normal(0, 3_000, len(quarter)), index=quarter)
    return conso, forecast


def targets() -> pd.DatetimeIndex:
    return pd.date_range(DAY, DAY + pd.Timedelta("23:30:00"), freq="30min")


def by_category(category: str) -> list[str]:
    return [r.name for r in refs.REFERENCES if r.category == category]


def test_decision_is_noon_the_day_before() -> None:
    at = refs.decision_time(pd.DatetimeIndex([pd.Timestamp("2025-06-10 18:30")]))
    assert at[0] == pd.Timestamp("2025-06-09 12:00")


def test_consolidated_lag_matches_observed_publication() -> None:
    # Le 14 novembre 2026, le consolidé publié s'arrête fin août.
    end = refs.consolidated_available_until(pd.DatetimeIndex([pd.Timestamp("2026-11-14 12:00")]))
    assert end[0] == pd.Timestamp("2026-09-01")


def test_rte_based_references_are_never_realistic() -> None:
    # La prévision J-1 de RTE est publiée après midi la veille : corrigée ou non, une
    # référence qui la lit ne peut pas être disponible à l'heure de la décision.
    for r in refs.REFERENCES:
        if r.name.startswith("rte_"):
            assert r.category in {"avantagée", "borne"}


def test_every_reference_is_computed(series: tuple[pd.Series, pd.Series]) -> None:
    conso, forecast = series
    out = refs.compute(conso, forecast, targets())
    assert list(out.columns) == [r.name for r in refs.REFERENCES]
    assert out.notna().all().all()


def test_no_value_after_noon_the_day_before(series: tuple[pd.Series, pd.Series]) -> None:
    conso, forecast = series
    decision = pd.Timestamp("2025-06-09 12:00")
    before = refs.compute(conso, forecast, targets())
    # Toute demi-heure qui se termine après midi la veille est remplacée par une valeur absurde.
    poisoned = conso.where(conso.index + refs.HALF_HOUR <= decision, POISON)
    after = refs.compute(poisoned, forecast, targets())
    for name in by_category("optimiste") + by_category("réaliste") + by_category("avantagée"):
        pd.testing.assert_series_equal(before[name], after[name], check_names=False)


def test_realistic_references_read_only_published_consolidated(
    series: tuple[pd.Series, pd.Series],
) -> None:
    conso, forecast = series
    available = pd.Timestamp("2025-04-01")  # décision le 9 juin : consolidé publié jusqu'à mars
    before = refs.compute(conso, forecast, targets())
    poisoned = conso.where(conso.index + refs.HALF_HOUR <= available, POISON)
    after = refs.compute(poisoned, forecast, targets())
    published_only = [r.name for r in refs.REFERENCES if r.published_consolidated_only]
    assert "rte_corrige_meme_mois_an_dernier" in published_only
    for name in published_only:
        pd.testing.assert_series_equal(before[name], after[name], check_names=False)
    # Contrôle du test lui-même : une référence optimiste, elle, est touchée.
    assert (after["naif_j7"] == POISON).all()


def test_morning_uses_yesterday_afternoon_uses_two_days_before(
    series: tuple[pd.Series, pd.Series],
) -> None:
    conso, forecast = series
    at = pd.DatetimeIndex([pd.Timestamp("2025-06-10 11:30"), pd.Timestamp("2025-06-10 12:00")])
    out = refs.compute(conso, forecast, at)["naif_j1_matin_j2_apres_midi"]
    assert out.iloc[0] == conso[pd.Timestamp("2025-06-09 11:30")]
    assert out.iloc[1] == conso[pd.Timestamp("2025-06-08 12:00")]


def test_errors_on_common_sample() -> None:
    index = pd.date_range("2025-01-01", periods=2, freq="30min")
    conso = pd.Series([100.0, 200.0], index=index)
    frame = pd.DataFrame({"a": [110.0, 180.0], "b": [np.nan, 200.0]}, index=index)
    out = refs.errors(conso, frame)
    assert out["a"] == {"demi_heures": 1, "mape_pct": 10.0, "mae_mw": 20.0}
    assert out["b"]["mape_pct"] == 0.0
