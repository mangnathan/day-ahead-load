from __future__ import annotations

import pandas as pd
import pytest

from day_ahead_load import weather_points as wp
from day_ahead_load.temperature_index import MAINLAND_REGIONS


def composition() -> pd.DataFrame:
    # Région fictive « 28 » : la plus grande commune (Port, 170) est dans une petite aire ;
    # l'aire de Ville (commune-centre 110 + couronne 120 = 230) est plus peuplée.
    rows = [
        ("1", "Ville", "A", "Ville", "11", "28"),
        ("2", "Banlieue", "A", "Ville", "20", "28"),
        ("3", "Port", "B", "Port", "11", "28"),
        ("4", "Village", "000", "Hors attraction", "30", "28"),
        ("5", "Autre", "C", "Autre", "11", "11"),
    ]
    return pd.DataFrame(
        rows, columns=["CODGEO", "LIBGEO", "AAV2020", "LIBAAV2020", "CATEAAV2020", "REG"]
    )


POPULATION = pd.Series({"1": 110, "2": 120, "3": 170, "4": 999, "5": 50})


def test_area_population_wins_over_largest_commune() -> None:
    ranking = wp.largest_areas(composition(), POPULATION).set_index("region")
    assert ranking.loc["28", "nom"] == "Ville"
    assert ranking.loc["28", "population_aire"] == 230
    assert ranking.loc["28", "deuxieme_aire"] == "Port"


def test_communes_outside_areas_are_ignored() -> None:
    ranking = wp.largest_areas(composition(), POPULATION).set_index("region")
    assert "Hors attraction" not in set(ranking["libelle_aire"])


def test_missing_population_is_an_error() -> None:
    with pytest.raises(ValueError, match="sans population"):
        wp.largest_areas(composition(), POPULATION.drop("2"))


def test_one_frozen_point_per_mainland_region() -> None:
    assert sorted(p.region for p in wp.POINTS) == sorted(MAINLAND_REGIONS)
    assert all(41 < p.latitude < 51.5 and -5 < p.longitude < 10 for p in wp.POINTS)
