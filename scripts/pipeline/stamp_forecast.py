"""v0.4 : ajoute à un fichier de prévision les heures enregistrées par GitHub et son statut.

L'heure de départ de l'exécution et l'heure de fin de l'étape de prévision sont lues par l'API
de GitHub dans le workflow, puis passées ici. Le statut « à l'heure » ou « en retard » se juge
sur la fin de l'étape de prévision (journal des choix, entrée 27). Le contenu de prévision et
son empreinte ne changent pas.

    uv run python scripts/pipeline/stamp_forecast.py --fichier F
        --depart-execution T1 --fin-prevision T2
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import pandas as pd

from day_ahead_load import daily


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fichier", type=Path, required=True)
    parser.add_argument("--depart-execution", required=True)
    parser.add_argument("--fin-prevision", required=True)
    args = parser.parse_args()

    record = json.loads(args.fichier.read_text(encoding="utf-8"))
    if daily.content_sha256(record["contenu"]) != record["contenu_sha256"]:
        raise RuntimeError("le contenu de la prévision ne correspond plus à son empreinte")
    day = date.fromisoformat(record["contenu"]["jour_livre"])
    finished = pd.Timestamp(args.fin_prevision).tz_convert("UTC")
    record["execution"].update(
        {
            "depart_de_l_execution_utc": pd.Timestamp(args.depart_execution)
            .tz_convert("UTC")
            .strftime("%Y-%m-%dT%H:%M:%SZ"),
            "fin_de_l_etape_de_prevision_utc": finished.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "statut": daily.on_time(finished.to_pydatetime(), day),
        }
    )
    args.fichier.write_text(
        json.dumps(record, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"{day} : {record['execution']['statut']}")


if __name__ == "__main__":
    main()
