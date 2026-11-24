# day-ahead-load

Prévision probabiliste de la consommation électrique française du lendemain, traduite en décision d'achat pour un fournisseur dont le portefeuille suit la forme de la consommation nationale.

État : étude de faisabilité (v0.0) terminée, décision de go dégradé. Le cadre est fixé avant toute modélisation dans l'[ADR 0001](docs/adr/0001-cadrage.md) et le [rapport de faisabilité](docs/pdf/day-ahead-load_v0.0_Rapport-de-faisabilite.pdf).

Prévision ponctuelle (v0.1) choisie sur la validation, test fermé : LightGBM avec le niveau des 52 dernières semaines, MAPE de validation de 2,61 %. Les choix sont dans le [journal des choix](docs/v0.1-prevision-ponctuelle/journal-des-choix.md), le modèle dans l'[ADR 0003](docs/adr/0003-modele-v0-1.md), le bilan dans le [rapport de la v0.1](docs/pdf/day-ahead-load_v0.1_Rapport-prevision-ponctuelle.pdf).

## Contrôles

Les mêmes contrôles tournent en local et en CI, sur des données fictives uniquement (aucune connexion réseau pendant les tests) :

```
uv sync --locked
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
uv run --no-sync mypy
uv run --no-sync pytest
```

## Rapports

Les rapports se compilent avec [Tectonic](https://tectonic-typesetting.github.io), depuis le dossier de leur version :

```
cd docs/v0.0-faisabilite
tectonic -X compile v0.0-rapport-de-faisabilite.tex
cd ../v0.1-prevision-ponctuelle
tectonic -X compile v0.1-rapport-prevision-ponctuelle.tex
```
