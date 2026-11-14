"""Étude de faisabilité : météo Open-Meteo aux 12 points, sous plafond d'appels.

Trois étapes, dans cet ordre :

    uv run python scripts/feasibility/download_weather.py estimation
    uv run python scripts/feasibility/download_weather.py controle
    uv run python scripts/feasibility/download_weather.py telecharger

- `estimation` : nombre d'appels prévus, sans aucun appel réseau ;
- `controle` : altitude de chaque point (fixée une fois, puis passée dans tous les appels),
  première requête de chaque source par point, contrôle terrestre de la maille et convention
  du rayonnement. Écrit `docs/v0.0-faisabilite/data/meteo-controle.json` ;
- `telecharger` : tout le reste, source par source, jusqu'au plafond local du jour. Relancer
  le lendemain reprend depuis le cache. Refuse de partir si un point n'a pas passé le contrôle.

Au premier refus de quota (429), un fichier d'arrêt est écrit et plus aucun appel n'est fait
tant qu'il existe.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from day_ahead_load import weather as w
from day_ahead_load.weather_points import POINTS, Point

RAW_ROOT = Path("data/raw/meteo")
LEDGER = RAW_ROOT / "journal-appels.json"
STOP_FILE = RAW_ROOT / "ARRET-QUOTA.json"
CONTROL = Path("docs/v0.0-faisabilite/data/meteo-controle.json")
DOWNLOAD_ORDER = ("ifs_historique", "era5", "ecmwf_00utc")


def downloader() -> w.Downloader:
    return w.Downloader(RAW_ROOT, w.Budget(LEDGER, STOP_FILE))


def run_estimation() -> None:
    per_source = w.estimate(POINTS)
    total = sum(per_source.values())
    print(json.dumps({"appels_par_source": per_source, "total": total}, indent=2))
    print(f"plafond local {w.DAILY_CAP} par jour : {-(-total // w.DAILY_CAP)} jours au moins")


def commune_at(dl: w.Downloader) -> Any:
    def lookup(lat: float, lon: float) -> str | None:
        # geo.api.gouv.fr ne relève pas du quota Open-Meteo : appel direct, hors budget.
        url = w.checked_url(
            w.REVERSE_GEOCODING_URL,
            {"lat": f"{lat}", "lon": f"{lon}", "fields": "nom,code", "format": "json"},
        )
        response = dl.fetch(url)
        if response.status != 200:
            raise RuntimeError(f"geo.api.gouv.fr : réponse {response.status}")
        found = json.loads(response.body)
        return f"{found[0]['nom']} ({found[0]['code']})" if found else None

    return lookup


def run_control() -> None:
    dl = downloader()
    url = w.checked_url(
        w.ELEVATION_URL,
        {
            "latitude": ",".join(f"{p.latitude}" for p in POINTS),
            "longitude": ",".join(f"{p.longitude}" for p in POINTS),
        },
    )
    payload, quota = dl.call(url)
    elevations = [float(e) for e in payload["elevation"]]
    lookup = commune_at(dl)
    points = []
    for point, elevation in zip(POINTS, elevations, strict=True):
        checks = []
        conventions = {}
        for source in DOWNLOAD_ORDER:
            record = dl.get(w.requests_for(source, point, elevation)[0])
            response = record["reponse"]
            checks.append(w.land_check(point, source, response, lookup))
            frame = w.hourly_frame(response)
            conventions[source] = w.radiation_convention(
                frame["shortwave_radiation"], point.latitude, point.longitude
            )
        points.append(
            {
                **point.__dict__,
                "altitude_m": elevation,
                "mailles": checks,
                "convention_rayonnement": conventions,
            }
        )
    summary = {
        "date": datetime.now(UTC).date().isoformat(),
        "parametres_communs": {
            "variables": list(w.VARIABLES),
            "timezone": "GMT",
            "cell_selection": "land",
            "altitude": "fixée par l'API d'altitude d'Open-Meteo, passée dans tous les appels",
        },
        "appel_altitude_12_points": {"en_tetes_quota": quota},
        "points": points,
    }
    CONTROL.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{dl.calls} appels ; contrôle écrit dans {CONTROL}")


def controlled_points() -> list[tuple[Point, float]]:
    if not CONTROL.exists():
        raise SystemExit("lancer d'abord l'étape controle")
    summary = json.loads(CONTROL.read_text(encoding="utf-8"))
    out = []
    for entry in summary["points"]:
        failed = [m["source"] for m in entry["mailles"] if not m["centre_sur_commune_francaise"]]
        if failed:
            raise SystemExit(f"{entry['nom']} : maille à examiner ({failed}) avant téléchargement")
        point = next(p for p in POINTS if p.commune == entry["commune"])
        out.append((point, float(entry["altitude_m"])))
    return out


def run_download() -> None:
    dl = downloader()
    points = controlled_points()
    try:
        for source in DOWNLOAD_ORDER:
            for point, elevation in points:
                for request in w.requests_for(source, point, elevation):
                    dl.get(request)
            print(f"{source} : complet")
    except w.DailyCapReachedError as stop:
        print(f"{stop} ({dl.calls} appels dans cette session) : relancer demain")
    except w.NetworkInterruptedError as stop:
        print(f"{stop} ({dl.calls} appels dans cette session) : séance arrêtée, relancer demain")
    except w.QuotaRefusedError as stop:
        print(f"ARRÊT : {stop}. Voir {STOP_FILE}.", file=sys.stderr)
        raise SystemExit(2) from stop


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("etape", choices=["estimation", "controle", "telecharger"])
    args = parser.parse_args()
    {"estimation": run_estimation, "controle": run_control, "telecharger": run_download}[
        args.etape
    ]()


if __name__ == "__main__":
    main()
