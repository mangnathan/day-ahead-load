from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from day_ahead_load import weather_features as wf

UTC = "UTC"


def hourly(start: str, hours: int) -> pd.DataFrame:
    """Série horaire dont chaque variable vaut l'heure UTC (0 à 23) : facile à relire."""
    index = pd.date_range(start, periods=hours, freq="h", tz=UTC)
    values = index.hour.to_numpy(dtype=float)
    return pd.DataFrame({name: values for name in wf.VARIABLES}, index=index)


def test_radiation_labelled_13h_applies_to_half_hours_12h30_and_13h00() -> None:
    ends = pd.DatetimeIndex(["2025-06-01 12:30", "2025-06-01 13:00", "2025-06-01 13:30"], tz=UTC)
    out = wf.half_hour_features(ends, hourly("2025-06-01 00:00", 24))
    assert out[wf.RADIATION].tolist() == [13.0, 13.0, 14.0]


def test_instant_variables_are_read_at_the_middle_of_the_half_hour() -> None:
    ends = pd.DatetimeIndex(["2025-06-01 12:30", "2025-06-01 13:00"], tz=UTC)
    out = wf.half_hour_features(ends, hourly("2025-06-01 00:00", 24))
    assert out[wf.TEMPERATURE].tolist() == [12.25, 12.75]


def test_smoothing_uses_the_hours_of_the_trailing_window_only() -> None:
    frame = hourly("2025-06-01 00:00", 48)
    frame[wf.TEMPERATURE] = np.arange(48, dtype=float)
    ends = pd.DatetimeIndex(["2025-06-02 12:00", "2025-06-02 12:30", "2025-06-01 22:00"], tz=UTC)
    out = wf.half_hour_features(ends, frame)
    # (t − 24 h, t] pour t = 02/06 12 h : heures 13 à 36 de la série.
    assert out["temperature_lissee_24h"].tolist()[:2] == [24.5, 24.5]
    assert np.isnan(out["temperature_lissee_24h"].iloc[2])  # moins de 24 heures connues
    assert out["temperature_lissee_72h"].isna().all()


def synthetic_runs(first: date, last: date) -> pd.DataFrame:
    """Chaque calcul vaut son propre numéro de jour sur ses 72 heures."""
    frames = {}
    for k in range((last - first).days + 1):
        run = first + timedelta(days=k)
        index = pd.date_range(pd.Timestamp(run, tz=UTC), periods=72, freq="h")
        frames[run] = pd.DataFrame({name: float(k) for name in wf.VARIABLES}, index=index)
    return pd.concat(frames, names=["calcul", "heure"])


def rows_of(day: date) -> pd.DataFrame:
    local = pd.date_range(pd.Timestamp(day).tz_localize("Europe/Paris"), periods=48, freq="30min")
    return pd.DataFrame({"jour": day}, index=local.tz_convert(UTC))


def test_hours_of_the_delivered_day_come_from_the_previous_day_run() -> None:
    runs = synthetic_runs(date(2025, 1, 1), date(2025, 1, 10))
    out = wf.forecast_features(rows_of(date(2025, 1, 8)), runs)
    assert (out[wf.TEMPERATURE] == 6.0).all()  # calcul du 07/01, numéro 6


def test_past_hours_come_from_the_runs_of_their_own_day() -> None:
    runs = synthetic_runs(date(2025, 1, 1), date(2025, 1, 10))
    out = wf.forecast_features(rows_of(date(2025, 1, 8)), runs)
    # Dernière demi-heure du 08/01 : étiquetée 23 h 30 à Paris, elle finit à 22 h 30 UTC. Les
    # 72 heures vont de 23 h UTC le 05/01 à 22 h UTC le 08/01 : une heure du 05/01 (calcul
    # numéro 4), 24 heures du 06/01 (numéro 5), puis 47 heures du calcul du 07/01 (numéro 6).
    last = out["temperature_lissee_72h"].iloc[-1]
    assert last == (1 * 4 + 24 * 5 + 47 * 6) / 72


def test_nothing_published_after_noon_the_day_before_enters_the_features() -> None:
    runs = synthetic_runs(date(2025, 1, 1), date(2025, 1, 10))
    delivered = date(2025, 1, 8)
    clean = wf.forecast_features(rows_of(delivered), runs)
    poisoned = runs.copy()
    later = np.asarray(
        pd.Index(poisoned.index.get_level_values("calcul")) > delivered - timedelta(days=1)
    )
    poisoned.loc[later, :] = 1e9
    pd.testing.assert_frame_equal(wf.forecast_features(rows_of(delivered), poisoned), clean)


def test_missing_previous_day_run_falls_back_on_the_run_before() -> None:
    runs = synthetic_runs(date(2025, 1, 1), date(2025, 1, 10))
    runs = runs.drop(date(2025, 1, 7), level="calcul")
    out = wf.forecast_features(rows_of(date(2025, 1, 8)), runs)
    assert (out[wf.TEMPERATURE] == 5.0).all()  # calcul du 06/01, numéro 5


def test_missing_values_inside_a_run_fall_back_on_the_run_before() -> None:
    runs = synthetic_runs(date(2025, 1, 1), date(2025, 1, 10))
    runs.loc[date(2025, 1, 7), wf.TEMPERATURE] = np.nan
    out = wf.forecast_features(rows_of(date(2025, 1, 8)), runs)
    assert (out[wf.TEMPERATURE] == 5.0).all()
    assert (out["cloud_cover"] == 6.0).all()  # les autres variables gardent leur calcul
