"""Ajoute la mesure du jour de l'heure de disponibilité du calcul ECMWF IFS 9 km.

Lancé une fois par jour par le workflow planifié `disponibilite-ecmwf.yml`, jamais par la CI.

    uv run python scripts/monitoring/record_ecmwf_availability.py --dossier donnees
"""

from __future__ import annotations

import argparse
from pathlib import Path

from day_ahead_load import availability


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dossier", type=Path, required=True, help="copie de la branche de données"
    )
    args = parser.parse_args()
    print(availability.record(args.dossier))


if __name__ == "__main__":
    main()
