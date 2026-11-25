"""v0.4 : niveau des 52 semaines des décisions d'un mois (journal des choix, entrée 27).

Lancé une fois par mois par le workflow « Niveau mensuel » :

    uv run python scripts/pipeline/monthly_level.py --donnees donnees [--mois 2026-12]

Télécharge l'export éCO2mix d'ODRÉ (deux fichiers), puis calcule, pour chaque jour livré D dont
la décision (la veille, à midi) tombe dans le mois, le niveau des 52 dernières semaines de
consolidé publié à cette heure (règle M+3). Seuls ces niveaux, des moyennes, sont publiés,
jamais la série. Un niveau incomplet est écrit vide : la chaîne n'émet alors pas de prévision.
Relancé plusieurs fois par mois, il ne remplit que les niveaux vides des décisions encore à
venir, et ne change jamais une valeur publiée.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from day_ahead_load import daily, diagnostics, eco2mix
from day_ahead_load import table as tb


def decision_days(month: str) -> list[date]:
    """Jours livrés dont la veille tombe dans `month` : du 2 du mois au 1er du mois suivant."""
    period = pd.Period(month, freq="M")
    first = period.start_time.date() + timedelta(days=1)
    last = (period + 1).start_time.date()
    return [first + timedelta(days=k) for k in range((last - first).days + 1)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--donnees", type=Path, required=True)
    parser.add_argument("--mois", default=datetime.now(UTC).strftime("%Y-%m"))
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        downloads = [eco2mix.download(name, Path(tmp)) for name in eco2mix.DATASETS]
        instants, _ = diagnostics.with_local_instants(
            diagnostics.read_raw([d.path for d in downloads])
        )
        target = tb.target_utc(instants)
    days = decision_days(args.mois)
    levels = tb.level_by_day(target, days)
    body = {
        "mois_de_decision": args.mois,
        "source": "éCO2mix (RTE, via ODRÉ), Licence Ouverte 2.0",
        "telecharge_le": datetime.now(UTC).isoformat(timespec="seconds"),
        "fichiers_sha256": {d.dataset: d.sha256 for d in downloads},
        "regle": "moyenne des 52 dernières semaines de consolidé publié à midi la veille (M+3)",
        "niveaux": {
            str(day): None if not np.isfinite(value) else round(float(value), 1)
            for day, value in levels.items()
        },
    }
    path = args.donnees / "niveau" / f"{args.mois}.json"
    if path.exists():
        previous = json.loads(path.read_text(encoding="utf-8"))["niveaux"]
        body["niveaux"] = daily.merge_levels(previous, body["niveaux"], datetime.now(UTC))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(body, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    missing = [k for k, v in body["niveaux"].items() if v is None]
    print(f"{args.mois} : {len(days) - len(missing)} niveaux, {len(missing)} vides")


if __name__ == "__main__":
    main()
