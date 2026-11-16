from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from pathlib import Path

from day_ahead_load import availability as av

INIT = 1794614400  # 2026-11-14 00:00 UTC
API_META = {
    "last_run_initialisation_time": INIT,
    "last_run_availability_time": INIT + 24055,  # 6,68 h plus tard
    "last_run_modification_time": INIT + 21679,
}
AWS_META = {**API_META, "last_run_availability_time": INIT + 21679}  # 39,6 min plus tôt
NOW = datetime(2026, 11, 14, 10, 0, tzinfo=UTC)
TIMEOUT = TimeoutError("The handshake operation timed out")
API, AWS = av.SOURCES["api"], av.SOURCES["aws"]


class Scripted:
    """Joue, pour chaque adresse, une suite de réponses : un statut ou une exception."""

    def __init__(self, **steps: list[int | Exception]) -> None:
        self.steps = {av.SOURCES[name]: list(seq) for name, seq in steps.items()}
        self.calls: list[str] = []

    def __call__(self, url: str) -> tuple[int, bytes]:
        self.calls.append(url)
        step = self.steps[url].pop(0)
        if isinstance(step, Exception):
            raise step
        meta = API_META if url == API else AWS_META
        return step, json.dumps(meta).encode()


def rows(directory: Path) -> list[dict[str, str]]:
    with (directory / av.CSV_NAME).open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def no_sleep(seconds: float) -> None:
    return None


def test_both_sources_and_their_gap(tmp_path: Path) -> None:
    av.record(tmp_path, Scripted(api=[200], aws=[200]), NOW, no_sleep)
    (row,) = rows(tmp_path)
    assert (row["statut_api"], row["statut_aws"]) == ("ok", "ok")
    assert row["initialisation_api_utc"] == "2026-11-14T00:00:00+00:00"
    assert row["ecart_api_moins_aws_min"] == "39.6"


def test_aws_is_read_even_when_the_api_fails_twice(tmp_path: Path) -> None:
    fetch = Scripted(api=[TIMEOUT, TIMEOUT], aws=[200])
    sleeps: list[float] = []
    av.record(tmp_path, fetch, NOW, sleeps.append)
    (row,) = rows(tmp_path)
    assert (row["statut_api"], row["statut_aws"]) == ("echec", "ok")
    assert row["ecart_api_moins_aws_min"] == ""
    assert "handshake" in row["detail"]
    assert sleeps == [av.RETRY_WAIT_S]
    assert fetch.calls.count(API) == 2


def test_at_most_one_row_per_day(tmp_path: Path) -> None:
    fetch = Scripted(api=[200, 200], aws=[200, 200])
    av.record(tmp_path, fetch, NOW, no_sleep)
    message = av.record(tmp_path, fetch, NOW, no_sleep)
    assert len(fetch.calls) == 2
    assert "aucun appel" in message


def test_server_error_is_retried_once(tmp_path: Path) -> None:
    av.record(tmp_path, Scripted(api=[503, 200], aws=[200]), NOW, no_sleep)
    assert rows(tmp_path)[0]["statut_api"] == "ok"


def test_quota_refusal_on_either_source_stops_for_good(tmp_path: Path) -> None:
    fetch = Scripted(api=[200], aws=[429])
    av.record(tmp_path, fetch, NOW, no_sleep)
    assert (tmp_path / av.STOP_NAME).exists()
    assert not (tmp_path / av.CSV_NAME).exists()
    later = Scripted(api=[200], aws=[200])
    av.record(tmp_path, later, datetime(2026, 11, 15, 10, 0, tzinfo=UTC), no_sleep)
    assert later.calls == []


def test_quota_refusal_is_never_retried(tmp_path: Path) -> None:
    fetch = Scripted(api=[429, 200], aws=[200])
    av.record(tmp_path, fetch, NOW, no_sleep)
    assert fetch.calls == [API]


def test_missing_api_days_are_estimated_from_aws_plus_the_largest_gap() -> None:
    def row(day: str, api: str, aws_avail: str, gap: str) -> dict[str, str]:
        return {
            "date_appel_utc": day,
            "statut_api": api,
            "initialisation_api_utc": f"{day}T00:00:00+00:00" if api == "ok" else "",
            "disponibilite_api_utc": f"{day}T06:40:00+00:00" if api == "ok" else "",
            "statut_aws": "ok",
            "initialisation_aws_utc": f"{day}T00:00:00+00:00",
            "disponibilite_aws_utc": aws_avail,
            "ecart_api_moins_aws_min": gap,
        }

    out = av.api_availability(
        [
            row("2026-11-14", "ok", "2026-11-14T06:00:00+00:00", "40.0"),
            row("2026-11-15", "ok", "2026-11-15T06:10:00+00:00", "30.0"),
            row("2026-11-16", "echec", "2026-11-16T06:05:00+00:00", ""),
        ]
    )
    assert [a.estimated for a in out] == [False, False, True]
    assert out[2].available_utc == datetime(2026, 11, 16, 6, 45, tzinfo=UTC)
