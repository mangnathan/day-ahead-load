# day-ahead-load

Prévision probabiliste de la consommation électrique française du lendemain, traduite en décision d'achat pour un fournisseur dont le portefeuille suit la forme de la consommation nationale.

État : étude de faisabilité (v0.0) terminée, décision de go dégradé. Le cadre est fixé avant toute modélisation dans l'[ADR 0001](docs/adr/0001-cadrage.md) et le [rapport de faisabilité](docs/pdf/day-ahead-load_v0.0_Rapport-de-faisabilite.pdf).

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
```
