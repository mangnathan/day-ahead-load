from __future__ import annotations

import pandas as pd

from day_ahead_load import diagnostics


def raw_day(day: str, hours: list[str], conso: float = 50_000.0) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "nature": "Données définitives",
            "date": day,
            "heure": hours,
            "consommation": conso,
            "prevision_j1": conso,
        }
    )


def quarter_hours() -> list[str]:
    return [f"{h:02d}:{m:02d}" for h in range(24) for m in (0, 15, 30, 45)]


def test_local_instants_drop_nonexistent_spring_hour() -> None:
    df, counts = diagnostics.with_local_instants(raw_day("2024-03-31", quarter_hours()))
    assert counts == {"lignes_heure_inexistante_mars": 4, "lignes_heure_ambigue_octobre": 0}
    assert len(df) == 92


def test_local_instants_drop_both_ambiguous_october_hours() -> None:
    df, counts = diagnostics.with_local_instants(raw_day("2024-10-27", quarter_hours()))
    assert counts == {"lignes_heure_inexistante_mars": 0, "lignes_heure_ambigue_octobre": 4}
    assert len(df) == 92


def test_aligned_forecast_averages_shifted_values() -> None:
    raw = raw_day("2024-01-10", ["10:00", "10:15", "10:30"])
    raw["prevision_j1"] = [100.0, 200.0, 300.0]
    df, _ = diagnostics.with_local_instants(raw)
    series = diagnostics.aligned_forecast(df, (0, 1))
    assert list(series.iloc[:2]) == [150.0, 250.0]
    assert pd.isna(series.iloc[2])


def test_monthly_bias_by_band() -> None:
    raw = raw_day("2024-01-10", ["00:00", "13:00", "13:15"])
    raw["prevision_j1"] = [49_000.0, 52_000.0, 0.0]
    df, _ = diagnostics.with_local_instants(raw)
    month = diagnostics.monthly_bias(df, "2024-01-01")["2024-01"]
    # 13 h 15 n'est pas une demi-heure pleine : écartée.
    assert month["00-06"] == -1000.0
    assert month["13-17"] == 2000.0
    assert month["tout"] == 500.0
    assert month["nature"] == ["Données définitives"]
