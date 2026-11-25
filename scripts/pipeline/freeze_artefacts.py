"""v0.4 : fabrique les artefacts figés de la chaîne quotidienne (journal des choix, entrée 27).

Ne lit que le cache local et s'arrête au 31/08/2025 : aucune consommation du test n'est lue.
Refuse de partir si le dépôt a des modifications non commitées, pour que le commit enregistré
décrive exactement le code qui a fabriqué les artefacts.

    uv run python scripts/pipeline/freeze_artefacts.py
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from day_ahead_load import diagnostics, eco2mix, frozen
from day_ahead_load import modelling as md
from day_ahead_load import table as tb
from day_ahead_load import temperature_index as ti
from day_ahead_load import weather_features as wf
from day_ahead_load.weather_points import POINTS

ECO2MIX = Path("data/raw/eco2mix/2026-11-14")
WEATHER = Path("data/raw/meteo")
WEIGHTS = Path("docs/v0.0-faisabilite/data/indice-temperature-poids.json")
INTERVALS = Path("docs/v0.2-incertitude/data/intervalles.json")
OUTPUT = Path("artefacts/v0.4")


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout.strip()  # noqa: S603, S607


def main() -> None:
    if git("status", "--porcelain"):
        raise SystemExit("dépôt modifié : committer d'abord, le commit est enregistré")
    commit = git("rev-parse", "HEAD")

    paths = [ECO2MIX / f"{name}.parquet" for name in eco2mix.DATASETS]
    instants, _ = diagnostics.with_local_instants(diagnostics.read_raw(paths))
    stored = json.loads(WEIGHTS.read_text(encoding="utf-8"))
    weights = ti.normalize(stored["resultats"]["consommation"]["poids_sur_2016_2023"])
    archive = wf.archive_index(WEATHER, "era5", POINTS, weights)
    runs = wf.runs_index(WEATHER, POINTS, weights)
    table = tb.build(instants, archive, runs, md.TRAIN_FIRST, tb.VALIDATION[1]).table
    train_table = tb.with_observed_weather(table, archive)
    validation = table[table["periode"] == "validation"]

    # Résidus de la procédure mensuelle : elle doit retrouver sa MAPE de la v0.2.
    monthly, _ = md.monthly_forecasts(train_table, validation)
    official = json.loads(INTERVALS.read_text(encoding="utf-8"))["procedure_mensuelle"][
        "mape_information"
    ]["toute_la_validation"]["mape_mensuelle_pct"]
    if round(md.mape(validation[tb.TARGET], monthly.to_numpy()), 3) != official:
        raise RuntimeError("la procédure mensuelle ne retrouve pas sa MAPE de la v0.2")
    residuals = validation[tb.TARGET] - monthly

    rows = frozen.training_rows(train_table)
    model_text = frozen.fit_model(rows)
    offsets_text = frozen.offsets_json(frozen.offsets(residuals, validation))

    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "modele.txt").write_text(model_text, encoding="utf-8", newline="\n")
    (OUTPUT / "ecarts-fourchette.json").write_text(offsets_text, encoding="utf-8", newline="\n")
    meta = {
        "regle": "journal des choix, entrée 27",
        "cree_le": datetime.now(UTC).isoformat(timespec="seconds"),
        "commit": commit,
        "modele": {
            "fichier": "modele.txt",
            "sha256": frozen.sha256((OUTPUT / "modele.txt").read_bytes()),
            "configuration_sha256": md.config_sha256(),
            "entrainement": [str(md.TRAIN_FIRST), str(frozen.FROZEN_END)],
            "lignes": len(rows),
            "meteo_entrainement": "ERA5",
        },
        "fourchette": {
            "fichier": "ecarts-fourchette.json",
            "sha256": frozen.sha256((OUTPUT / "ecarts-fourchette.json").read_bytes()),
            "residus": [str(frozen.OFFSET_WINDOW[0]), str(frozen.OFFSET_WINDOW[1])],
            "niveaux": [str(level) for level in frozen.OFFSET_LEVELS],
            "limite": (
                "résidus de modèles plus anciens, hors échantillon : la fourchette décrit un "
                "modèle un peu moins bien informé que celui qui tourne"
            ),
        },
        "quantile_d_achat": {"q": frozen.PURCHASE_Q, "etiquette": frozen.PURCHASE_LABEL},
    }
    (OUTPUT / "meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps(meta, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
