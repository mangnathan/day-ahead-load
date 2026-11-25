from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import ModuleType

import numpy as np
import pandas as pd
import pytest

from day_ahead_load import daily
from day_ahead_load import modelling as md

DAY = date(2026, 11, 26)
NOW = datetime(2026, 11, 25, 8, 20, tzinfo=UTC)
SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "pipeline" / "daily_forecast.py"


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("daily_forecast", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def national_run(run_day: date) -> pd.DataFrame:
    hours = pd.date_range(pd.Timestamp(run_day, tz="UTC"), periods=72, freq="h")
    return pd.DataFrame(
        {
            "temperature_2m": 8.0 + 0.1 * hours.hour.to_numpy(dtype=float),
            "cloud_cover": 50.0,
            "wind_speed_10m": 5.0,
            "shortwave_radiation": 100.0,
        },
        index=hours,
    )


@pytest.fixture
def script(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[ModuleType, Path, list[date]]:
    module = load_script()
    fetched: list[date] = []
    rng = np.random.default_rng(0)
    x = pd.DataFrame({name: rng.normal(size=1_000) for name in md.FEATURES})
    model = str(md.fit(x, pd.Series(50_000.0 + 1_000.0 * x["temperature_2m"])).model_to_string())
    offsets = {
        str(s): {"0.025": -2e3, "0.1": -1e3, "0.5": 0.0, "0.9": 1e3, "0.975": 2e3, "0.4616": -50.0}
        for s in range(48)
    }

    def fake_fetch(run_day: date, downloader: object) -> pd.DataFrame:
        fetched.append(run_day)
        return national_run(run_day)

    monkeypatch.setattr(module.daily, "now_utc", lambda: NOW)
    monkeypatch.setattr(module, "fetch_run", fake_fetch)
    monkeypatch.setattr(module, "load_artefacts", lambda: (model, offsets, {"modele_sha256": "x"}))
    level = tmp_path / "niveau" / "2026-11.json"
    level.parent.mkdir(parents=True)
    level.write_text(json.dumps({"niveaux": {str(DAY): 52_000.0}}), encoding="utf-8")
    return module, tmp_path, fetched


def run(module: ModuleType, root: Path, start: str, monkeypatch: pytest.MonkeyPatch) -> int:
    monkeypatch.setattr(sys, "argv", ["daily_forecast", "--donnees", str(root), "--depart", start])
    return int(module.main())


def test_first_start_stops_cleanly_when_the_run_is_not_ready(
    script: tuple[ModuleType, Path, list[date]], monkeypatch: pytest.MonkeyPatch
) -> None:
    module, root, fetched = script
    monkeypatch.setattr(module, "deposit_time", lambda d: NOW - timedelta(minutes=30))
    assert run(module, root, "premier", monkeypatch) == 0
    assert not (root / "previsions" / f"{DAY}.json").exists()
    assert fetched == []


def test_second_start_uses_the_fallback_run_and_records_it(
    script: tuple[ModuleType, Path, list[date]], monkeypatch: pytest.MonkeyPatch
) -> None:
    module, root, fetched = script
    monkeypatch.setattr(module, "deposit_time", lambda d: None)
    assert run(module, root, "second", monkeypatch) == 0
    record = json.loads((root / "previsions" / f"{DAY}.json").read_text(encoding="utf-8"))
    assert record["execution"]["calcul_de_secours_pour_la_veille"] is True
    assert DAY - timedelta(days=1) not in fetched
    assert record["contenu_sha256"] == daily.content_sha256(record["contenu"])


def test_a_ready_run_gives_one_forecast_that_a_second_run_never_overwrites(
    script: tuple[ModuleType, Path, list[date]], monkeypatch: pytest.MonkeyPatch
) -> None:
    module, root, fetched = script
    monkeypatch.setattr(module, "deposit_time", lambda d: NOW - timedelta(hours=3))
    assert run(module, root, "premier", monkeypatch) == 0
    path = root / "previsions" / f"{DAY}.json"
    first = path.read_bytes()
    assert sorted(fetched) == [DAY - timedelta(days=k) for k in range(4, 0, -1)]
    assert run(module, root, "second", monkeypatch) == 0
    assert path.read_bytes() == first
    content = json.loads(first)["contenu"]
    assert len(content["demi_heures"]) == 48
    assert "pas des données RTE" in content["etiquettes"][0]


def test_a_missing_level_gives_an_absence_and_a_failure(
    script: tuple[ModuleType, Path, list[date]], monkeypatch: pytest.MonkeyPatch
) -> None:
    module, root, _ = script
    (root / "niveau" / "2026-11.json").unlink()
    monkeypatch.setattr(module, "deposit_time", lambda d: NOW - timedelta(hours=3))
    assert run(module, root, "premier", monkeypatch) == 1
    absence = json.loads((root / "absences" / f"{DAY}.json").read_text(encoding="utf-8"))
    assert "niveau" in absence["cause"]
    assert not (root / "previsions" / f"{DAY}.json").exists()
