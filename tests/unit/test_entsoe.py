from __future__ import annotations

import io
import zipfile
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pandas as pd
import pytest

from day_ahead_load import entsoe
from day_ahead_load import weather as w

TOKEN = "jeton-secret-0123456789abcdef"  # noqa: S105 (faux jeton de test)
BODY = b"<Publication_MarketDocument>prix</Publication_MarketDocument>"


class FakeServer:
    """Faux serveur : répond selon une liste de statuts, et garde les adresses reçues."""

    def __init__(self, statuses: list[int | Exception]) -> None:
        self.statuses = list(statuses)
        self.urls: list[str] = []

    def __call__(self, url: str) -> w.Response:
        self.urls.append(url)
        status = self.statuses.pop(0)
        if isinstance(status, Exception):
            raise status
        body = BODY if status == 200 else f"erreur pour {url}".encode()
        return w.Response(status, {"Content-Type": "text/xml"}, body)


def client(tmp_path: Path, server: Callable[[str], w.Response]) -> entsoe.Client:
    budget = w.Budget(tmp_path / "journal.json", tmp_path / "ARRET.json", cap=entsoe.DAILY_CAP)
    return entsoe.Client(
        TOKEN, tmp_path / "cache", budget, fetch=server, sleep=lambda s: None, clock=lambda: 0.0
    )


def every_file_text(root: Path) -> str:
    return "".join(p.read_bytes().decode("latin-1") for p in root.rglob("*") if p.is_file())


def test_estimate_is_one_control_call_and_one_call_per_month() -> None:
    assert entsoe.estimate() == {"controle": 1, "prix_des_ecarts_mensuels": 30}
    requests = entsoe.monthly_requests()
    assert requests[0].start == datetime(2024, 3, 1, tzinfo=UTC)
    assert requests[-1].end == datetime(2026, 9, 1, tzinfo=UTC)


def test_request_parameters_follow_the_documentation_and_never_carry_the_token() -> None:
    request = entsoe.control_request(date(2025, 1, 15))
    assert request.params() == {
        "documentType": "A85",
        entsoe.DOMAIN_PARAMETER: "10YFR-RTE------C",
        "periodStart": "202501150000",
        "periodEnd": "202501160000",
    }


def test_the_token_never_appears_in_files_outputs_or_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    server = FakeServer([200, 400, OSError(f"échec vers {TOKEN}"), OSError("encore"), 429])
    c = client(tmp_path, server)
    c.get(entsoe.control_request())
    with pytest.raises(RuntimeError) as bad:
        c.get(entsoe.monthly_requests()[0])
    with pytest.raises(w.NetworkInterruptedError) as cut:
        c.get(entsoe.monthly_requests()[1])
    with pytest.raises(w.QuotaRefusedError) as quota:
        c.get(entsoe.monthly_requests()[2])
    print(repr(c))
    out = capsys.readouterr()
    assert TOKEN not in every_file_text(tmp_path)
    assert TOKEN not in out.out + out.err
    for error in (bad.value, cut.value, quota.value):
        assert TOKEN not in str(error)
    # Le jeton part bien dans la requête, et seulement là.
    assert parse_qs(urlparse(server.urls[0]).query)["securityToken"] == [TOKEN]


def test_responses_are_cached_with_their_parameters_and_counted(tmp_path: Path) -> None:
    server = FakeServer([200])
    c = client(tmp_path, server)
    path, meta = c.get(entsoe.control_request())
    again, _ = c.get(entsoe.control_request())
    assert path == again and path.read_bytes() == BODY
    assert len(server.urls) == 1  # le second appel est lu dans le cache
    assert meta["requete"] == entsoe.control_request().params()
    assert meta["source"] == "ENTSO-E Transparency Platform"
    assert c.budget.used_today() == 1.0


def test_a_quota_refusal_stops_everything_for_good(tmp_path: Path) -> None:
    server = FakeServer([429])
    c = client(tmp_path, server)
    with pytest.raises(w.QuotaRefusedError):
        c.get(entsoe.control_request())
    assert (tmp_path / "ARRET.json").exists()
    with pytest.raises(w.QuotaRefusedError):
        c.get(entsoe.monthly_requests()[0])
    assert len(server.urls) == 1  # aucun appel après le refus


def test_one_retry_after_a_network_cut_then_the_session_stops(tmp_path: Path) -> None:
    server = FakeServer([OSError("coupure"), 200])
    c = client(tmp_path, server)
    c.get(entsoe.control_request())
    assert c.calls == 2
    assert c.budget.used_today() == 2.0  # la nouvelle tentative compte


def test_the_daily_cap_refuses_the_call_before_it_is_made(tmp_path: Path) -> None:
    server = FakeServer([200])
    budget = w.Budget(tmp_path / "journal.json", tmp_path / "ARRET.json", cap=0)
    c = entsoe.Client(TOKEN, tmp_path / "cache", budget, fetch=server, sleep=lambda s: None)
    with pytest.raises(w.DailyCapReachedError):
        c.get(entsoe.control_request())
    assert server.urls == []


def test_load_token_reads_the_key_without_quoting_the_file(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text(f"AUTRE=x\n{entsoe.TOKEN_KEY}={TOKEN}\n", encoding="utf-8")
    assert entsoe.load_token(env) == TOKEN
    env.write_text(f"{entsoe.TOKEN_KEY}=\nAUTRE={TOKEN}\n", encoding="utf-8")
    with pytest.raises(entsoe.TokenMissingError) as missing:
        entsoe.load_token(env)
    assert TOKEN not in str(missing.value)


def test_only_the_entsoe_host_is_allowed() -> None:
    with pytest.raises(ValueError, match="hôte"):
        entsoe.urllib_fetch("https://example.org/api?securityToken=x")


def test_structure_describes_xml_and_zip_answers_without_their_values() -> None:
    xml = b"<Doc><Price.amount>61.1</Price.amount></Doc>"
    assert entsoe.structure(xml) == {"format": "xml", "balises": ["Doc", "Price.amount"]}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("a.xml", xml)
    out = entsoe.structure(buffer.getvalue())
    assert out["format"] == "zip" and out["fichiers"] == ["a.xml"]
    assert "61.1" not in str(out)


NS = "urn:iec62325.351:tc57wg16:451-6:balancingdocument:4:4"


def document(series: list[tuple[str, str, list[tuple[int, float]]]], start: str, end: str) -> bytes:
    """Balancing_MarketDocument fabriqué : (catégorie, résolution, [(position, prix)])."""
    parts = [f'<?xml version="1.0" encoding="UTF-8"?><Balancing_MarketDocument xmlns="{NS}">']
    for i, (category, resolution, points) in enumerate(series, start=1):
        pts = "".join(
            f"<Point><position>{p}</position><imbalance_Price.amount>{v}</imbalance_Price.amount>"
            f"<imbalance_Price.category>{category}</imbalance_Price.category></Point>"
            for p, v in points
        )
        parts.append(
            f"<TimeSeries><mRID>{i}</mRID><curveType>A03</curveType><Period><timeInterval>"
            f"<start>{start}</start><end>{end}</end></timeInterval>"
            f"<resolution>{resolution}</resolution>{pts}</Period></TimeSeries>"
        )
    parts.append("</Balancing_MarketDocument>")
    return "".join(parts).encode()


def test_parse_prices_fills_the_gaps_of_a03_curves_with_the_last_value() -> None:
    body = document(
        [("A04", "PT15M", [(1, 10.0), (3, 30.0)]), ("A05", "PT15M", [(1, 11.0), (2, 22.0)])],
        "2025-01-15T00:00Z",
        "2025-01-15T01:00Z",
    )
    out = entsoe.parse_prices(body)
    assert out["pre_positif"].tolist() == [10.0, 10.0, 30.0, 30.0]
    assert out["pre_negatif"].tolist() == [11.0, 22.0, 22.0, 22.0]
    assert out.index[0] == pd.Timestamp("2025-01-15T00:00Z")
    assert out["pas"].tolist() == [15, 15, 15, 15]


def test_parse_prices_reads_zip_answers_and_thirty_minute_periods() -> None:
    xml = document(
        [("A04", "PT30M", [(1, 5.0)]), ("A05", "PT30M", [(1, 6.0)])],
        "2024-06-01T00:00Z",
        "2024-06-01T01:00Z",
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("prix.xml", xml)
    out = entsoe.parse_prices(buffer.getvalue())
    assert len(out) == 2 and set(out["pas"]) == {30}


def test_parse_prices_refuses_entities_and_unknown_categories() -> None:
    with pytest.raises(ValueError, match="DOCTYPE"):
        entsoe.parse_prices(b'<!DOCTYPE x [<!ENTITY a "b">]><x/>')
    bad = document([("A06", "PT15M", [(1, 1.0)])], "2025-01-15T00:00Z", "2025-01-15T00:15Z")
    with pytest.raises(ValueError, match="catégories"):
        entsoe.parse_prices(bad)
