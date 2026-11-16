from __future__ import annotations

import csv
import json
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path

from day_ahead_load import availability as av

DAY = date(2026, 11, 16)
INIT_00 = 1794787200  # 2026-11-16 00:00 UTC
INIT_06 = INIT_00 + 6 * 3600
NOW = datetime(2026, 11, 16, 9, 0, tzinfo=UTC)
AWS_URL = av.AWS_RUN_URL.format(day=DAY)
TIMEOUT = TimeoutError("The handshake operation timed out")
AWS_META = {"created_at": "2026-11-16T06:23:03Z", "reference_time": "2026-11-16T00:00:00Z"}


def api_meta(init: int, delay_s: int) -> dict[str, int]:
    return {
        "last_run_initialisation_time": init,
        "last_run_availability_time": init + delay_s,
        "last_run_modification_time": init + delay_s,
    }


class Scripted:
    """Joue, pour l'API et pour AWS, une suite de réponses : un statut ou une exception."""

    def __init__(
        self,
        api: list[int | Exception],
        aws: list[int | Exception],
        meta: dict[str, int] | None = None,
    ) -> None:
        self.steps = {av.API_URL: list(api), AWS_URL: list(aws)}
        self.meta = meta or api_meta(INIT_00, 6 * 3600 + 23 * 60 + 3 + 54 * 60)
        self.calls: list[str] = []

    def __call__(self, url: str) -> tuple[int, bytes]:
        self.calls.append(url)
        step = self.steps[url].pop(0)
        if isinstance(step, Exception):
            raise step
        body = self.meta if url == av.API_URL else AWS_META
        return step, json.dumps(body).encode()


def rows(directory: Path) -> list[dict[str, str]]:
    with (directory / av.CSV_NAME).open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def no_sleep(seconds: float) -> None:
    return None


def server(host: str) -> str:
    return "157.90.83.168"


def run(tmp_path: Path, fetch: Scripted, sleep: Callable[[float], None] = no_sleep) -> str:
    return av.record(tmp_path, fetch, NOW, sleep, server)


def test_00utc_run_server_and_gap(tmp_path: Path) -> None:
    run(tmp_path, Scripted(api=[200], aws=[200]))
    (row,) = rows(tmp_path)
    assert row["calcul_api"] == "00"
    assert row["serveur_api"] == "157.90.83.168"
    assert row["depot_aws_00utc"] == "2026-11-16T06:23:03+00:00"
    assert row["ecart_api_moins_aws_min"] == "54.0"


def test_reading_that_falls_on_the_06utc_run_is_labelled_and_not_compared(tmp_path: Path) -> None:
    fetch = Scripted(api=[200], aws=[200], meta=api_meta(INIT_06, 6 * 3600))
    run(tmp_path, fetch)
    (row,) = rows(tmp_path)
    assert row["calcul_api"] == "06"
    assert row["ecart_api_moins_aws_min"] == ""


def test_aws_is_read_even_when_the_api_fails_twice(tmp_path: Path) -> None:
    fetch = Scripted(api=[TIMEOUT, TIMEOUT], aws=[200])
    sleeps: list[float] = []
    run(tmp_path, fetch, sleeps.append)
    (row,) = rows(tmp_path)
    assert (row["statut_api"], row["statut_aws"]) == ("echec", "ok")
    assert "handshake" in row["detail"]
    assert sleeps == [av.RETRY_WAIT_S]


def test_run_not_yet_deposited_on_aws(tmp_path: Path) -> None:
    run(tmp_path, Scripted(api=[200], aws=[404]))
    assert rows(tmp_path)[0]["statut_aws"] == "absent"


def test_at_most_one_row_per_day(tmp_path: Path) -> None:
    fetch = Scripted(api=[200, 200], aws=[200, 200])
    run(tmp_path, fetch)
    message = run(tmp_path, fetch)
    assert len(fetch.calls) == 2
    assert "aucun appel" in message


def test_quota_refusal_on_either_source_stops_for_good(tmp_path: Path) -> None:
    run(tmp_path, Scripted(api=[200], aws=[429]))
    assert (tmp_path / av.STOP_NAME).exists()
    assert not (tmp_path / av.CSV_NAME).exists()
    later = Scripted(api=[200], aws=[200])
    run(tmp_path, later)
    assert later.calls == []


def test_quota_refusal_is_never_retried(tmp_path: Path) -> None:
    fetch = Scripted(api=[429, 200], aws=[200])
    run(tmp_path, fetch)
    assert fetch.calls == [av.API_URL]


def test_missing_api_days_use_aws_deposit_plus_two_hours() -> None:
    base = dict.fromkeys(av.COLUMNS, "")
    measured = {
        **base,
        "date_appel_utc": "2026-11-16",
        "statut_api": "ok",
        "calcul_api": "00",
        "disponibilite_api_utc": "2026-11-16T07:17:00+00:00",
        "statut_aws": "ok",
        "depot_aws_00utc": "2026-11-16T06:23:00+00:00",
    }
    estimated = {**measured, "date_appel_utc": "2026-11-17", "statut_api": "echec"}
    other_run = {**measured, "date_appel_utc": "2026-11-18", "calcul_api": "06"}
    out = av.api_availability([measured, estimated, other_run])
    assert [a.estimated for a in out] == [False, True, True]
    assert out[1].available_utc == datetime(2026, 11, 16, 8, 23, tzinfo=UTC)
