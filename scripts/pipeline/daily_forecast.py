"""v0.4 : prévision du lendemain, avant midi la veille (journal des choix, entrée 27).

Lancé deux fois par jour par le workflow « Prévision quotidienne » :

    uv run python scripts/pipeline/daily_forecast.py --donnees donnees --depart premier
    uv run python scripts/pipeline/daily_forecast.py --donnees donnees --depart second

`--donnees` est la copie locale de la branche `donnees/previsions`. Le script :

1. ne fait rien si la prévision du lendemain existe déjà (une seule par jour livré) ;
2. vérifie que le calcul de 00 UTC de la veille est disponible (dépôt sur la copie AWS
   d'Open-Meteo plus 2 h, et calcul servi par l'API) ; sinon, au premier départ, il s'arrête
   proprement, et au second il applique le calcul de secours ;
3. complète les calculs des quatre jours précédents s'ils manquent ;
4. écrit la prévision, ou une absence motivée si une entrée manque, et affiche l'empreinte
   sha256 du contenu dans le journal de l'exécution.

Le statut « à l'heure » ou « en retard » est ajouté ensuite par `stamp_forecast.py`, à partir
des heures enregistrées par GitHub.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from day_ahead_load import availability as av
from day_ahead_load import daily, frozen
from day_ahead_load import temperature_index as ti
from day_ahead_load import weather as w
from day_ahead_load import weather_features as wf
from day_ahead_load.weather_points import POINTS

ARTEFACTS = Path("artefacts/v0.4")
CONTROL = Path("docs/v0.0-faisabilite/data/meteo-controle.json")
WEIGHTS = Path("docs/v0.0-faisabilite/data/indice-temperature-poids.json")
DAILY_CAP = 100
MIN_SERVED_HOURS = 48  # un calcul servi a au moins 48 heures de température


def output(name: str, value: str) -> None:
    """Sortie d'étape pour GitHub Actions, sans effet hors d'un workflow."""
    target = os.environ.get("GITHUB_OUTPUT")
    if target:
        with open(target, "a", encoding="utf-8") as out:
            out.write(f"{name}={value}\n")


def elevations() -> dict[str, float]:
    summary = json.loads(CONTROL.read_text(encoding="utf-8"))
    return {entry["commune"]: float(entry["altitude_m"]) for entry in summary["points"]}


def fetch_run(run_day: date, downloader: w.Downloader) -> pd.DataFrame:
    """Indice national horaire du calcul de 00 UTC de `run_day`, aux 12 points."""
    source = w.SOURCES["ecmwf_00utc"]
    heights = elevations()
    weights = ti.normalize(
        json.loads(WEIGHTS.read_text(encoding="utf-8"))["resultats"]["consommation"][
            "poids_sur_2016_2023"
        ]
    )
    by_point = {}
    for point in POINTS:
        params = {
            "latitude": f"{point.latitude}",
            "longitude": f"{point.longitude}",
            "elevation": f"{heights[point.commune]}",
            "hourly": ",".join(w.VARIABLES),
            "models": source.model,
            "timezone": "GMT",
            "cell_selection": "land",
            "run": f"{run_day}T00:00",
            "forecast_days": f"{w.RUN_FORECAST_DAYS}",
        }
        request = w.Request(
            "ecmwf_00utc", point, run_day, run_day, w.checked_url(source.url, params)
        )
        record = downloader.get(request)
        by_point[point] = w.hourly_frame(record["reponse"]).astype(float)
    return wf.national(by_point, weights)


def deposit_time(run_day: date) -> datetime | None:
    """Heure de dépôt du calcul de 00 UTC sur la copie AWS d'Open-Meteo, ou None."""
    fetched = av.fetch_once_retry(av.AWS_RUN_URL.format(day=run_day), av.urllib_fetch, sleep=_sleep)
    if fetched.status != "ok":
        return None
    created = json.loads(fetched.body).get("created_at")
    return pd.Timestamp(created).tz_convert("UTC").to_pydatetime() if created else None


def _sleep(seconds: float) -> None:
    import time

    time.sleep(seconds)


def load_runs(folder: Path, days: list[date]) -> dict[date, pd.DataFrame]:
    runs = {}
    for d in days:
        path = folder / f"run-{d}.csv"
        if path.exists():
            runs[d] = daily.run_from_csv(path.read_text(encoding="utf-8"))
    return runs


def load_level(folder: Path, day: date) -> float | None:
    month = (day - timedelta(days=1)).strftime("%Y-%m")
    path = folder / f"{month}.json"
    if not path.exists():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))["niveaux"].get(str(day))
    return None if value is None else float(value)


def load_artefacts() -> tuple[str, dict[str, dict[str, float]], dict[str, Any]]:
    meta = json.loads((ARTEFACTS / "meta.json").read_text(encoding="utf-8"))
    model_bytes = (ARTEFACTS / meta["modele"]["fichier"]).read_bytes()
    offsets_bytes = (ARTEFACTS / meta["fourchette"]["fichier"]).read_bytes()
    if frozen.sha256(model_bytes) != meta["modele"]["sha256"]:
        raise RuntimeError("le modèle figé ne correspond pas à son empreinte")
    if frozen.sha256(offsets_bytes) != meta["fourchette"]["sha256"]:
        raise RuntimeError("la fourchette figée ne correspond pas à son empreinte")
    summary = {
        "modele_sha256": meta["modele"]["sha256"],
        "configuration_sha256": meta["modele"]["configuration_sha256"],
        "fourchette_sha256": meta["fourchette"]["sha256"],
        "commit_des_artefacts": meta["commit"],
    }
    return model_bytes.decode("utf-8"), json.loads(offsets_bytes), summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--donnees", type=Path, required=True)
    parser.add_argument("--depart", choices=["premier", "second"], required=True)
    args = parser.parse_args()
    root: Path = args.donnees

    now = daily.now_utc()
    day = daily.delivered_day(now)
    run_day = day - timedelta(days=1)
    target = root / "previsions" / f"{day}.json"
    output("jour", str(day))
    if target.exists() or (root / "absences" / f"{day}.json").exists():
        print(f"{day} : déjà traité, rien à écrire")
        return 0

    with tempfile.TemporaryDirectory() as tmp:
        budget = w.Budget(Path(tmp) / "journal.json", Path(tmp) / "ARRET.json", cap=DAILY_CAP)
        downloader = w.Downloader(Path(tmp) / "cache", budget)
        meteo = root / "meteo"
        secours = False
        # Calcul de la veille : seulement s'il est déposé depuis 2 h et servi par l'API.
        if not (meteo / f"run-{run_day}.csv").exists():
            deposit = deposit_time(run_day)
            ready = deposit is not None and daily.run_ready(now, deposit)
            frame = fetch_run(run_day, downloader) if ready else None
            served = (
                frame is not None and int(frame["temperature_2m"].notna().sum()) >= MIN_SERVED_HOURS
            )
            if served and frame is not None:
                daily.write_once(meteo / f"run-{run_day}.csv", daily.run_to_csv(frame))
            elif args.depart == "premier":
                print(
                    f"calcul de 00 UTC du {run_day} pas encore disponible : "
                    "le second départ réessaiera"
                )
                return 0
            else:
                secours = True
                print(f"calcul de 00 UTC du {run_day} indisponible : calcul de secours")
        # Calculs plus anciens, publiés depuis longtemps : complétés s'ils manquent.
        for k in range(2, daily.RUN_DAYS_BACK + 1):
            older = day - timedelta(days=k)
            if not (meteo / f"run-{older}.csv").exists():
                daily.write_once(
                    meteo / f"run-{older}.csv", daily.run_to_csv(fetch_run(older, downloader))
                )
        print(f"{downloader.calls} appels à Open-Meteo")

    days = [day - timedelta(days=k) for k in range(daily.RUN_DAYS_BACK, 0, -1)]
    inputs = daily.Inputs(
        day, daily.runs_frame(load_runs(meteo, days)), load_level(root / "niveau", day)
    )
    model_text, offsets, artefacts = load_artefacts()
    result = daily.forecast(inputs, model_text, offsets)
    execution = {
        "workflow_run_id": os.environ.get("GITHUB_RUN_ID"),
        "depart": args.depart,
        "calcul_de_secours_pour_la_veille": secours,
    }
    if isinstance(result, daily.Absence):
        body = {"jour_livre": str(day), "cause": result.cause, "execution": execution}
        daily.write_once(
            root / "absences" / f"{day}.json", json.dumps(body, indent=2, ensure_ascii=False) + "\n"
        )
        print(f"{day} : pas de prévision, {result.cause}")
        output("absence", "true")
        return 1
    content = daily.core(day, result, inputs, artefacts)
    digest = daily.content_sha256(content)
    record = {"contenu": content, "contenu_sha256": digest, "execution": execution}
    daily.write_once(target, json.dumps(record, indent=1, ensure_ascii=False) + "\n")
    print(f"{day} : prévision écrite, empreinte sha256 du contenu {digest}")
    output("fichier", str(target))
    output("empreinte", digest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
