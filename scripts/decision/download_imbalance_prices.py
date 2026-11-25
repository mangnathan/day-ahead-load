"""v0.3 : prix des écarts d'ENTSO-E (17.1.G, France), sous plafond d'appels.

Trois étapes, dans cet ordre (journal des choix, entrée 24) :

    uv run python scripts/decision/download_imbalance_prices.py estimation
    uv run python scripts/decision/download_imbalance_prices.py controle
    uv run python scripts/decision/download_imbalance_prices.py telecharger

- `estimation` : nombre d'appels prévus, sans aucun appel réseau ;
- `controle` : un seul appel, sur une journée, qui vérifie le nom du paramètre de zone et le
  format de la réponse ; affiche seulement la structure de la réponse (statut, type, balises) ;
- `telecharger` : une requête par mois, sous le plafond du jour ; refuse de partir sans un
  contrôle réussi. Relancer le lendemain reprend depuis le cache.

Le jeton est lu dans `.env` (clé ENTSOE_TOKEN) et n'est jamais affiché. Au premier refus de
quota (429), un fichier d'arrêt est écrit et plus aucun appel n'est fait tant qu'il existe.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from day_ahead_load import entsoe
from day_ahead_load import weather as w

ENV = Path(".env")
ROOT = Path("data/raw/entsoe")
CACHE = ROOT / "prix-des-ecarts"
LEDGER = ROOT / "journal-appels.json"
STOP = ROOT / "ARRET-QUOTA.json"


def client() -> entsoe.Client:
    budget = w.Budget(LEDGER, STOP, cap=entsoe.DAILY_CAP)
    return entsoe.Client(entsoe.load_token(ENV), CACHE, budget)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("etape", choices=["estimation", "controle", "telecharger"])
    args = parser.parse_args()

    if args.etape == "estimation":
        counts = entsoe.estimate()
        print(json.dumps({**counts, "total": sum(counts.values())}, indent=2))
        print(f"plafond local : {entsoe.DAILY_CAP} appels par jour")
        return

    c = client()
    if args.etape == "controle":
        body_path, meta = c.get(entsoe.control_request())
        print(json.dumps(meta, indent=2, ensure_ascii=False))
        print(json.dumps(entsoe.structure(body_path.read_bytes()), indent=2, ensure_ascii=False))
        return

    control = CACHE / f"{entsoe.control_request().cache_name}.json"
    if not control.exists():
        raise SystemExit("lancer d'abord l'étape controle, et en lire le résultat")
    for request in entsoe.monthly_requests():
        _, meta = c.get(request)
        print(f"{request.name} : {meta['octets']} octets")
    print(f"{c.calls} appels dans cette séance")


if __name__ == "__main__":
    main()
