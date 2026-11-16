"""Mesure quotidienne de l'heure de disponibilité du calcul ECMWF IFS 9 km chez Open-Meteo.

Deux lectures du même fichier de métadonnées `data/ecmwf_ifs/static/meta.json`, qui décrit le
dernier calcul publié :

- l'API (`api.open-meteo.com`) : heure à laquelle le calcul est disponible pour nos appels.
  C'est la référence pour la règle de midi ;
- la copie publique sur AWS (`openmeteo.s3.amazonaws.com`) : heure du dépôt des fichiers,
  un peu plus tôt (12 h 01 contre 12 h 40 UTC pour le calcul de 06 UTC du 14/11/2026). Elle est
  lue chaque jour, car l'API est restée injoignable depuis la machine de GitHub.

Une mesure par jour, vers 10 h UTC, tombe en principe sur le calcul de 00 UTC. Chaque ligne
garde l'heure d'initialisation de chaque lecture : une lecture tombée sur un autre calcul reste
juste et se repère.

Garde-fous :
- une ligne par jour au plus : la ligne du jour présente, rien n'est appelé ;
- pour chaque source, une coupure réseau ou une réponse 5xx donne lieu à une seule nouvelle
  tentative après une pause ; un deuxième échec est noté dans la ligne, pour que le trou reste
  visible ;
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
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

SOURCES = {
    "api": "https://api.open-meteo.com/data/ecmwf_ifs/static/meta.json",
    "aws": "https://openmeteo.s3.amazonaws.com/data/ecmwf_ifs/static/meta.json",
}
ALLOWED_HOSTS = frozenset({"api.open-meteo.com", "openmeteo.s3.amazonaws.com"})
# Le fichier de la première version (une seule source) est gardé tel quel comme historique.
CSV_NAME = "disponibilite-ecmwf.csv"
STOP_NAME = "ARRET-QUOTA.json"
MAX_ROWS_PER_DAY = 1
RETRY_WAIT_S = 120.0
TIMEOUT_S = 30
COLUMNS = (
    "date_appel_utc",
    "heure_appel_utc",
    "statut_api",
    "initialisation_api_utc",
    "disponibilite_api_utc",
    "statut_aws",
    "initialisation_aws_utc",
    "disponibilite_aws_utc",
    "ecart_api_moins_aws_min",
    "detail",
)
USER_AGENT = "day-ahead-load/0.0 (mesure de disponibilite)"

Fetch = Callable[[str], tuple[int, bytes]]


class TransientFailureError(RuntimeError):
    """Coupure réseau ou réponse 5xx."""


class QuotaRefusedError(RuntimeError):
    """Réponse 429 : arrêt définitif."""


def urllib_fetch(url: str) -> tuple[int, bytes]:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise ValueError(f"adresse refusée : {url}")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310
    try:
        # Schéma et hôte vérifiés ci-dessus.
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:  # noqa: S310
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def _utc(seconds: int) -> str:
    return datetime.fromtimestamp(seconds, UTC).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Reading:
    status: str  # "ok" ou "echec"
    initialisation: int | None = None
    available: int | None = None
    detail: str = ""


def _attempt(fetch: Fetch, url: str) -> tuple[int, bytes]:
    try:
        status, body = fetch(url)
    except OSError as error:  # URLError, délai dépassé, connexion coupée
        raise TransientFailureError(f"connexion interrompue : {error}") from error
    if 500 <= status < 600:
        raise TransientFailureError(f"réponse {status} du serveur")
    return status, body


def read_source(url: str, fetch: Fetch, sleep: Callable[[float], None]) -> Reading:
    """Lit une source, avec au plus une nouvelle tentative. Lève QuotaRefusedError sur un 429."""
    try:
        status, body = _attempt(fetch, url)
    except TransientFailureError:
        sleep(RETRY_WAIT_S)
        try:
            status, body = _attempt(fetch, url)
        except TransientFailureError as second:
            return Reading("echec", detail=str(second)[:200])
    if status == 429:
        raise QuotaRefusedError(body[:500].decode(errors="replace"))
    if status != 200:
        return Reading("echec", detail=f"réponse {status}")
    meta: dict[str, Any] = json.loads(body)
    return Reading(
        "ok",
        int(meta["last_run_initialisation_time"]),
        int(meta["last_run_availability_time"]),
    )


def build_row(called_at: datetime, readings: Mapping[str, Reading]) -> dict[str, str]:
    row = dict.fromkeys(COLUMNS, "")
    row["date_appel_utc"] = called_at.date().isoformat()
    row["heure_appel_utc"] = called_at.isoformat(timespec="seconds")
    details = []
    for name, reading in readings.items():
        row[f"statut_{name}"] = reading.status
        if reading.initialisation is not None and reading.available is not None:
            row[f"initialisation_{name}_utc"] = _utc(reading.initialisation)
            row[f"disponibilite_{name}_utc"] = _utc(reading.available)
        if reading.detail:
            details.append(f"{name} : {reading.detail}")
    api, aws = readings.get("api"), readings.get("aws")
    if (
        api is not None
        and aws is not None
        and api.available is not None
        and aws.available is not None
        and api.initialisation == aws.initialisation
    ):
        row["ecart_api_moins_aws_min"] = f"{(api.available - aws.available) / 60:.1f}"
    row["detail"] = " ; ".join(details)
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


def record(
    directory: Path,
    fetch: Fetch = urllib_fetch,
    now: datetime | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    """Lit l'API puis AWS et ajoute une ligne. Renvoie ce qui s'est passé, en clair."""
    called_at = now or datetime.now(UTC)
    stop = directory / STOP_NAME
    if stop.exists():
        return "arrêt : refus de quota antérieur, aucun appel"
    table = directory / CSV_NAME
    if rows_on(table, called_at.date().isoformat()) >= MAX_ROWS_PER_DAY:
        return "déjà mesuré aujourd'hui, aucun appel"
    readings: dict[str, Reading] = {}
    for name, url in SOURCES.items():
        try:
            readings[name] = read_source(url, fetch, sleep)
        except QuotaRefusedError as refusal:
            stop.write_text(
                json.dumps(
                    {
                        "date": called_at.isoformat(timespec="seconds"),
                        "source": name,
                        "reponse": str(refusal),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            return f"refus de quota (429) sur {name} : fichier d'arrêt écrit"
    row = build_row(called_at, readings)
    _append(table, row)
    gap = row["ecart_api_moins_aws_min"] or "-"
    return f"api : {row['statut_api']}, aws : {row['statut_aws']}, écart {gap} min"


@dataclass(frozen=True)
class Availability:
    day: str
    initialisation_utc: str
    available_utc: datetime
    estimated: bool


def api_availability(rows: Iterable[Mapping[str, str]]) -> list[Availability]:
    """Heure de disponibilité sur l'API, jour par jour.

    Mesurée quand l'API a répondu. Sinon, estimée : heure AWS plus le plus grand écart
    API - AWS observé les jours où les deux ont répondu sur le même calcul. Sans aucun écart
    observé, le jour n'est pas estimé.
    """
    rows = list(rows)
    gaps = [float(r["ecart_api_moins_aws_min"]) for r in rows if r["ecart_api_moins_aws_min"]]
    max_gap = timedelta(minutes=max(gaps)) if gaps else None
    out = []
    for r in rows:
        if r["statut_api"] == "ok":
            out.append(
                Availability(
                    r["date_appel_utc"],
                    r["initialisation_api_utc"],
                    datetime.fromisoformat(r["disponibilite_api_utc"]),
                    estimated=False,
                )
            )
        elif r["statut_aws"] == "ok" and max_gap is not None:
            out.append(
                Availability(
                    r["date_appel_utc"],
                    r["initialisation_aws_utc"],
                    datetime.fromisoformat(r["disponibilite_aws_utc"]) + max_gap,
                    estimated=True,
                )
            )
    return out
