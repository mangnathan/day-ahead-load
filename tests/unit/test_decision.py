from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from day_ahead_load import decision as dec


def prices(start: str, end: str, step: int, long: float, short: float) -> pd.DataFrame:
    index = pd.date_range(start, end, freq=f"{step}min", inclusive="left")
    return pd.DataFrame({"pre_positif": long, "pre_negatif": short, "pas": step}, index=index)


def around_new_year() -> pd.DataFrame:
    """30 min jusqu'au 30/12 23 h 30 UTC, puis le 31/12 UTC publié au quart d'heure avec des
    prix recopiés jusqu'à 23 h UTC (minuit à Paris), puis le vrai règlement au quart d'heure."""
    before = prices("2024-12-30T22:00Z", "2024-12-31T00:00Z", 30, 40.0, 50.0)
    copied = prices("2024-12-31T00:00Z", "2024-12-31T23:00Z", 15, 41.0, 51.0)
    after = prices("2024-12-31T23:00Z", "2025-01-01T00:00Z", 15, 42.0, 52.0)
    after.iloc[1, :2] = [43.0, 53.0]  # prix propres à chaque quart d'heure
    return pd.concat([before, copied, after])


def test_the_31st_of_december_is_not_counted_twice() -> None:
    grid = dec.quarter_prices(around_new_year())
    assert not grid.index.duplicated().any()
    assert len(grid) == len(
        pd.date_range("2024-12-30T22:00Z", "2025-01-01T00:00Z", freq="15min", inclusive="left")
    )


def test_the_31st_of_december_costs_the_same_as_a_half_hour_settlement() -> None:
    grid = dec.quarter_prices(around_new_year())
    # Demi-heure étiquetée 10 h UTC le 31/12 : quarts d'heure de 9 h 45 et de 10 h.
    row = pd.DataFrame(
        {
            "jour": [pd.Timestamp("2024-12-31").date()],
            "consommation": [60_000.0],
            "achat": [59_000.0],
        },
        index=pd.DatetimeIndex([pd.Timestamp("2024-12-31T10:00Z")]),
    )
    q = dec.expand(row, grid, ["consommation", "achat"]).frame
    by_quarter = dec.cost(
        q["consommation"].to_numpy(),
        q["achat"].to_numpy(),
        q["pre_positif"].to_numpy(),
        q["pre_negatif"].to_numpy(),
        61.1,
        0.01,
    ).sum()
    half_hour_energy = 1_000.0 * 0.01 * 0.5  # MWh sur la demi-heure, fournisseur court
    assert by_quarter == pytest.approx(half_hour_energy * (51.0 - 61.1))


def test_different_quarter_prices_before_the_switch_are_refused() -> None:
    bad = around_new_year()
    bad.loc[pd.Timestamp("2024-12-31T10:15Z"), "pre_positif"] = 99.0
    with pytest.raises(ValueError, match="demi-heure"):
        dec.quarter_prices(bad)


def test_a_half_hour_straddles_two_thirty_minute_settlement_periods() -> None:
    grid = dec.quarter_prices(
        pd.concat(
            [
                prices("2024-06-01T09:30Z", "2024-06-01T10:00Z", 30, 10.0, 20.0),
                prices("2024-06-01T10:00Z", "2024-06-01T10:30Z", 30, 30.0, 40.0),
            ]
        )
    )
    row = pd.DataFrame(
        {"jour": [pd.Timestamp("2024-06-01").date()], "consommation": [1.0], "achat": [0.0]},
        index=pd.DatetimeIndex([pd.Timestamp("2024-06-01T10:00Z")]),
    )
    q = dec.expand(row, grid, ["consommation", "achat"]).frame
    assert q["pre_negatif"].tolist() == [20.0, 40.0]  # 9 h 45 puis 10 h


def test_quarters_without_price_are_excluded_and_listed() -> None:
    grid = dec.quarter_prices(prices("2025-03-01T00:00Z", "2025-03-01T00:30Z", 15, 1.0, 2.0))
    rows = pd.DataFrame(
        {
            "jour": [pd.Timestamp("2025-03-01").date()] * 2,
            "consommation": [1.0, 1.0],
            "achat": [0.0, 0.0],
        },
        index=pd.DatetimeIndex(
            [pd.Timestamp("2025-03-01T00:15Z"), pd.Timestamp("2025-03-01T00:45Z")]
        ),
    )
    out = dec.expand(rows, grid, ["consommation", "achat"])
    assert len(out.frame) == 2  # 0 h, 0 h 15 ; 0 h 30 et 0 h 45 sans prix
    assert len(out.excluded) == 2


def test_cost_follows_the_side_of_the_imbalance() -> None:
    long_price, short_price = np.array([40.0, 40.0]), np.array([80.0, 80.0])
    out = dec.cost(
        np.array([100.0, 100.0]), np.array([96.0, 104.0]), long_price, short_price, 60.0, 1.0
    )
    # court de 4 MW pendant 15 min = 1 MWh à (80 − 60) ; long de 1 MWh à (60 − 40)
    assert out.tolist() == pytest.approx([20.0, 20.0])


def test_newsvendor_quantile_and_its_guard() -> None:
    err = np.array([1.0, 1.0, -1.0, -1.0, 0.0])
    long_price = np.array([0.0, 0.0, 50.0, 30.0, 0.0])
    short_price = np.array([70.0, 90.0, 0.0, 0.0, 0.0])
    b = dec.penalties_by_sign(err, long_price, short_price, 60.0)
    assert (b.short, b.long) == pytest.approx((20.0, 20.0))
    assert b.quantile == pytest.approx(0.5)
    assert (b.short_periods, b.long_periods) == (2, 2)
    assert dec.Penalties(-1.0, 5.0, 1, 1).quantile is None
