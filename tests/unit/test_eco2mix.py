from __future__ import annotations

import pandas as pd
import pytest

from day_ahead_load import eco2mix


def frame(
    start: str, periods: int, nature: str = "Données définitives", **values: float
) -> pd.DataFrame:
    stamps = pd.date_range(start, periods=periods, freq="15min", tz="UTC")
    return pd.DataFrame(
        {
            "nature": nature,
            "date_heure": stamps,
            "consommation": pd.array([values.get("conso", 50_000.0)] * periods, dtype="Float64"),
            "prevision_j1": pd.array([values.get("j1", 51_000.0)] * periods, dtype="Float64"),
            "prevision_j": pd.array([values.get("j", 50_500.0)] * periods, dtype="Float64"),
        }
    )


def test_export_url_refuses_unknown_dataset() -> None:
    with pytest.raises(ValueError):
        eco2mix.export_url("autre-jeu")


def test_export_url_is_https_odre() -> None:
    assert eco2mix.export_url("eco2mix-national-tr").startswith("https://odre.opendatasoft.com/")


def test_missing_timestamps_finds_one_run() -> None:
    df = frame("2024-01-01T00:00Z", 10)
    df = df.drop(index=[3, 4]).reset_index(drop=True)
    result = eco2mix.missing_timestamps(df)
    assert result["attendus"] == 10
    assert result["absents"] == 2
    assert result["plages"] == [
        {"debut_utc": "2024-01-01T00:45:00+00:00", "fin_utc": "2024-01-01T01:00:00+00:00", "pas": 2}
    ]


def test_duplicates_counts_repeated_stamps() -> None:
    df = frame("2024-01-01T00:00Z", 4)
    df = pd.concat([df, df.iloc[[1]]], ignore_index=True)
    assert eco2mix.duplicates(df) == 1


def test_seams_exact_join_is_one_step() -> None:
    a = frame("2024-01-01T00:00Z", 4, nature="Données définitives")
    b = frame("2024-01-01T01:00Z", 4, nature="Données consolidées")
    assert eco2mix.seams(pd.concat([a, b]))[0]["ecart_en_pas"] == 1.0


def test_local_days_follow_daylight_saving() -> None:
    # Le 31 mars 2024 (passage à l'heure d'été) dure 23 h à Paris : 92 quarts d'heure. La
    # série démarre le 30 mars à minuit à Paris ; les 4 derniers pas tombent le 2 avril.
    df = frame("2024-03-29T23:00Z", 96 * 3)
    assert eco2mix.local_day_sizes(df) == {"4": 1, "92": 1, "96": 2}
    assert eco2mix.irregular_days(df) == [{"jour": "2024-04-02", "lignes": 4, "attendues": 96}]


def test_irregular_days_flags_a_short_normal_day() -> None:
    df = frame("2024-01-09T23:00Z", 96).drop(index=[10]).reset_index(drop=True)
    assert eco2mix.irregular_days(df) == [{"jour": "2024-01-10", "lignes": 95, "attendues": 96}]


def test_fill_by_minute_detects_half_hour_step() -> None:
    df = frame("2024-01-01T00:00Z", 8)
    df.loc[df["date_heure"].dt.minute.isin([15, 45]), "consommation"] = pd.NA
    fill = eco2mix.fill_by_minute(df, "consommation")["2024"]
    assert fill == {"00": 1.0, "15": 0.0, "30": 1.0, "45": 0.0}


def test_j1_error_by_year() -> None:
    df = frame("2024-06-01T00:00Z", 4, conso=50_000.0, j1=51_000.0)
    result = eco2mix.j1_error_by_year(df)["2024"]
    assert result == {"points": 4, "mae_mw": 1000.0, "mape_pct": 2.0, "biais_mw": 1000.0}
