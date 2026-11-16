from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from pathlib import Path

from day_ahead_load import availability as av

META = {
    "last_run_initialisation_time": 1794614400,  # 2026-11-14 00:00 UTC
    "last_run_availability_time": 1794638455,  # 6,68 h plus tard
    "last_run_modification_time": 1794636079,
}
NOW = datetime(2026, 11, 14, 10, 0, tzinfo=UTC)
TIMEOUT = TimeoutError("The handshake operation timed out")


class Scripted:
    """Joue une suite de réponses : un statut HTTP, ou une exception à lever."""

    def __init__(self, *steps: int | Exception) -> None:
        self.steps = list(steps)
        self.calls = 0

    def __call__(self, url: str) -> tuple[int, bytes]:
        self.calls += 1
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step, json.dumps(META).encode()


def rows(directory: Path) -> list[dict[str, str]]:
    with (directory / av.CSV_NAME).open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def no_sleep(seconds: float) -> None:
    return None


def test_one_row_with_the_delay(tmp_path: Path) -> None:
    av.record(tmp_path, Scripted(200), NOW, no_sleep)
    (row,) = rows(tmp_path)
    assert row["statut"] == "ok"
    assert row["initialisation_utc"] == "2026-11-14T00:00:00+00:00"
    assert row["delai_disponibilite_h"] == "6.68"


def test_at_most_one_row_per_day(tmp_path: Path) -> None:
    fetch = Scripted(200, 200)
    av.record(tmp_path, fetch, NOW, no_sleep)
    message = av.record(tmp_path, fetch, NOW, no_sleep)
    assert fetch.calls == 1
    assert "aucun appel" in message


def test_network_timeout_is_retried_once_after_a_pause(tmp_path: Path) -> None:
    fetch = Scripted(TIMEOUT, 200)
    sleeps: list[float] = []
    av.record(tmp_path, fetch, NOW, sleeps.append)
    assert fetch.calls == 2
    assert sleeps == [av.RETRY_WAIT_S]
    assert rows(tmp_path)[0]["statut"] == "ok"


def test_second_failure_writes_a_visible_gap_and_stops(tmp_path: Path) -> None:
    fetch = Scripted(TIMEOUT, 503)
    av.record(tmp_path, fetch, NOW, no_sleep)
    assert fetch.calls == 2
    (row,) = rows(tmp_path)
    assert row["statut"] == "echec"
    assert "503" in row["detail"]
    assert not (tmp_path / av.STOP_NAME).exists()


def test_quota_refusal_is_never_retried_and_stops_every_later_call(tmp_path: Path) -> None:
    fetch = Scripted(429, 200)
    av.record(tmp_path, fetch, NOW, no_sleep)
    assert fetch.calls == 1
    assert (tmp_path / av.STOP_NAME).exists()
    later = Scripted(200)
    av.record(tmp_path, later, datetime(2026, 11, 15, 10, 0, tzinfo=UTC), no_sleep)
    assert later.calls == 0
    assert not (tmp_path / av.CSV_NAME).exists()


def test_quota_refusal_on_the_retry_still_stops(tmp_path: Path) -> None:
    av.record(tmp_path, Scripted(TIMEOUT, 429), NOW, no_sleep)
    assert (tmp_path / av.STOP_NAME).exists()
