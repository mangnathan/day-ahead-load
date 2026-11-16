"""Mesure quotidienne de l'heure de disponibilité du calcul ECMWF IFS 9 km de 00 UTC.

La règle de midi utilise le calcul de 00 UTC de la veille. Deux lectures par jour :

- l'API (`api.open-meteo.com`, fichier `data/ecmwf_ifs/static/meta.json`) : heure à laquelle le
  dernier calcul reçu est disponible sur le serveur atteint. Ce fichier ne décrit que le dernier
  calcul : la lecture doit tomber après la disponibilité du calcul de 00 UTC et avant celle du
  calcul de 06 UTC, d'où un lancement vers 9 h UTC. Le serveur atteint dépend de l'endroit d'où
  l'on appelle (le 16/11/2026, 157.90.83.168 depuis la France, 167.114.211.86 depuis la machine
  de GitHub ; pays déduits de la plage d'adresses, non vérifiés) : son adresse est notée ;
- la copie publique d'Open-Meteo sur AWS, fichier propre au calcul de 00 UTC du jour
  (`data_run/ecmwf_ifs/AAAA/MM/JJ/0000Z/meta.json`) : son champ `created_at` est l'heure de dépôt
  de ce calcul, quel que soit le moment de la lecture.

Chaque ligne indique à quel calcul (00, 06, 12 ou 18 UTC) se rapporte la lecture de l'API.

Garde-fous :
- une ligne par jour au plus : la ligne du jour présente, rien n'est appelé ;
- pour chaque source, une coupure réseau ou une réponse 5xx donne lieu à une seule nouvelle
  tentative après une pause ; un deuxième échec est noté dans la ligne ;
- au premier refus de quota (429), jamais retenté, un fichier d'arrêt est écrit et plus aucun
  appel n'est fait tant qu'une personne ne l'a pas retiré.

Bibliothèque standard seulement.
"""

from __future__ import annotations

import csv
import json
import socket
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

API_URL = "https://api.open-meteo.com/data/ecmwf_ifs/static/meta.json"
AWS_RUN_URL = "https://openmeteo.s3.amazonaws.com/data_run/ecmwf_ifs/{day:%Y/%m/%d}/0000Z/meta.json"
API_HOST = "api.open-meteo.com"
ALLOWED_HOSTS = frozenset({API_HOST, "openmeteo.s3.amazonaws.com"})
# Les fichiers des versions précédentes sont gardés tels quels comme historique.
CSV_NAME = "disponibilite-ecmwf-00utc.csv"
STOP_NAME = "ARRET-QUOTA.json"
MAX_ROWS_PER_DAY = 1
RETRY_WAIT_S = 120.0
TIMEOUT_S = 30
# Règle prudente pour la disponibilité sur l'API quand elle n'est pas mesurée : dépôt sur AWS
# + 2 h. Les écarts mesurés (40 et 54 min sur le serveur européen) servent à la justifier ou à
# la réduire plus tard.
SAFETY_MARGIN = timedelta(hours=2)
COLUMNS = (
    "date_appel_utc",
    "heure_appel_utc",
    "statut_api",
    "serveur_api",
    "calcul_api",
    "initialisation_api_utc",
    "disponibilite_api_utc",
    "statut_aws",
    "depot_aws_00utc",
    "ecart_api_moins_aws_min",
    "detail",
)
USER_AGENT = "day-ahead-load/0.0 (mesure de disponibilite)"

Fetch = Callable[[str], tuple[int, bytes]]
Resolve = Callable[[str], str]


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


def resolve_ipv4(host: str) -> str:
    """Première adresse IPv4 du serveur, celle qu'utilise la connexion (pas d'IPv6 ici)."""
    try:
        return str(socket.getaddrinfo(host, 443, socket.AF_INET)[0][4][0])
    except OSError:
        return ""


def _utc(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds")


def _attempt(fetch: Fetch, url: str) -> tuple[int, bytes]:
    try:
        status, body = fetch(url)
    except OSError as error:  # URLError, délai dépassé, connexion coupée
        raise TransientFailureError(f"connexion interrompue : {error}") from error
    if 500 <= status < 600:
        raise TransientFailureError(f"réponse {status} du serveur")
    return status, body


@dataclass(frozen=True)
class Fetched:
    status: str  # "ok", "absent" (404) ou "echec"
    body: bytes = b""
    detail: str = ""


def fetch_once_retry(url: str, fetch: Fetch, sleep: Callable[[float], None]) -> Fetched:
    """Au plus une nouvelle tentative. Lève QuotaRefusedError sur un 429."""
    try:
        status, body = _attempt(fetch, url)
    except TransientFailureError:
        sleep(RETRY_WAIT_S)
        try:
            status, body = _attempt(fetch, url)
        except TransientFailureError as second:
            return Fetched("echec", detail=str(second)[:200])
    if status == 429:
        raise QuotaRefusedError(body[:500].decode(errors="replace"))
    if status == 404:
        return Fetched("absent", detail="réponse 404")
    if status != 200:
        return Fetched("echec", detail=f"réponse {status}")
    return Fetched("ok", body)


def build_row(
    called_at: datetime, api: Fetched, server: str, aws: Fetched, day: date
) -> dict[str, str]:
    row = dict.fromkeys(COLUMNS, "")
    row["date_appel_utc"] = called_at.date().isoformat()
    row["heure_appel_utc"] = _utc(called_at)
    row["statut_api"] = api.status
    row["serveur_api"] = server
    row["statut_aws"] = aws.status
    details = [f"{name} : {f.detail}" for name, f in (("api", api), ("aws", aws)) if f.detail]
    api_init: datetime | None = None
    api_available: datetime | None = None
    if api.status == "ok":
        meta = json.loads(api.body)
        api_init = datetime.fromtimestamp(int(meta["last_run_initialisation_time"]), UTC)
        api_available = datetime.fromtimestamp(int(meta["last_run_availability_time"]), UTC)
        row["calcul_api"] = f"{api_init:%H}"
        row["initialisation_api_utc"] = _utc(api_init)
        row["disponibilite_api_utc"] = _utc(api_available)
    deposit: datetime | None = None
    if aws.status == "ok":
        meta = json.loads(aws.body)
        if not str(meta["reference_time"]).startswith(f"{day}T00:00"):
            raise ValueError(f"calcul AWS inattendu : {meta['reference_time']}")
        deposit = datetime.fromisoformat(str(meta["created_at"]).replace("Z", "+00:00"))
        row["depot_aws_00utc"] = _utc(deposit)
    same_run = api_init is not None and api_init == datetime(*day.timetuple()[:3], tzinfo=UTC)
    if same_run and api_available is not None and deposit is not None:
        row["ecart_api_moins_aws_min"] = f"{(api_available - deposit).total_seconds() / 60:.1f}"
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
    resolve: Resolve = resolve_ipv4,
) -> str:
    """Lit l'API puis le dépôt AWS du calcul de 00 UTC du jour, et ajoute une ligne."""
    called_at = now or datetime.now(UTC)
    day = called_at.astimezone(UTC).date()
    stop = directory / STOP_NAME
    if stop.exists():
        return "arrêt : refus de quota antérieur, aucun appel"
    table = directory / CSV_NAME
    if rows_on(table, day.isoformat()) >= MAX_ROWS_PER_DAY:
        return "déjà mesuré aujourd'hui, aucun appel"
    try:
        server = resolve(API_HOST)
        api = fetch_once_retry(API_URL, fetch, sleep)
        aws = fetch_once_retry(AWS_RUN_URL.format(day=day), fetch, sleep)
    except QuotaRefusedError as refusal:
        stop.write_text(
            json.dumps(
                {"date": _utc(called_at), "reponse": str(refusal)},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return "refus de quota (429) : fichier d'arrêt écrit"
    row = build_row(called_at, api, server, aws, day)
    _append(table, row)
    gap = row["ecart_api_moins_aws_min"] or "-"
    return (
        f"api : {row['statut_api']} (calcul {row['calcul_api'] or '-'}, serveur "
        f"{row['serveur_api'] or '-'}), aws : {row['statut_aws']}, écart {gap} min"
    )


@dataclass(frozen=True)
class Availability:
    day: str
    available_utc: datetime
    estimated: bool


def api_availability(rows: Iterable[Mapping[str, str]]) -> list[Availability]:
    """Heure de disponibilité du calcul de 00 UTC sur l'API, jour par jour.

    Mesurée quand l'API a répondu sur le calcul de 00 UTC. Sinon, estimée par la règle
    prudente : dépôt sur AWS + 2 h.
    """
    out = []
    for r in rows:
        if r["statut_api"] == "ok" and r["calcul_api"] == "00":
            out.append(
                Availability(
                    r["date_appel_utc"], datetime.fromisoformat(r["disponibilite_api_utc"]), False
                )
            )
        elif r["statut_aws"] == "ok":
            out.append(
                Availability(
                    r["date_appel_utc"],
                    datetime.fromisoformat(r["depot_aws_00utc"]) + SAFETY_MARGIN,
                    True,
                )
            )
    return out
