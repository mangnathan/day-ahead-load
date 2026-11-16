"""Mesure quotidienne de l'heure de disponibilité du calcul ECMWF IFS 9 km chez Open-Meteo.

Le point de métadonnées `data/ecmwf_ifs/static/meta.json` décrit le dernier calcul publié :
heure d'initialisation, heure de disponibilité, heure de modification. Il ne garde que le
dernier calcul : une mesure par jour, vers 10 h UTC, tombe en principe sur le calcul de 00 UTC
(disponible vers 6 h 40 UTC d'après la mesure du 14/11/2026, le calcul de 06 UTC arrivant vers
12 h 40 UTC). Chaque ligne garde l'heure d'initialisation : une ligne tombée sur un autre calcul
reste juste et se repère.

Garde-fous :
- une ligne par jour au plus : la ligne du jour présente, rien n'est appelé ;
- une coupure réseau ou une réponse 5xx donne lieu à une seule nouvelle tentative, après une
  pause ; si elle échoue aussi, une ligne « échec » est écrite, pour que le trou reste visible ;
- au premier refus de quota (429), jamais retenté, un fichier d'arrêt est écrit et plus aucun
  appel n'est fait tant qu'une personne ne l'a pas retiré.

Bibliothèque standard seulement.
"""

from __future__ import annotations

import csv
import json
import time
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
MAX_ROWS_PER_DAY = 1
RETRY_WAIT_S = 120.0
COLUMNS = (
    "date_appel_utc",
    "heure_appel_utc",
    "statut",
    "initialisation_utc",
    "disponibilite_utc",
    "modification_utc",
    "delai_disponibilite_h",
    "detail",
)
USER_AGENT = "day-ahead-load/0.0 (mesure de disponibilite)"

Fetch = Callable[[str], tuple[int, bytes]]


class TransientFailureError(RuntimeError):
    """Coupure réseau ou réponse 5xx."""


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


def _base_row(called_at: datetime, status: str) -> dict[str, str]:
    row = dict.fromkeys(COLUMNS, "")
    row["date_appel_utc"] = called_at.date().isoformat()
    row["heure_appel_utc"] = called_at.isoformat(timespec="seconds")
    row["statut"] = status
    return row


def row_from_meta(meta: dict[str, Any], called_at: datetime) -> dict[str, str]:
    init = int(meta["last_run_initialisation_time"])
    available = int(meta["last_run_availability_time"])
    row = _base_row(called_at, "ok")
    row["initialisation_utc"] = _utc(init)
    row["disponibilite_utc"] = _utc(available)
    row["modification_utc"] = _utc(int(meta["last_run_modification_time"]))
    row["delai_disponibilite_h"] = f"{(available - init) / 3600:.2f}"
    return row


def rows_on(path: Path, day: str) -> int:
    if not path.exists():
        return 0
    with path.open(encoding="utf-8", newline="") as f:
        return sum(1 for row in csv.DictReader(f) if row["date_appel_utc"] == day)


def _append(table: Path, row: dict[str, str]) -> None:
    new_file = not table.exists()
    with table.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        if new_file:
            writer.writeheader()
        writer.writerow(row)


def _attempt(fetch: Fetch) -> tuple[int, bytes]:
    try:
        status, body = fetch(META_URL)
    except OSError as error:  # URLError, délai dépassé, connexion coupée
        raise TransientFailureError(f"connexion interrompue : {error}") from error
    if 500 <= status < 600:
        raise TransientFailureError(f"réponse {status} du serveur")
    return status, body


def record(
    directory: Path,
    fetch: Fetch = urllib_fetch,
    now: datetime | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    """Fait au plus deux tentatives et ajoute une ligne. Renvoie ce qui s'est passé, en clair."""
    called_at = now or datetime.now(UTC)
    stop = directory / STOP_NAME
    if stop.exists():
        return "arrêt : refus de quota antérieur, aucun appel"
    table = directory / CSV_NAME
    if rows_on(table, called_at.date().isoformat()) >= MAX_ROWS_PER_DAY:
        return "déjà mesuré aujourd'hui, aucun appel"
    try:
        status, body = _attempt(fetch)
    except TransientFailureError:
        sleep(RETRY_WAIT_S)
        try:
            status, body = _attempt(fetch)
        except TransientFailureError as second:
            row = _base_row(called_at, "echec")
            row["detail"] = str(second)[:200]
            _append(table, row)
            return f"deux échecs de suite, ligne « échec » écrite : {second}"
    if status == 429:
        stop.write_text(
            json.dumps(
                {
                    "date": called_at.isoformat(timespec="seconds"),
                    "reponse": body[:500].decode(errors="replace"),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return "refus de quota (429) : fichier d'arrêt écrit"
    if status != 200:
        row = _base_row(called_at, "echec")
        row["detail"] = f"réponse {status}"
        _append(table, row)
        return f"réponse {status}, ligne « échec » écrite"
    row = row_from_meta(json.loads(body), called_at)
    _append(table, row)
    return f"mesuré : calcul {row['initialisation_utc']}, délai {row['delai_disponibilite_h']} h"
