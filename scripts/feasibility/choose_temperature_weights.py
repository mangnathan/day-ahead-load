"""Étude de faisabilité : choix des poids de l'indice national de température.

Compare trois pondérations des températures régionales observées (population, consommation,
consommation d'hiver moins consommation d'été) par validation croisée temporelle, sur la
seule période d'entraînement (2016 au 14 mars 2024) : la validation et le test futurs n'y
entrent pas. Les poids fondés sur la consommation sont recalculés à chaque pli à partir des
années d'entraînement de ce pli.

    uv run python scripts/feasibility/choose_temperature_weights.py --date 2026-11-14
"""

from __future__ import annotations

import argparse
import json
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd

from day_ahead_load import diagnostics, eco2mix
from day_ahead_load import references as refs
from day_ahead_load import temperature_index as ti

ODRE = "https://odre.opendatasoft.com/api/explore/v2.1/catalog/datasets"
SOURCES = {
    "temperature-regionale.csv": (
        f"{ODRE}/temperature-quotidienne-regionale/exports/csv?select=code_insee_region,date,tmoy"
    ),
    "consommation-regionale-jour.csv": (
        f"{ODRE}/eco2mix-regional-cons-def/exports/csv"
        "?select=code_insee_region,date,avg(consommation)%20as%20conso_mw"
        "&group_by=code_insee_region,date"
        "&where=date_heure%3E%3D%222016-01-01T00:00:00%2B01:00%22"
    ),
    "population-communes.json": (
        "https://geo.api.gouv.fr/communes?fields=code,codeRegion,population&format=json"
    ),
}
RAW_ROOT = Path("data/raw/temperature")
ECO2MIX_ROOT = Path("data/raw/eco2mix")
SUMMARY = Path("docs/v0.0-faisabilite/data/indice-temperature-poids.json")
FIRST_YEAR = 2016
TRAIN_END = pd.Timestamp("2024-03-14")
TEST_YEARS = [2018, 2019, 2020, 2021, 2022, 2023]
USER_AGENT = "day-ahead-load/0.0 (etude de faisabilite)"


def fetch(name: str, url: str, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / name
    if not target.exists():
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=600) as response:
            target.write_bytes(response.read())
    return target


def read_inputs(directory: Path) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, float]]:
    temps = pd.read_csv(directory / "temperature-regionale.csv", sep=";", encoding="utf-8-sig")
    temps = temps.rename(columns={"code_insee_region": "region"})
    temps["region"] = temps["region"].astype(str)
    temps["date"] = pd.to_datetime(temps["date"].str[:10])

    regional = pd.read_csv(
        directory / "consommation-regionale-jour.csv", sep=";", encoding="utf-8-sig"
    )
    regional = regional.rename(columns={"code_insee_region": "region"})
    regional["region"] = regional["region"].astype(str)
    regional["date"] = pd.to_datetime(regional["date"])

    communes = json.loads((directory / "population-communes.json").read_text(encoding="utf-8"))
    population: dict[str, float] = {}
    for commune in communes:
        code = str(commune.get("codeRegion"))
        population[code] = population.get(code, 0.0) + float(commune.get("population") or 0)
    return temps, regional, population


def national_daily(date: str) -> pd.Series:
    paths = [ECO2MIX_ROOT / date / f"{name}.parquet" for name in eco2mix.DATASETS]
    df, _ = diagnostics.with_local_instants(diagnostics.read_raw(paths))
    conso = refs.target_series(df)
    daily = conso.groupby(pd.DatetimeIndex(conso.index).normalize()).mean()
    days = pd.DatetimeIndex(daily.index)
    kept: pd.Series = daily[(days.year >= FIRST_YEAR) & (days <= TRAIN_END)]
    return kept


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, help="date du téléchargement (AAAA-MM-JJ)")
    args = parser.parse_args()

    directory = RAW_ROOT / args.date
    files = {name: fetch(name, url, directory) for name, url in SOURCES.items()}
    temps, regional, population = read_inputs(directory)
    temps = temps[temps["date"] <= TRAIN_END]
    regional = regional[regional["date"] <= TRAIN_END]
    consumption = national_daily(args.date)

    def before(year: int) -> pd.DataFrame:
        kept: pd.DataFrame = regional[regional["date"].dt.year < year]
        return kept

    def by_population(year: int) -> dict[str, float]:
        return ti.population_weights(population)

    def by_consumption(year: int) -> dict[str, float]:
        return ti.consumption_weights(before(year))

    def by_winter_minus_summer(year: int) -> dict[str, float]:
        return ti.thermosensitive_weights(before(year))

    builders: dict[str, Callable[[int], dict[str, float]]] = {
        "population": by_population,
        "consommation": by_consumption,
        "hiver_moins_ete": by_winter_minus_summer,
    }

    def index_builder(weights_for: Callable[[int], dict[str, float]]) -> Callable[[int], pd.Series]:
        def build(year: int) -> pd.Series:
            return ti.national_index(temps, weights_for(year))

        return build

    results: dict[str, Any] = {}
    for name, weights_for in builders.items():
        cv = ti.cross_validate(index_builder(weights_for), consumption, FIRST_YEAR, TEST_YEARS)
        last = weights_for(TEST_YEARS[-1] + 1)
        results[name] = {
            **cv,
            "poids_sur_2016_2023": {r: round(v, 4) for r, v in last.items()},
        }

    best = min(results, key=lambda k: results[k]["mae_moyenne_mw"])
    summary = {
        "sources": {
            "temperature": "ODRÉ, température quotidienne régionale (Licence Ouverte 2.0)",
            "consommation_regionale": "RTE, éCO2mix régional, via ODRÉ (Licence Ouverte 2.0)",
            "consommation_nationale": "RTE, éCO2mix national, via ODRÉ (Licence Ouverte 2.0)",
            "population": (
                "INSEE, population des communes servie par geo.api.gouv.fr ; millésime non "
                "indiqué par l'API"
            ),
        },
        "fichiers": [
            {"fichier": name, "sha256": eco2mix.sha256_of(path)} for name, path in files.items()
        ],
        "periode": {"premiere_annee": FIRST_YEAR, "fin": str(TRAIN_END.date())},
        "modele": (
            "consommation journalière = niveau annuel + jour de la semaine + degrés-jours sous "
            f"{ti.HEATING_BASE_C:g} °C + degrés-jours au-dessus de {ti.COOLING_BASE_C:g} °C ; "
            "le niveau de l'année testée est celui de la dernière année d'entraînement"
        ),
        "annees_de_test": TEST_YEARS,
        "limite_hiver_moins_ete": (
            "la consommation d'été contient la climatisation : la part de Provence-Alpes-Côte "
            "d'Azur et de l'Occitanie est sous-estimée"
        ),
        "resultats": results,
        "meilleure_ponderation": best,
        "repere_rte": (
            "environ 2 400 MW par degré sous 15 °C en hiver (RTE, Futurs énergétiques 2050, "
            "février 2022, chapitre 8). La phrase n'est pas datée ; la figure voisine porte la "
            "mention « thermosensibilité en 2020 ». Ordre de grandeur, autre période et autre "
            "indice, pas une cible"
        ),
    }
    SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    with SUMMARY.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"résumé écrit : {SUMMARY}")


if __name__ == "__main__":
    main()
