"""Téléchargement et contrôle de qualité des données éCO2mix nationales (RTE, via ODRÉ).

Les mesures servent l'étude de faisabilité : période couverte, trous, doublons, pas réel de
la consommation, changements d'heure, raccords entre données définitives, consolidées et
temps réel, et erreur de la prévision J-1 publiée par RTE.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pandas as pd

EXPORT_URL = (
    "https://odre.opendatasoft.com/api/explore/v2.1/catalog/datasets/{dataset}/exports/parquet"
)
ALLOWED_HOSTS = frozenset({"odre.opendatasoft.com"})
DATASETS = ("eco2mix-national-cons-def", "eco2mix-national-tr")
COLUMNS = ("nature", "date_heure", "consommation", "prevision_j1", "prevision_j")
PARIS = "Europe/Paris"
TIMEOUT_S = 600
USER_AGENT = "day-ahead-load/0.0 (etude de faisabilite)"


@dataclass(frozen=True)
class Download:
    dataset: str
    path: Path
    sha256: str
    size: int


def export_url(dataset: str) -> str:
    if dataset not in DATASETS:
        raise ValueError(f"jeu inconnu : {dataset}")
    url = EXPORT_URL.format(dataset=dataset)
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise ValueError(f"adresse refusée : {url}")
    return url


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def download(dataset: str, directory: Path) -> Download:
    """Télécharge l'export Parquet d'un jeu, sauf s'il est déjà présent dans `directory`.

    L'écriture passe par un fichier temporaire renommé à la fin : un téléchargement coupé ne
    laisse jamais un fichier tronqué qui serait relu comme complet.
    """
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{dataset}.parquet"
    if not target.exists():
        # export_url n'accepte que https vers ODRÉ : pas de schéma file: ou personnalisé.
        request = urllib.request.Request(  # noqa: S310
            export_url(dataset), headers={"User-Agent": USER_AGENT}
        )
        fd, tmp_name = tempfile.mkstemp(dir=directory, suffix=".part")
        try:
            with (
                os.fdopen(fd, "wb") as out,
                urllib.request.urlopen(  # noqa: S310
                    request, timeout=TIMEOUT_S
                ) as response,
            ):
                for block in iter(lambda: response.read(1 << 20), b""):
                    out.write(block)
            with open(tmp_name, "rb") as check:
                magic = check.read(4)
            if magic != b"PAR1":
                raise ValueError(f"{dataset} : la réponse n'est pas un fichier Parquet")
            os.replace(tmp_name, target)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
    return Download(dataset, target, sha256_of(target), target.stat().st_size)


def load(paths: list[Path]) -> pd.DataFrame:
    """Lit les exports et garde les colonnes utiles, triées par horodatage UTC."""
    frames = [pd.read_parquet(p, columns=list(COLUMNS)) for p in paths]
    df = pd.concat(frames, ignore_index=True)
    df["date_heure"] = pd.to_datetime(df["date_heure"], utc=True)
    for column in ("consommation", "prevision_j1", "prevision_j"):
        df[column] = df[column].astype("Float64")
    return df.sort_values("date_heure", kind="stable").reset_index(drop=True)


def periods_by_nature(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Début, fin et nombre de lignes de chaque nature de données, dans l'ordre du temps."""
    grouped = df.groupby("nature", sort=False)["date_heure"].agg(["min", "max", "count"])
    grouped = grouped.sort_values("min")
    return [
        {
            "nature": str(nature),
            "debut_utc": row["min"].isoformat(),
            "fin_utc": row["max"].isoformat(),
            "lignes": int(row["count"]),
        }
        for nature, row in grouped.iterrows()
    ]


def seams(df: pd.DataFrame, step: str = "15min") -> list[dict[str, Any]]:
    """Raccord entre natures successives : écart (en pas) entre la fin de l'une et le début
    de la suivante. 1 = raccord exact, plus de 1 = trou, 0 ou moins = chevauchement."""
    periods = periods_by_nature(df)
    delta = pd.Timedelta(step)
    out = []
    for before, after in zip(periods, periods[1:], strict=False):
        gap = pd.Timestamp(after["debut_utc"]) - pd.Timestamp(before["fin_utc"])
        out.append(
            {
                "de": before["nature"],
                "vers": after["nature"],
                "ecart_en_pas": gap / delta,
            }
        )
    return out


def duplicates(df: pd.DataFrame) -> int:
    """Nombre de lignes dont l'horodatage UTC apparaît déjà."""
    return int(df["date_heure"].duplicated().sum())


def missing_timestamps(df: pd.DataFrame, step: str = "15min") -> dict[str, Any]:
    """Horodatages absents de la grille régulière entre la première et la dernière ligne."""
    stamps = pd.DatetimeIndex(df["date_heure"].drop_duplicates())
    grid = pd.date_range(stamps.min(), stamps.max(), freq=step)
    missing = grid.difference(stamps)
    runs: list[dict[str, Any]] = []
    if len(missing):
        breaks = missing.to_series().diff() != pd.Timedelta(step)
        run_id = breaks.cumsum()
        for _, block in missing.to_series().groupby(run_id.to_numpy()):
            runs.append(
                {
                    "debut_utc": block.iloc[0].isoformat(),
                    "fin_utc": block.iloc[-1].isoformat(),
                    "pas": len(block),
                }
            )
    return {"attendus": len(grid), "absents": len(missing), "plages": runs}


def fill_by_minute(df: pd.DataFrame, column: str) -> dict[str, dict[str, float]]:
    """Part des lignes renseignées pour `column`, par année (heure de Paris) et par minute de
    l'horodatage (00, 15, 30, 45). Révèle un pas réel de 30 min dans un fichier au quart
    d'heure."""
    local = df["date_heure"].dt.tz_convert(PARIS)
    filled = df[column].notna()
    table = filled.groupby([local.dt.year, local.dt.minute]).mean().unstack()
    return {
        str(year): {f"{minute:02}": round(float(share), 4) for minute, share in row.items()}
        for year, row in table.iterrows()
    }


def local_day_sizes(df: pd.DataFrame) -> dict[str, int]:
    """Nombre de jours (heure de Paris) par nombre de lignes. Une journée normale a 96 quarts
    d'heure, celle du passage à l'heure d'été 92, celle du retour à l'heure d'hiver 100."""
    local_dates = df["date_heure"].dt.tz_convert(PARIS).dt.date
    sizes = local_dates.value_counts().value_counts().sort_index()
    return {str(int(size)): int(days) for size, days in sizes.items()}


def irregular_days(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Jours dont le nombre de lignes n'est pas celui attendu compte tenu de l'heure légale."""
    local = df["date_heure"].dt.tz_convert(PARIS)
    counts = local.dt.date.value_counts().sort_index()
    out = []
    for day, count in counts.items():
        start = pd.Timestamp(day).tz_localize(PARIS)
        end = (pd.Timestamp(day) + pd.Timedelta(days=1)).tz_localize(PARIS)
        expected = int((end - start) / pd.Timedelta("15min"))
        if count != expected:
            out.append({"jour": str(day), "lignes": int(count), "attendues": expected})
    return out


def j1_error_by_year(df: pd.DataFrame) -> dict[str, dict[str, float | int]]:
    """Erreur de la prévision J-1 de RTE sur les points où la consommation est renseignée :
    erreur absolue moyenne (MW), erreur absolue moyenne en pourcentage, biais moyen (MW,
    positif = RTE surestime)."""
    both = df.dropna(subset=["consommation", "prevision_j1"])
    both = both[both["consommation"] > 0]
    error = both["prevision_j1"] - both["consommation"]
    year = both["date_heure"].dt.tz_convert(PARIS).dt.year
    out: dict[str, dict[str, float | int]] = {}
    for y, err in error.groupby(year):
        conso = both.loc[err.index, "consommation"]
        out[str(y)] = {
            "points": len(err),
            "mae_mw": round(float(err.abs().mean()), 1),
            "mape_pct": round(float((err.abs() / conso).mean() * 100), 3),
            "biais_mw": round(float(err.mean()), 1),
        }
    return out


def consumption_range_by_year(df: pd.DataFrame) -> dict[str, dict[str, float]]:
    """Minimum, médiane et maximum de la consommation par année, pour repérer les valeurs
    aberrantes (zéros, unités changées)."""
    conso = df.dropna(subset=["consommation"])
    year = conso["date_heure"].dt.tz_convert(PARIS).dt.year
    stats = conso.groupby(year)["consommation"].agg(["min", "median", "max"])
    return {str(y): {str(k): float(v) for k, v in row.items()} for y, row in stats.iterrows()}
