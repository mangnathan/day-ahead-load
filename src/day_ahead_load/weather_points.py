"""Les 12 points météo de l'indice national de température.

Règle : dans chaque région de France métropolitaine continentale, le point est le centroïde de
la commune-centre de l'aire d'attraction des villes (INSEE, zonage 2020) la plus peuplée de la
région. L'aire est rattachée à la région de sa commune-centre. La commune la plus peuplée n'est
pas retenue : elle n'est pas toujours la plus représentative (en Normandie, Le Havre est sur la
côte alors que l'aire de Rouen est plus grande et à l'intérieur des terres).

Les points sont figés ici. Le script `scripts/feasibility/choose_weather_points.py` les
recalcule à partir des sources et échoue s'ils ont changé.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from day_ahead_load.temperature_index import MAINLAND_REGIONS

# Catégorie INSEE de la commune dans l'aire : 11 = commune-centre.
COMMUNE_CENTRE = "11"
OUTSIDE_AREAS = "000"


@dataclass(frozen=True)
class Point:
    region: str
    aire: str
    commune: str
    nom: str
    latitude: float
    longitude: float


# Centroïdes des communes servis par geo.api.gouv.fr (champ `centre`), consultés le 14/11/2026.
POINTS: tuple[Point, ...] = (
    Point("11", "001", "75056", "Paris", 48.8589, 2.3470),
    Point("24", "019", "37261", "Tours", 47.3943, 0.6949),
    Point("27", "028", "21231", "Dijon", 47.3319, 5.0322),
    Point("28", "015", "76540", "Rouen", 49.4412, 1.0912),
    Point("32", "004", "59350", "Lille", 50.6311, 3.0468),
    Point("44", "010", "67482", "Strasbourg", 48.5691, 7.7621),
    Point("52", "008", "44109", "Nantes", 47.2382, -1.5603),
    Point("53", "013", "35238", "Rennes", 48.1159, -1.6884),
    Point("75", "006", "33063", "Bordeaux", 44.8624, -0.5848),
    Point("76", "005", "31555", "Toulouse", 43.6007, 1.4328),
    Point("84", "002", "69123", "Lyon", 45.7580, 4.8351),
    Point("93", "003", "13055", "Marseille", 43.2803, 5.3806),
)


def largest_areas(composition: pd.DataFrame, population: pd.Series) -> pd.DataFrame:
    """Classe les aires de chaque région par population et garde les deux premières.

    `composition` : une ligne par commune, colonnes CODGEO, AAV2020, LIBAAV2020, CATEAAV2020,
    REG (fichier INSEE). `population` : population indexée par code commune.
    Renvoie une ligne par région : la première aire, sa commune-centre, sa population, et la
    deuxième aire avec sa population pour montrer l'écart.
    """
    missing = set(composition["CODGEO"]) - set(population.index)
    if missing:
        raise ValueError(f"{len(missing)} communes sans population, par ex. {sorted(missing)[:3]}")
    df = composition[composition["AAV2020"] != OUTSIDE_AREAS].copy()
    df["population"] = df["CODGEO"].map(population)
    areas = df.groupby(["AAV2020", "LIBAAV2020"], as_index=False)["population"].sum()
    centres = (
        df[df["CATEAAV2020"] == COMMUNE_CENTRE]
        .sort_values("population", ascending=False)
        .drop_duplicates("AAV2020")
        .rename(columns={"CODGEO": "commune", "LIBGEO": "nom", "REG": "region"})
    )[["AAV2020", "commune", "nom", "region"]]
    areas = areas.merge(centres, on="AAV2020", how="inner")
    areas = areas[areas["region"].isin(MAINLAND_REGIONS)]
    rows = []
    for region, group in areas.groupby("region"):
        ranked = group.sort_values("population", ascending=False).reset_index(drop=True)
        first = ranked.iloc[0]
        second = ranked.iloc[1] if len(ranked) > 1 else None
        rows.append(
            {
                "region": str(region),
                "aire": str(first["AAV2020"]),
                "libelle_aire": str(first["LIBAAV2020"]),
                "population_aire": int(first["population"]),
                "commune": str(first["commune"]),
                "nom": str(first["nom"]),
                "deuxieme_aire": None if second is None else str(second["LIBAAV2020"]),
                "population_deuxieme_aire": None if second is None else int(second["population"]),
            }
        )
    return pd.DataFrame(rows).sort_values("region").reset_index(drop=True)
