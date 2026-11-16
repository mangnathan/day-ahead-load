"""Téléchargement de la météo Open-Meteo aux 12 points, sous plafond d'appels.

Trois sources, toujours appelées avec les mêmes coordonnées exactes, la même altitude fixée,
les mêmes variables, `timezone=GMT` et `cell_selection=land` :

- `era5` : réanalyse ERA5 (`models=era5` explicite : par défaut, l'API historique mélange
  IFS, ERA5 et ERA5-Land sans le dire). Sert à l'entraînement, météo observée ;
- `ifs_historique` : série IFS 9 km de l'API historique, sur la seule validation, pour
  mesurer si elle est plus proche de la prévision qu'ERA5. Elle n'est jamais assemblée à ERA5 ;
- `ecmwf_00utc` : calcul ECMWF IFS de 00 UTC de la veille (Single Runs API), l'entrée réelle
  du modèle au moment de la décision.

Règle de décompte d'Open-Meteo : une requête de plus de 10 variables ou de plus de 2 semaines
pour un point compte pour plusieurs appels. Avec 5 variables et des tranches de 14 jours,
chaque requête compte pour 1, ce que l'essai du 14/11/2026 a confirmé (en-tête
`X-RateLimit-Cost: 1.0`). Le service ne donne qu'un compteur par minute : le plafond
journalier est tenu ici, dans un journal local.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse

import numpy as np
import pandas as pd

from day_ahead_load.weather_points import Point

VARIABLES = (
    "temperature_2m",
    "shortwave_radiation",
    "cloud_cover",
    "wind_speed_10m",
    "relative_humidity_2m",
)
MAX_VARIABLES_PER_CALL = 10
CHUNK_DAYS = 14
DAILY_CAP = 8_000
MIN_INTERVAL_S = 1.0
RETRY_WAIT_S = 300.0
RUN_FORECAST_DAYS = 3
TIMEOUT_S = 60
USER_AGENT = "day-ahead-load/0.0 (etude de faisabilite)"
ALLOWED_HOSTS = frozenset(
    {
        "archive-api.open-meteo.com",
        "single-runs-api.open-meteo.com",
        "api.open-meteo.com",
        "geo.api.gouv.fr",
    }
)
ELEVATION_URL = "https://api.open-meteo.com/v1/elevation"
REVERSE_GEOCODING_URL = "https://geo.api.gouv.fr/communes"

if len(VARIABLES) > MAX_VARIABLES_PER_CALL:
    raise RuntimeError("plus de 10 variables : chaque requête compterait pour plusieurs appels")


@dataclass(frozen=True)
class Source:
    name: str
    url: str
    model: str
    start: date
    end: date
    single_runs: bool


SOURCES: dict[str, Source] = {
    "era5": Source(
        "era5",
        "https://archive-api.open-meteo.com/v1/archive",
        "era5",
        date(2012, 1, 1),
        date(2026, 10, 31),
        single_runs=False,
    ),
    "ifs_historique": Source(
        "ifs_historique",
        "https://archive-api.open-meteo.com/v1/archive",
        "ecmwf_ifs",
        date(2024, 3, 15),
        date(2025, 8, 31),
        single_runs=False,
    ),
    "ecmwf_00utc": Source(
        "ecmwf_00utc",
        "https://single-runs-api.open-meteo.com/v1/forecast",
        "ecmwf_ifs",
        date(2024, 3, 14),
        date(2026, 11, 13),
        single_runs=True,
    ),
}


@dataclass(frozen=True)
class Request:
    source: str
    point: Point
    start: date
    end: date
    url: str

    @property
    def cache_path(self) -> Path:
        name = (
            f"run-{self.start}" if SOURCES[self.source].single_runs else f"{self.start}_{self.end}"
        )
        return Path(self.source) / self.point.commune / f"{name}.json"


def checked_url(base: str, params: Mapping[str, str]) -> str:
    url = f"{base}?{urlencode(params, safe=',:')}"
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise ValueError(f"adresse refusée : {url}")
    return url


def chunks(start: date, end: date, days: int = CHUNK_DAYS) -> list[tuple[date, date]]:
    out = []
    current = start
    while current <= end:
        last = min(current + timedelta(days=days - 1), end)
        out.append((current, last))
        current = last + timedelta(days=1)
    return out


def requests_for(source_name: str, point: Point, elevation: float) -> list[Request]:
    source = SOURCES[source_name]
    common = {
        "latitude": f"{point.latitude}",
        "longitude": f"{point.longitude}",
        "elevation": f"{elevation}",
        "hourly": ",".join(VARIABLES),
        "models": source.model,
        "timezone": "GMT",
        "cell_selection": "land",
    }
    out = []
    if source.single_runs:
        day = source.start
        while day <= source.end:
            params = {**common, "run": f"{day}T00:00", "forecast_days": f"{RUN_FORECAST_DAYS}"}
            out.append(Request(source_name, point, day, day, checked_url(source.url, params)))
            day += timedelta(days=1)
    else:
        for first, last in chunks(source.start, source.end):
            params = {**common, "start_date": f"{first}", "end_date": f"{last}"}
            out.append(Request(source_name, point, first, last, checked_url(source.url, params)))
    return out


def estimate(points: tuple[Point, ...]) -> dict[str, int]:
    """Nombre d'appels prévus par source, sans aucun appel réseau."""
    dummy = 0.0
    return {name: len(requests_for(name, points[0], dummy)) * len(points) for name in SOURCES}


class QuotaRefusedError(RuntimeError):
    """Le service a refusé un appel pour quota : arrêt définitif."""


class DailyCapReachedError(RuntimeError):
    """Le plafond local du jour est atteint : reprise le lendemain, depuis le cache."""


class TransientFailureError(RuntimeError):
    """Coupure réseau ou réponse 5xx : une seule nouvelle tentative, après une pause."""


class NetworkInterruptedError(RuntimeError):
    """Deux échecs passagers de suite : fin de la séance, reprise plus tard depuis le cache.

    Une coupure peut être une limitation de débit qui ne dit pas son nom : après la pause et
    la nouvelle tentative, on n'insiste pas. Chaque tentative est comptée dans le journal.
    """


class Budget:
    """Journal local des appels par jour UTC, plafond journalier et arrêt définitif au 429.

    Le fichier d'arrêt n'est jamais supprimé par le code : reprendre après un refus de quota
    demande une décision humaine.
    """

    def __init__(
        self,
        ledger: Path,
        stop_file: Path,
        cap: int = DAILY_CAP,
        today: Callable[[], date] = lambda: datetime.now(UTC).date(),
    ) -> None:
        self.ledger = ledger
        self.stop_file = stop_file
        self.cap = cap
        self.today = today

    def _read(self) -> dict[str, float]:
        if not self.ledger.exists():
            return {}
        data: dict[str, float] = json.loads(self.ledger.read_text(encoding="utf-8"))
        return data

    def used_today(self) -> float:
        return self._read().get(str(self.today()), 0.0)

    def check(self, cost: float = 1.0) -> None:
        if self.stop_file.exists():
            raise QuotaRefusedError(f"arrêt définitif après un refus de quota : {self.stop_file}")
        if self.used_today() + cost > self.cap:
            raise DailyCapReachedError(f"plafond local de {self.cap} appels atteint aujourd'hui")

    def record(self, cost: float) -> None:
        data = self._read()
        key = str(self.today())
        data[key] = data.get(key, 0.0) + cost
        write_atomic(self.ledger, json.dumps(data, indent=2, sort_keys=True))

    def stop(self, details: Mapping[str, Any]) -> None:
        write_atomic(self.stop_file, json.dumps(dict(details), indent=2, ensure_ascii=False))


@dataclass(frozen=True)
class Response:
    status: int
    headers: Mapping[str, str]
    body: bytes


Fetcher = Callable[[str], Response]


def urllib_fetch(url: str) -> Response:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise ValueError(f"adresse refusée : {url}")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310
    try:
        # Schéma et hôte vérifiés ci-dessus : https vers Open-Meteo ou geo.api.gouv.fr.
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:  # noqa: S310
            return Response(response.status, dict(response.headers.items()), response.read())
    except urllib.error.HTTPError as error:
        return Response(error.code, dict(error.headers.items()), error.read())


def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".part")
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as out:
        out.write(text)
    os.replace(tmp, path)


QUOTA_HEADERS = ("x-ratelimit-cost", "x-ratelimit-limit", "x-ratelimit-remaining")


class Downloader:
    """Appelle Open-Meteo au plus une fois par seconde, sous budget, avec cache sur disque."""

    def __init__(
        self,
        root: Path,
        budget: Budget,
        fetch: Fetcher = urllib_fetch,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.root = root
        self.budget = budget
        self.fetch = fetch
        self.sleep = sleep
        self.clock = clock
        self._last_call: float | None = None
        self.calls = 0

    def _attempt(self, url: str) -> Response:
        """Une tentative comptée. Lève TransientFailureError sur coupure réseau ou réponse 5xx."""
        self.budget.check()
        if self._last_call is not None:
            wait = MIN_INTERVAL_S - (self.clock() - self._last_call)
            if wait > 0:
                self.sleep(wait)
        self._last_call = self.clock()
        try:
            response = self.fetch(url)
        except OSError as error:  # URLError, coupure de connexion, délai dépassé
            self.budget.record(1.0)
            self.calls += 1
            raise TransientFailureError(f"connexion interrompue : {error}") from error
        headers = {k.lower(): v for k, v in response.headers.items()}
        self.budget.record(float(headers.get("x-ratelimit-cost", "1")))
        self.calls += 1
        if 500 <= response.status < 600:
            raise TransientFailureError(f"réponse {response.status} du serveur")
        return response

    def call(self, url: str) -> tuple[dict[str, Any], dict[str, str]]:
        """Un appel compté, avec au plus une nouvelle tentative après une pause.

        La nouvelle tentative n'a lieu qu'après une coupure réseau ou une réponse 5xx ; elle
        compte dans le plafond. Un deuxième échec arrête la séance. Un 429 arrête tout,
        définitivement, à la première ou à la deuxième tentative.
        """
        try:
            response = self._attempt(url)
        except TransientFailureError as first:
            self.sleep(RETRY_WAIT_S)
            try:
                response = self._attempt(url)
            except TransientFailureError as second:
                raise NetworkInterruptedError(
                    f"deux échecs de suite ({first} ; {second})"
                ) from second
        headers = {k.lower(): v for k, v in response.headers.items()}
        if response.status == 429:
            self.budget.stop(
                {
                    "date": datetime.now(UTC).isoformat(timespec="seconds"),
                    "url": url,
                    "reponse": response.body.decode("utf-8", errors="replace")[:500],
                }
            )
            raise QuotaRefusedError("refus de quota (429) : arrêt définitif")
        if response.status != 200:
            raise RuntimeError(f"réponse {response.status} pour {url} : {response.body[:300]!r}")
        payload: dict[str, Any] = json.loads(response.body)
        if payload.get("error"):
            raise RuntimeError(f"erreur Open-Meteo pour {url} : {payload.get('reason')}")
        quota = {k: headers[k] for k in QUOTA_HEADERS if k in headers}
        return payload, quota

    def get(self, request: Request) -> dict[str, Any]:
        """Renvoie la réponse en cache, ou l'appelle et la met en cache."""
        path = self.root / request.cache_path
        if path.exists():
            cached: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
            return cached
        payload, quota = self.call(request.url)
        record = {
            "url": request.url,
            "telecharge_le": datetime.now(UTC).isoformat(timespec="seconds"),
            "en_tetes_quota": quota,
            "reponse": payload,
        }
        write_atomic(path, json.dumps(record, ensure_ascii=False))
        return record


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, l1, p2, l2 = map(math.radians, (lat1, lon1, lat2, lon2))
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin((l2 - l1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def land_check(
    point: Point,
    source: str,
    payload: Mapping[str, Any],
    commune_at: Callable[[float, float], str | None],
) -> dict[str, Any]:
    """Contrôle que le centre de la maille renvoyée est sur une commune française.

    Limite : le centre de maille ne dit pas quelle part de mer contient la maille. Une maille
    dont le centre n'est sur aucune commune française (mer ou pays voisin) est à examiner à la
    main ; le déplacement éventuel du point est alors documenté.
    """
    lat = float(payload["latitude"])
    lon = float(payload["longitude"])
    commune = commune_at(lat, lon)
    return {
        "source": source,
        "latitude_maille": lat,
        "longitude_maille": lon,
        "altitude_utilisee_m": float(payload["elevation"]),
        "distance_km": round(distance_km(point.latitude, point.longitude, lat, lon), 1),
        "commune_au_centre_de_maille": commune,
        "centre_sur_commune_francaise": commune is not None,
    }


def top_of_atmosphere(index: pd.DatetimeIndex, latitude: float, longitude: float) -> np.ndarray:
    """Rayonnement solaire hors atmosphère sur un plan horizontal, instantané, en W/m².

    Formules usuelles (déclinaison de Cooper, équation du temps de Spencer simplifiée) :
    assez précises pour situer la courbe à quelques minutes près.
    """
    n = index.day_of_year.to_numpy()
    hours = index.hour.to_numpy() + index.minute.to_numpy() / 60
    b = 2 * np.pi * (n - 81) / 364
    equation_of_time_min = 9.87 * np.sin(2 * b) - 7.53 * np.cos(b) - 1.5 * np.sin(b)
    declination = np.radians(23.45) * np.sin(2 * np.pi * (284 + n) / 365)
    hour_angle = np.radians(15 * (hours + longitude / 15 + equation_of_time_min / 60 - 12))
    lat = math.radians(latitude)
    cos_zenith = math.sin(lat) * np.sin(declination) + math.cos(lat) * np.cos(declination) * np.cos(
        hour_angle
    )
    result: np.ndarray = np.clip(1361.0 * cos_zenith, 0.0, None)
    return result


def radiation_convention(
    radiation: pd.Series, latitude: float, longitude: float
) -> dict[str, float]:
    """Corrélation du rayonnement horaire (index UTC) avec la courbe théorique sous trois
    conventions : valeur à l'instant affiché, moyenne de l'heure précédente, de l'heure suivante.

    La convention documentée par Open-Meteo est la moyenne de l'heure précédente. Si deux
    sources ne gagnent pas avec la même convention, un décalage d'une heure les sépare.
    """
    series = radiation.dropna()
    index = pd.DatetimeIndex(series.index)
    minutes = pd.date_range(
        index.min() - pd.Timedelta(hours=1), index.max() + pd.Timedelta(hours=1), freq="1min"
    )
    theory = pd.Series(top_of_atmosphere(minutes, latitude, longitude), index=minutes)
    previous = theory.rolling(60).mean()
    following = theory[::-1].rolling(60).mean()[::-1]
    candidates = {
        "instant": pd.Series(top_of_atmosphere(index, latitude, longitude), index=index),
        "moyenne_heure_precedente": previous.reindex(index),
        "moyenne_heure_suivante": following.reindex(index),
    }
    return {name: round(float(series.corr(values)), 4) for name, values in candidates.items()}


def hourly_frame(payload: Mapping[str, Any]) -> pd.DataFrame:
    """Réponse Open-Meteo en tableau horaire indexé en UTC (les appels demandent GMT)."""
    if payload.get("timezone") != "GMT" or payload.get("utc_offset_seconds") != 0:
        raise ValueError("réponse hors GMT : la conversion vers Paris se fait dans notre code")
    hourly = dict(payload["hourly"])
    raw_times: list[str] = list(hourly.pop("time"))
    times = pd.DatetimeIndex(raw_times).tz_localize("UTC")
    return pd.DataFrame(hourly, index=times)
