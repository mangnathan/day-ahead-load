"""Étude de faisabilité : recalcule les 12 points météo à partir des sources.

Classe les aires d'attraction des villes (INSEE, zonage 2020, géographie au 01/01/2026) de
chaque région par population, prend la commune-centre de la plus peuplée et son centroïde
(geo.api.gouv.fr). Échoue si le résultat diffère des points figés dans
`day_ahead_load.weather_points.POINTS`.

    uv run python scripts/feasibility/choose_weather_points.py --date 2026-11-14
"""

from __future__ import annotations

import argparse
import io
import json
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

import pandas as pd

from day_ahead_load import eco2mix
from day_ahead_load import weather_points as wp

INSEE_ZIP = "https://www.insee.fr/fr/statistiques/fichier/4803954/AAV2020_au_01-01-2026.zip"
INSEE_SHEET = "Composition_communale"
GEO_COMMUNE = "https://geo.api.gouv.fr/communes/{code}?fields=nom,code,codeRegion,centre"
POPULATION_ROOT = Path("data/raw/temperature")
RAW_ROOT = Path("data/raw/insee")
SUMMARY = Path("docs/v0.0-faisabilite/data/meteo-points-choix.json")
USER_AGENT = "day-ahead-load/0.0 (etude de faisabilite)"


def fetch(url: str, target: Path) -> Path:
    if not url.startswith("https://"):
        raise ValueError(f"adresse refusée : {url}")
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=120) as response:
            target.write_bytes(response.read())
    return target


def read_composition(zip_path: Path) -> pd.DataFrame:
    with zipfile.ZipFile(zip_path) as archive:
        names = [n for n in archive.namelist() if n.endswith(".xlsx")]
        if len(names) != 1:
            raise ValueError(f"archive INSEE inattendue : {archive.namelist()}")
        content = archive.read(names[0])
    # Les cinq premières lignes sont un titre ; la sixième porte les noms courts des colonnes.
    composition = pd.read_excel(
        io.BytesIO(content), sheet_name=INSEE_SHEET, header=5, engine="calamine", dtype=str
    )
    return composition


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, help="dossier de téléchargement (AAAA-MM-JJ)")
    args = parser.parse_args()

    directory = RAW_ROOT / args.date
    zip_path = fetch(INSEE_ZIP, directory / "AAV2020_au_01-01-2026.zip")
    composition = read_composition(zip_path)
    communes = json.loads(
        (POPULATION_ROOT / args.date / "population-communes.json").read_text(encoding="utf-8")
    )
    population = pd.Series({c["code"]: c["population"] for c in communes if "population" in c})
    ranking = wp.largest_areas(composition, population)

    computed = []
    for row in ranking.itertuples():
        geo_path = fetch(
            GEO_COMMUNE.format(code=row.commune), directory / "centroides" / f"{row.commune}.json"
        )
        geo: dict[str, Any] = json.loads(geo_path.read_text(encoding="utf-8"))
        lon, lat = geo["centre"]["coordinates"]
        computed.append(
            wp.Point(str(row.region), str(row.aire), str(row.commune), str(row.nom), lat, lon)
        )

    frozen = sorted(wp.POINTS, key=lambda p: p.region)
    if computed != frozen:
        raise SystemExit(f"les points recalculés diffèrent des points figés :\n{computed}")

    summary = {
        "regle": (
            "Centroïde de la commune-centre de l'aire d'attraction des villes la plus peuplée "
            "de chaque région ; aire rattachée à la région de sa commune-centre."
        ),
        "sources": {
            "aires": "INSEE, base des aires d'attraction des villes 2020, géographie au "
            "01/01/2026, mise en ligne le 19/03/2026 (Licence Ouverte 2.0)",
            "population": "INSEE, population des communes servie par geo.api.gouv.fr ; "
            "millésime non indiqué par l'API",
            "centroides": "geo.api.gouv.fr, champ centre",
        },
        "fichiers": {
            zip_path.name: {"sha256": eco2mix.sha256_of(zip_path), "telecharge_le": args.date}
        },
        "limite": (
            "Le millésime de la population n'est pas indiqué. Le seul classement serré est "
            "Centre-Val de Loire (Tours devant Orléans) ; il suit aussi l'ordre des codes INSEE."
        ),
        "points": ranking.to_dict(orient="records"),
        "coordonnees": [p.__dict__ for p in frozen],
    }
    SUMMARY.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    print(ranking.to_string())


if __name__ == "__main__":
    main()
