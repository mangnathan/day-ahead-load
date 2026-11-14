from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np
import pandas as pd
import pytest

from day_ahead_load import weather as w
from day_ahead_load.weather_points import POINTS

PARIS = POINTS[0]


def params(url: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


def test_chunks_cover_the_period_without_gap_or_overlap() -> None:
    parts = w.chunks(date(2024, 1, 1), date(2024, 3, 1))
    assert parts[0][0] == date(2024, 1, 1) and parts[-1][1] == date(2024, 3, 1)
    for (_, end), (start, _) in zip(parts, parts[1:], strict=False):
        assert start == end + timedelta(days=1)
    assert all((end - start).days + 1 <= w.CHUNK_DAYS for start, end in parts)


@pytest.mark.parametrize("source", list(w.SOURCES))
def test_every_call_fixes_the_same_location_and_conventions(source: str) -> None:
    for request in w.requests_for(source, PARIS, 48.0)[:3]:
        p = params(request.url)
        assert (p["latitude"], p["longitude"], p["elevation"]) == ("48.8589", "2.347", "48.0")
        assert p["hourly"].split(",") == list(w.VARIABLES)
        assert p["timezone"] == "GMT"
        assert p["cell_selection"] == "land"
        assert p["models"] == w.SOURCES[source].model


def test_era5_is_requested_explicitly() -> None:
    assert params(w.requests_for("era5", PARIS, 48.0)[0].url)["models"] == "era5"


def test_runs_are_00_utc_of_each_day() -> None:
    runs = w.requests_for("ecmwf_00utc", PARIS, 48.0)
    assert params(runs[0].url)["run"] == "2024-03-14T00:00"
    assert len(runs) == (date(2026, 11, 13) - date(2024, 3, 14)).days + 1


def test_estimate_matches_the_written_figures() -> None:
    assert w.estimate(POINTS) == {"era5": 4644, "ifs_historique": 468, "ecmwf_00utc": 11700}


def budget(tmp_path: Path, cap: int = 3) -> w.Budget:
    return w.Budget(
        tmp_path / "journal.json", tmp_path / "ARRET.json", cap, lambda: date(2026, 1, 1)
    )


def test_daily_cap_blocks_the_next_call(tmp_path: Path) -> None:
    b = budget(tmp_path, cap=2)
    b.record(1.0)
    b.record(1.0)
    with pytest.raises(w.DailyCapReachedError):
        b.check()


class FakeFetch:
    def __init__(self, status: int = 200, cost: str = "1.0") -> None:
        self.status = status
        self.cost = cost
        self.urls: list[str] = []

    def __call__(self, url: str) -> w.Response:
        self.urls.append(url)
        body = {"latitude": 48.75, "longitude": 2.25, "elevation": 48.0}
        return w.Response(self.status, {"X-RateLimit-Cost": self.cost}, json.dumps(body).encode())


def make(tmp_path: Path, fetch: FakeFetch, cap: int = 100) -> tuple[w.Downloader, list[float]]:
    sleeps: list[float] = []
    dl = w.Downloader(tmp_path / "cache", budget(tmp_path, cap), fetch, sleeps.append, lambda: 0.0)
    return dl, sleeps


def test_quota_refusal_stops_for_good(tmp_path: Path) -> None:
    fetch = FakeFetch(status=429)
    dl, _ = make(tmp_path, fetch)
    request = w.requests_for("era5", PARIS, 48.0)[0]
    with pytest.raises(w.QuotaRefusedError):
        dl.get(request)
    assert (tmp_path / "ARRET.json").exists()
    with pytest.raises(w.QuotaRefusedError):
        dl.get(w.requests_for("era5", PARIS, 48.0)[1])
    assert len(fetch.urls) == 1


def test_cache_avoids_a_second_call(tmp_path: Path) -> None:
    fetch = FakeFetch()
    dl, _ = make(tmp_path, fetch)
    request = w.requests_for("era5", PARIS, 48.0)[0]
    dl.get(request)
    dl.get(request)
    assert len(fetch.urls) == 1


def test_calls_are_spaced_and_cost_comes_from_the_header(tmp_path: Path) -> None:
    fetch = FakeFetch(cost="1.5")
    dl, sleeps = make(tmp_path, fetch)
    for request in w.requests_for("era5", PARIS, 48.0)[:3]:
        dl.get(request)
    assert sleeps == [w.MIN_INTERVAL_S, w.MIN_INTERVAL_S]
    assert dl.budget.used_today() == 4.5


def test_land_check_flags_a_cell_outside_french_communes() -> None:
    payload = {"latitude": 43.2, "longitude": 5.3, "elevation": 0.0}
    check = w.land_check(POINTS[-1], "era5", payload, lambda lat, lon: None)
    assert check["centre_sur_commune_francaise"] is False
    assert check["distance_km"] > 0


def test_radiation_convention_is_recognised() -> None:
    minutes = pd.date_range("2024-06-15", "2024-06-22", freq="1min")
    theory = pd.Series(w.top_of_atmosphere(minutes, PARIS.latitude, PARIS.longitude), index=minutes)
    hours = pd.date_range("2024-06-15 01:00", "2024-06-21 23:00", freq="1h")
    previous_hour_mean = theory.rolling(60).mean().reindex(hours)
    scores = w.radiation_convention(previous_hour_mean, PARIS.latitude, PARIS.longitude)
    assert max(scores, key=lambda k: scores[k]) == "moyenne_heure_precedente"
    assert np.isclose(scores["moyenne_heure_precedente"], 1.0)


def test_responses_outside_gmt_are_refused() -> None:
    payload = {"timezone": "Europe/Paris", "utc_offset_seconds": 3600, "hourly": {"time": []}}
    with pytest.raises(ValueError, match="GMT"):
        w.hourly_frame(payload)


def test_only_known_hosts_are_called() -> None:
    with pytest.raises(ValueError, match="refusée"):
        w.checked_url("http://archive-api.open-meteo.com/v1/archive", {})
    with pytest.raises(ValueError, match="refusée"):
        w.checked_url("https://example.org/v1/archive", {})
