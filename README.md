# day-ahead-load

Prévision probabiliste de la consommation électrique française du lendemain, traduite en décision d'achat pour un fournisseur dont le portefeuille suit la forme de la consommation nationale.

État : étude de faisabilité (v0.0) en cours.

## Contrôles

Les mêmes contrôles tournent en local et en CI, sur des données fictives uniquement (aucune connexion réseau pendant les tests) :

```
uv sync --locked
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
uv run --no-sync mypy
uv run --no-sync pytest
```
