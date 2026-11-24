"""Figure du README : MAPE de validation du modèle et des références, en SVG.

Lit seulement le bilan de la v0.1 (erreurs agrégées) : aucune série de consommation ni courbe
de RTE n'est dessinée. Écrit une version pour le thème clair et une pour le thème sombre.

    uv run python scripts/docs/readme_figure.py
"""

from __future__ import annotations

import json
from pathlib import Path
from xml.sax.saxutils import escape

BILAN = Path("docs/v0.1-prevision-ponctuelle/data/bilan-v0-1.json")
OUTPUT = Path("docs/images")
BARS = (
    ("rte_corrige_meme_mois_an_dernier", "RTE J-1 corrigée (même mois l'an dernier)", "avantagée"),
    ("rte_corrige_retard_reel", "RTE J-1 corrigée (28 derniers jours publiés)", "avantagée"),
    ("rte_j1_brut", "RTE J-1 brute", "avantagée"),
    ("modele", "day-ahead-load, modèle de la v0.1", "disponible à midi"),
    ("naif_j7", "Même demi-heure 7 jours avant", "optimiste"),
    ("naif_annee_precedente", "Même jour, 52 semaines avant", "réaliste"),
)
THEMES = {
    "clair": {
        "primary": "#0b0b0b",
        "secondary": "#52514e",
        "highlight": "#2a78d6",
        "context": "#86857e",
        "rule": "#d6d5d0",
    },
    "sombre": {
        "primary": "#f0efec",
        "secondary": "#c3c2b7",
        "highlight": "#3987e5",
        "context": "#6e6d66",
        "rule": "#3a3a38",
    },
}
FONT = "-apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"
WIDTH = 820
LABEL_X = 16
BAR_X = 400
BAR_MAX = 330
ROW = 40
THICKNESS = 18
TOP = 58


def percent(value: float) -> str:
    return f"{value:.2f}".replace(".", ",") + " %"


def bar(x: float, y: float, length: float, color: str) -> str:
    """Barre horizontale à bout arrondi (4 px), carrée contre la ligne de base."""
    r = 4
    return (
        f'<path d="M{x},{y} H{x + length - r} Q{x + length},{y} {x + length},{y + r} '
        f"V{y + THICKNESS - r} Q{x + length},{y + THICKNESS} {x + length - r},{y + THICKNESS} "
        f'H{x} Z" fill="{color}"/>'
    )


def svg(values: dict[str, float], theme: dict[str, str]) -> str:
    scale = BAR_MAX / max(values[key] for key, _, _ in BARS)
    height = TOP + ROW * len(BARS) + 24
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height}" '
        f'viewBox="0 0 {WIDTH} {height}" font-family="{FONT}" role="img" '
        'aria-label="MAPE de validation du modèle de la v0.1 et des références">',
        f'<text x="{LABEL_X}" y="24" font-size="15" font-weight="600" fill="{theme["primary"]}">'
        "Erreur moyenne en pourcentage (MAPE) sur la validation, plus bas = mieux</text>",
        f'<text x="{LABEL_X}" y="44" font-size="12" fill="{theme["secondary"]}">'
        "Jours livrés du 15/03/2024 au 31/08/2025, 25 607 demi-heures communes. "
        "« Avantagée » : publiée après midi la veille.</text>",
    ]
    for i, (key, label, tag) in enumerate(BARS):
        y = TOP + i * ROW
        mid = y + THICKNESS / 2 + 4
        is_model = key == "modele"
        weight = "600" if is_model else "400"
        color = theme["highlight"] if is_model else theme["context"]
        length = values[key] * scale
        parts += [
            f'<text x="{LABEL_X}" y="{mid}" font-size="13" font-weight="{weight}" '
            f'fill="{theme["primary"]}">{escape(label)} '
            f'<tspan fill="{theme["secondary"]}" font-weight="400">· {escape(tag)}</tspan></text>',
            bar(BAR_X, y, length, color),
            f'<text x="{BAR_X + length + 8}" y="{mid}" font-size="13" font-weight="{weight}" '
            f'fill="{theme["primary"]}">{percent(values[key])}</text>',
        ]
    base_bottom = TOP + ROW * (len(BARS) - 1) + THICKNESS + 6
    parts += [
        f'<line x1="{BAR_X}" y1="{TOP - 6}" x2="{BAR_X}" y2="{base_bottom}" '
        f'stroke="{theme["rule"]}" stroke-width="1"/>',
        f'<text x="{LABEL_X}" y="{height - 10}" font-size="11" fill="{theme["secondary"]}">'
        "Source : calculs du projet à partir d'éCO2mix (RTE, via ODRÉ). "
        "Erreurs agrégées seulement.</text>",
        "</svg>",
    ]
    return "\n".join(parts) + "\n"


def main() -> None:
    bilan = json.loads(BILAN.read_text(encoding="utf-8"))
    values = {key: float(v["mape_reference_pct"]) for key, v in bilan["references"].items()}
    values["modele"] = float(bilan["echantillon_commun"]["mape_modele_pct"])
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for name, theme in THEMES.items():
        path = OUTPUT / f"mape-validation-{name}.svg"
        path.write_text(svg(values, theme), encoding="utf-8", newline="\n")
        print(f"écrit : {path}")


if __name__ == "__main__":
    main()
