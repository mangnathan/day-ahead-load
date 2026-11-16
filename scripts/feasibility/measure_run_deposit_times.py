"""Étude de faisabilité : heure de dépôt de chaque calcul ECMWF de 00 UTC sur la copie AWS.

Le dépôt open-data d'Open-Meteo sur AWS garde, pour chaque calcul, un fichier
`data_run/ecmwf_ifs/AAAA/MM/JJ/HHMMZ/meta.json` dont le champ `created_at` est l'heure de dépôt
du calcul (vérifié le 16/11/2026 : 12:01:59 pour le calcul de 06 UTC, contre 12:01:23 dans le
fichier de métadonnées général). Ces fichiers sont conservés environ trois mois.

Pour chaque calcul de 00 UTC disponible, le script calcule la marge avant midi, heure de Paris,
avec la règle prudente retenue : heure de dépôt sur AWS + 2 h. Il sépare l'heure d'été et
l'heure d'hiver.

Appels : une liste par mois plus un fichier par calcul, sur la copie AWS (hors quota de l'API
Open-Meteo), une requête par seconde au plus, arrêt au premier 403 ou 429.

    uv run python scripts/feasibility/measure_run_deposit_times.py
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

BUCKET = "https://openmeteo.s3.amazonaws.com"
PREFIX = "data_run/ecmwf_ifs"
MONTHS = ("2026/08", "2026/09", "2026/10", "2026/11")
SAFETY_MARGIN = timedelta(hours=2)
PARIS = ZoneInfo("Europe/Paris")
RAW = Path("data/raw/depots-ecmwf")
SUMMARY = Path("docs/v0.0-faisabilite/data/depots-calculs-00utc.json")
USER_AGENT = "day-ahead-load/0.0 (etude de faisabilite)"


class StopError(RuntimeError):
    pass


_last_call = 0.0


def get(url: str) -> bytes:
    global _last_call
    if not url.startswith(BUCKET + "/"):
        raise ValueError(f"adresse refusée : {url}")
    wait = 1.0 - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            body: bytes = response.read()
            return body
    except urllib.error.HTTPError as error:
        if error.code in (403, 429):
            raise StopError(f"réponse {error.code} : arrêt") from error
        raise


def runs_00z() -> list[date]:
    days = []
    for month in MONTHS:
        listing = get(f"{BUCKET}/?list-type=2&prefix={PREFIX}/{month}/&delimiter=/").decode()
        for day in re.findall(rf"<Prefix>{PREFIX}/{month}/(\d\d)/</Prefix>", listing):
            y, m = month.split("/")
            days.append(date(int(y), int(m), int(day)))
    return sorted(days)


def created_at(day: date) -> datetime | None:
    path = RAW / f"{day}-0000Z.json"
    if not path.exists():
        url = f"{BUCKET}/{PREFIX}/{day:%Y/%m/%d}/0000Z/meta.json"
        try:
            body = get(url)
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            raise
        RAW.mkdir(parents=True, exist_ok=True)
        meta = json.loads(body)
        path.write_text(
            json.dumps({k: meta[k] for k in ("created_at", "reference_time")}),
            encoding="utf-8",
            newline="\n",
        )
    stored: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    if not stored["reference_time"].startswith(f"{day}T00:00"):
        raise ValueError(f"calcul inattendu : {stored}")
    return datetime.fromisoformat(stored["created_at"].replace("Z", "+00:00"))


def summarize(values: list[float]) -> dict[str, float | int]:
    ordered = sorted(values)
    return {
        "calculs": len(ordered),
        "min": round(ordered[0], 2),
        "mediane": round(ordered[len(ordered) // 2], 2),
        "max": round(ordered[-1], 2),
    }


def main() -> None:
    rows: list[dict[str, Any]] = []
    for day in runs_00z():
        deposit = created_at(day)
        if deposit is None:
            continue
        noon = datetime(day.year, day.month, day.day, 12, tzinfo=PARIS).astimezone(UTC)
        rows.append(
            {
                "calcul": f"{day}T00:00Z",
                "depot_aws_utc": deposit.isoformat(),
                "delai_depot_h": round(
                    (deposit - datetime(*day.timetuple()[:3], tzinfo=UTC)).total_seconds() / 3600, 2
                ),
                "heure_ete": noon.hour == 10,
                "marge_avant_midi_h": round(
                    (noon - deposit - SAFETY_MARGIN).total_seconds() / 3600, 2
                ),
            }
        )
    summer = [r["marge_avant_midi_h"] for r in rows if r["heure_ete"]]
    winter = [r["marge_avant_midi_h"] for r in rows if not r["heure_ete"]]
    summary = {
        "source": (
            "Open-Meteo, dépôt open-data sur AWS, "
            "data_run/ecmwf_ifs/<calcul>/meta.json, champ created_at"
        ),
        "regle": (
            "Heure retenue = dépôt sur AWS + 2 h ; marge = midi, heure de Paris, "
            "la veille du jour livré, moins cette heure."
        ),
        "delai_depot_h": summarize([r["delai_depot_h"] for r in rows]),
        "marge_heure_ete_h": summarize(summer) if summer else None,
        "marge_heure_hiver_h": summarize(winter) if winter else None,
        "calculs_hors_marge": [r["calcul"] for r in rows if r["marge_avant_midi_h"] < 0],
        "par_calcul": rows,
    }
    SUMMARY.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    print(
        json.dumps(
            {k: v for k, v in summary.items() if k != "par_calcul"}, indent=2, ensure_ascii=False
        )
    )


if __name__ == "__main__":
    main()
