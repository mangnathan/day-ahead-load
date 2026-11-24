"""Prix des écarts d'ENTSO-E (Imbalance Prices [17.1.G], France), sous plafond d'appels.

Règle écrite avant le premier appel (journal des choix, entrée 24) :

- API `https://web-api.tp.entsoe.eu/api`, type de document A85, zone France
  (code EIC 10YFR-RTE------C), dates en UTC au format yyyyMMddHHmm, au plus un an par requête ;
- une requête par mois civil UTC, de mars 2024 à août 2026, plus un appel de contrôle sur une
  journée, qui vérifie le nom du paramètre de zone et le format de la réponse avant tout
  téléchargement : 31 appels ;
- plafond local de 100 appels par jour, au plus un appel toutes les 2 secondes, arrêt définitif
  au premier refus de quota (429), une seule nouvelle tentative après une coupure ou une 5xx.

Le jeton est lu dans `.env` et n'est jamais affiché, journalisé ni écrit : le cache garde les
paramètres de la requête sans le jeton, et tout message d'erreur en est expurgé.

Données réutilisées sous licence CC BY 4.0. Source : ENTSO-E Transparency Platform.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from io import BytesIO
from pathlib import Path

import pandas as pd

from day_ahead_load import weather as w

API_URL = "https://web-api.tp.entsoe.eu/api"
ALLOWED_HOSTS = frozenset({"web-api.tp.entsoe.eu"})
TOKEN_KEY = "ENTSOE_TOKEN"  # noqa: S105 (nom de la clé dans .env, pas un secret)
DOCUMENT_TYPE = "A85"  # Imbalance prices
FRANCE = "10YFR-RTE------C"
# Nom non vérifié dans la documentation lisible (Postman) : confirmé par l'appel de contrôle.
DOMAIN_PARAMETER = "controlArea_Domain"
FIRST_MONTH = "2024-03"
LAST_MONTH = "2026-08"
CONTROL_DAY = date(2025, 1, 15)
DAILY_CAP = 100
MIN_INTERVAL_S = 2.0
RETRY_WAIT_S = 120.0
TIMEOUT_S = 300  # délai de réponse annoncé par ENTSO-E
USER_AGENT = "day-ahead-load/0.3"
SOURCE = "ENTSO-E Transparency Platform"


class TokenMissingError(RuntimeError):
    """La clé ENTSOE_TOKEN est absente ou vide dans .env."""


def load_token(env_path: Path) -> str:
    """Lit le jeton dans .env sans jamais l'afficher. Le message d'erreur ne cite aucune ligne."""
    if not env_path.exists():
        raise TokenMissingError(f"fichier absent : {env_path}")
    for line in env_path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() == TOKEN_KEY:
            token = value.strip().strip('"').strip("'")
            if token:
                return token
    raise TokenMissingError(f"clé {TOKEN_KEY} absente ou vide dans {env_path}")


def redact(text: str, token: str) -> str:
    return text.replace(token, "***") if token else text


def _stamp(moment: datetime) -> str:
    return moment.strftime("%Y%m%d%H%M")


@dataclass(frozen=True)
class Request:
    """Une requête de prix des écarts, sans le jeton."""

    name: str
    start: datetime  # UTC
    end: datetime  # UTC, exclu

    def params(self) -> dict[str, str]:
        return {
            "documentType": DOCUMENT_TYPE,
            DOMAIN_PARAMETER: FRANCE,
            "periodStart": _stamp(self.start),
            "periodEnd": _stamp(self.end),
        }

    @property
    def cache_name(self) -> str:
        return f"{self.name}_{_stamp(self.start)}_{_stamp(self.end)}"


def monthly_requests(first: str = FIRST_MONTH, last: str = LAST_MONTH) -> list[Request]:
    """Un mois civil UTC par requête : loin de la limite d'un an et de 200 documents."""
    out = []
    for period in pd.period_range(first, last, freq="M"):
        start = period.start_time.to_pydatetime().replace(tzinfo=UTC)
        end = (period + 1).start_time.to_pydatetime().replace(tzinfo=UTC)
        out.append(Request(f"prix-ecarts-{period}", start, end))
    return out


def control_request(day: date = CONTROL_DAY) -> Request:
    start = datetime(day.year, day.month, day.day, tzinfo=UTC)
    return Request("controle", start, start + timedelta(days=1))


def estimate() -> dict[str, int]:
    """Nombre d'appels prévus, sans aucun appel réseau."""
    return {"controle": 1, "prix_des_ecarts_mensuels": len(monthly_requests())}


Fetcher = Callable[[str], w.Response]


def urllib_fetch(url: str) -> w.Response:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise ValueError("adresse refusée : hôte hors d'ENTSO-E")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310
    try:
        # Schéma et hôte vérifiés ci-dessus : https vers l'API d'ENTSO-E seulement.
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:  # noqa: S310
            return w.Response(response.status, dict(response.headers.items()), response.read())
    except urllib.error.HTTPError as error:
        return w.Response(error.code, dict(error.headers.items()), error.read())


class Client:
    """Appelle l'API sous budget, met chaque réponse en cache et ne divulgue jamais le jeton."""

    def __init__(
        self,
        token: str,
        root: Path,
        budget: w.Budget,
        fetch: Fetcher = urllib_fetch,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not token:
            raise TokenMissingError("jeton vide")
        self._token = token
        self.root = root
        self.budget = budget
        self.fetch = fetch
        self.sleep = sleep
        self.clock = clock
        self._last_call: float | None = None
        self.calls = 0

    def __repr__(self) -> str:
        return f"Client(root={self.root!s}, calls={self.calls})"

    def _url(self, request: Request) -> str:
        query = {"securityToken": self._token, **request.params()}
        return f"{API_URL}?{urllib.parse.urlencode(query)}"

    def _attempt(self, request: Request) -> w.Response:
        self.budget.check()
        if self._last_call is not None:
            wait = MIN_INTERVAL_S - (self.clock() - self._last_call)
            if wait > 0:
                self.sleep(wait)
        self._last_call = self.clock()
        try:
            response = self.fetch(self._url(request))
        except OSError as error:
            self.budget.record(1.0)
            self.calls += 1
            # Pas d'enchaînement : l'erreur d'origine peut citer l'adresse, donc le jeton.
            message = redact(f"connexion interrompue : {error}", self._token)
            raise w.TransientFailureError(message) from None
        self.budget.record(1.0)
        self.calls += 1
        if 500 <= response.status < 600:
            raise w.TransientFailureError(f"réponse {response.status} du serveur")
        return response

    def call(self, request: Request) -> w.Response:
        """Un appel compté, avec au plus une nouvelle tentative ; arrêt définitif au 429."""
        try:
            response = self._attempt(request)
        except w.TransientFailureError as first:
            self.sleep(RETRY_WAIT_S)
            try:
                response = self._attempt(request)
            except w.TransientFailureError as second:
                raise w.NetworkInterruptedError(
                    f"deux échecs de suite ({first} ; {second})"
                ) from None
        if response.status == 429:
            self.budget.stop(
                {
                    "date": datetime.now(UTC).isoformat(timespec="seconds"),
                    "requete": request.params(),
                    "reponse": redact(response.body.decode("utf-8", "replace")[:500], self._token),
                }
            )
            raise w.QuotaRefusedError("refus de quota (429) : arrêt définitif")
        return response

    def get(self, request: Request) -> tuple[Path, Mapping[str, object]]:
        """Renvoie le corps en cache, ou l'appelle et le met en cache avec ses métadonnées.

        Une réponse autre que 200 est gardée telle quelle (corps expurgé) pour l'appel de
        contrôle, mais lève une erreur : elle n'entre jamais dans les données.
        """
        body_path = self.root / f"{request.cache_name}.bin"
        meta_path = self.root / f"{request.cache_name}.json"
        if body_path.exists() and meta_path.exists():
            meta: dict[str, object] = json.loads(meta_path.read_text(encoding="utf-8"))
            return body_path, meta
        response = self.call(request)
        headers = {k.lower(): v for k, v in response.headers.items()}
        meta = {
            "source": SOURCE,
            "requete": request.params(),
            "telecharge_le": datetime.now(UTC).isoformat(timespec="seconds"),
            "statut": response.status,
            "type_de_contenu": headers.get("content-type", ""),
            "octets": len(response.body),
        }
        if response.status != 200:
            text = redact(response.body.decode("utf-8", "replace")[:2000], self._token)
            w.write_atomic(self.root / f"{request.cache_name}.erreur.txt", text)
            raise RuntimeError(f"réponse {response.status} pour {request.name}")
        self.root.mkdir(parents=True, exist_ok=True)
        body_path.write_bytes(response.body.replace(self._token.encode(), b"***"))
        w.write_atomic(meta_path, json.dumps(meta, indent=2, ensure_ascii=False))
        return body_path, meta


def structure(body: bytes) -> dict[str, object]:
    """Structure de la réponse, sans les valeurs : archive ou XML, balises présentes."""
    if body[:2] == b"PK":
        with zipfile.ZipFile(BytesIO(body)) as archive:
            names = archive.namelist()
            inner = archive.read(names[0]) if names else b""
        return {"format": "zip", "fichiers": names, "contenu": structure(inner)}
    text = body.decode("utf-8", "replace")
    tags = sorted(set(re.findall(r"<([A-Za-z_][\w.:-]*)", text)))
    return {"format": "xml" if text.lstrip().startswith("<") else "autre", "balises": tags}
