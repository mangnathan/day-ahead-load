from __future__ import annotations

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


class FakeFetch:
    def __init__(self, status: int = 200) -> None:
        self.status = status
        self.calls = 0

    def __call__(self, url: str) -> tuple[int, bytes]:
        self.calls += 1
        return self.status, json.dumps(META).encode()


def test_one_row_with_the_delay(tmp_path: Path) -> None:
    av.record(tmp_path, FakeFetch(), NOW)
    lines = (tmp_path / av.CSV_NAME).read_text(encoding="utf-8").splitlines()
    assert lines[0].split(",") == list(av.COLUMNS)
    assert "2026-11-14T00:00:00+00:00" in lines[1]
    assert lines[1].endswith(",6.68")


def test_at_most_one_call_per_day(tmp_path: Path) -> None:
    fetch = FakeFetch()
    av.record(tmp_path, fetch, NOW)
    message = av.record(tmp_path, fetch, NOW)
    assert fetch.calls == 1
    assert "aucun appel" in message


def test_quota_refusal_stops_every_later_call(tmp_path: Path) -> None:
    av.record(tmp_path, FakeFetch(status=429), NOW)
    assert (tmp_path / av.STOP_NAME).exists()
    later = FakeFetch()
    av.record(tmp_path, later, datetime(2026, 11, 15, 10, 0, tzinfo=UTC))
    assert later.calls == 0
    assert not (tmp_path / av.CSV_NAME).exists()
