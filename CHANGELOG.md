# Changelog

Les évolutions notables du projet sont notées ici, selon le format [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/). Chaque version correspond à une étape du projet et porte un tag Git (`v0.0`, `v0.1`, etc.).

## [Non publié]

### Ajouté
- CI GitHub Actions bloquante sur chaque PR et chaque push sur `main` : installation depuis `uv.lock`, ruff, mypy strict et pytest. Actions épinglées sur un SHA de commit.
- Garde-fou des tests : toute connexion réseau pendant un test échoue ; les tests ne tournent que sur des données fictives.
- Étude de faisabilité : mesures de l'historique éCO2mix, diagnostic de la prévision J-1 de RTE (alignement, changements d'heure, biais mensuel), références simples sous la règle de midi la veille, choix des poids de l'indice national de température.
