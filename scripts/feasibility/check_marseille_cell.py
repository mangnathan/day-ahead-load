"""Étude de faisabilité : part d'eau dans la maille ERA5 retenue pour Marseille.

La sélection terrestre d'Open-Meteo a placé la maille ERA5 de Marseille à 26,6 km au nord du
point, centrée sur Rognac, au bord de l'étang de Berre. Le contrôle terrestre (centre de maille
sur une commune) ne voit pas l'étang : les contours des communes l'incluent. On estime donc la
part d'eau à partir de l'altitude du modèle numérique de terrain servi par Open-Meteo
(Copernicus GLO-90), où les surfaces d'eau sont aplanies au niveau de l'eau.

Appels : 400 points (grille de 20 × 20) plus 2 points témoins, comptés un par point, sous le
même plafond journalier et le même arrêt au 429 que le téléchargement.

    uv run python scripts/feasibility/check_marseille_cell.py
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from day_ahead_load import weather as w

RAW_ROOT = Path("data/raw/meteo")
CONTROL = Path("docs/v0.0-faisabilite/data/meteo-controle.json")
SUMMARY = Path("docs/v0.0-faisabilite/data/marseille-maille-era5.json")
ERA5_STEP = 0.25
GRID = 20
WATER_MAX_M = 0.5
# Points témoins : le milieu de l'étang de Berre et la rade de Marseille (mer).
WITNESSES = {"etang_de_berre": (43.47, 5.15), "rade_de_marseille": (43.29, 5.32)}
BATCH = 100


def era5_cell() -> tuple[float, float]:
    summary = json.loads(CONTROL.read_text(encoding="utf-8"))
    entry = next(p for p in summary["points"] if p["nom"] == "Marseille")
    cell = next(m for m in entry["mailles"] if m["source"] == "era5")
    return float(cell["latitude_maille"]), float(cell["longitude_maille"])


def elevations(dl: w.Downloader, points: list[tuple[float, float]]) -> list[float]:
    out: list[float] = []
    for start in range(0, len(points), BATCH):
        batch = points[start : start + BATCH]
        url = w.checked_url(
            w.ELEVATION_URL,
            {
                "latitude": ",".join(f"{lat:.5f}" for lat, _ in batch),
                "longitude": ",".join(f"{lon:.5f}" for _, lon in batch),
            },
        )
        payload, _ = dl.call(url)
        out.extend(float(e) for e in payload["elevation"])
    return out


def main() -> None:
    lat0, lon0 = era5_cell()
    half = ERA5_STEP / 2
    # Centres des sous-cases d'une grille régulière couvrant la maille.
    offsets = (np.arange(GRID) + 0.5) / GRID * ERA5_STEP - half
    grid = [(lat0 + a, lon0 + b) for a in offsets for b in offsets]
    dl = w.Downloader(
        RAW_ROOT, w.Budget(RAW_ROOT / "journal-appels.json", RAW_ROOT / "ARRET-QUOTA.json")
    )
    witness_values = elevations(dl, list(WITNESSES.values()))
    values = np.array(elevations(dl, grid))
    water = values <= WATER_MAX_M
    summary: dict[str, Any] = {
        "maille_era5": {"latitude": lat0, "longitude": lon0, "pas_deg": ERA5_STEP},
        "methode": (
            "Altitude Copernicus GLO-90 servie par l'API d'altitude d'Open-Meteo, sur une "
            f"grille de {GRID} x {GRID} points ; un point est compté comme eau si son altitude "
            f"est au plus {WATER_MAX_M} m."
        ),
        "temoins_altitude_m": dict(zip(WITNESSES, witness_values, strict=True)),
        "points": int(values.size),
        "part_eau_pct": round(100 * float(water.mean()), 1),
        "altitude_mediane_m": float(np.median(values)),
        "limite": (
            "Une terre très basse (marais, salins) peut être comptée comme eau ; la part d'eau "
            "est donc une borne haute."
        ),
        "appels": dl.calls,
    }
    SUMMARY.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
