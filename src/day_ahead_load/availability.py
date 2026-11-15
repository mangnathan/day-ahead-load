"""Mesure quotidienne de l'heure de disponibilité du calcul ECMWF IFS 9 km chez Open-Meteo.

Le point de métadonnées `data/ecmwf_ifs/static/meta.json` décrit le dernier calcul publié :
heure d'initialisation, heure de disponibilité, heure de modification. Il ne garde que le
dernier calcul : une mesure par jour, vers 10 h UTC, tombe en principe sur le calcul de 00 UTC
(disponible vers 6 h 40 UTC d'après la mesure du 14/11/2026, le calcul de 06 UTC arrivant vers
12 h 40 UTC). Chaque ligne garde l'heure d'initialisation : une ligne tombée sur un autre calcul
reste juste et se repère.

Garde-fous : un appel par jour au plus (la ligne du jour présente, rien n'est appelé) ; au
premier refus de quota (429), un fichier d'arrêt est écrit et plus aucun appel n'est fait tant
qu'une personne ne l'a pas retiré. Bibliothèque standard seulement.
"""

from __future__ import annotations

import csv
import json
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

META_URL = "https://api.open-meteo.com/data/ecmwf_ifs/static/meta.json"
CSV_NAME = "disponibilite-ecmwf-ifs.csv"
STOP_NAME = "ARRET-QUOTA.json"
MAX_CALLS_PER_DAY = 1
COLUMNS = (
    "date_appel_utc",
    "heure_appel_utc",
    "initialisation_utc",
    "disponibilite_utc",
    "modification_utc",
    "delai_disponibilite_h",
)
USER_AGENT = "day-ahead-load/0.0 (mesure de disponibilite)"

Fetch = Callable[[str], tuple[int, bytes]]


def urllib_fetch(url: str) -> tuple[int, bytes]:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "api.open-meteo.com":
        raise ValueError(f"adresse refusée : {url}")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310
    try:
        # Schéma et hôte vérifiés ci-dessus.
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def _utc(seconds: int) -> str:
    return datetime.fromtimestamp(seconds, UTC).isoformat(timespec="seconds")


def row_from_meta(meta: dict[str, Any], called_at: datetime) -> dict[str, str]:
    init = int(meta["last_run_initialisation_time"])
    available = int(meta["last_run_availability_time"])
    return {
        "date_appel_utc": called_at.date().isoformat(),
        "heure_appel_utc": called_at.isoformat(timespec="seconds"),
        "initialisation_utc": _utc(init),
        "disponibilite_utc": _utc(available),
        "modification_utc": _utc(int(meta["last_run_modification_time"])),
        "delai_disponibilite_h": f"{(available - init) / 3600:.2f}",
    }


def calls_on(path: Path, day: str) -> int:
    if not path.exists():
        return 0
    with path.open(encoding="utf-8", newline="") as f:
        return sum(1 for row in csv.DictReader(f) if row["date_appel_utc"] == day)


def record(directory: Path, fetch: Fetch = urllib_fetch, now: datetime | None = None) -> str:
    """Fait au plus un appel et ajoute une ligne. Renvoie ce qui s'est passé, en clair."""
    called_at = now or datetime.now(UTC)
    stop = directory / STOP_NAME
    if stop.exists():
        return "arrêt : refus de quota antérieur, aucun appel"
    table = directory / CSV_NAME
    if calls_on(table, called_at.date().isoformat()) >= MAX_CALLS_PER_DAY:
        return "déjà mesuré aujourd'hui, aucun appel"
    status, body = fetch(META_URL)
    if status == 429:
        stop.write_text(
            json.dumps(
                {"date": called_at.isoformat(timespec="seconds"), "reponse": body[:500].decode()},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return "refus de quota (429) : fichier d'arrêt écrit"
    if status != 200:
        raise RuntimeError(f"réponse {status} : {body[:300]!r}")
    row = row_from_meta(json.loads(body), called_at)
    new_file = not table.exists()
    with table.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        if new_file:
            writer.writeheader()
        writer.writerow(row)
    return f"mesuré : calcul {row['initialisation_utc']}, délai {row['delai_disponibilite_h']} h"
