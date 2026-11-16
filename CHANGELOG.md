# Changelog

Les évolutions notables du projet sont notées ici, selon le format [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/). Chaque version correspond à une étape du projet et porte un tag Git (`v0.0`, `v0.1`, etc.).

## [Non publié]

### Ajouté
- CI GitHub Actions bloquante sur chaque PR et chaque push sur `main` : installation depuis `uv.lock`, ruff, mypy strict et pytest. Actions épinglées sur un SHA de commit.
- Garde-fou des tests : toute connexion réseau pendant un test échoue ; les tests ne tournent que sur des données fictives.
- Étude de faisabilité : mesures de l'historique éCO2mix, diagnostic de la prévision J-1 de RTE (alignement, changements d'heure, biais mensuel), références simples sous la règle de midi la veille, choix des poids de l'indice national de température.
- Points météo : 12 points fixés sur les aires d'attraction des villes de l'INSEE, contrôle terrestre des mailles et de la convention du rayonnement.
- Téléchargement de la météo Open-Meteo (ERA5, IFS historique, calculs ECMWF de 00 UTC) sous plafond local de 8 000 appels par jour, avec arrêt définitif au premier refus de quota.
- Workflow planifié, séparé de la CI, qui mesure chaque jour l'heure de disponibilité du calcul ECMWF (un appel par jour au plus, arrêt définitif au premier refus de quota) et l'écrit sur la branche `donnees/disponibilite-ecmwf`.
- Clôture de l'étude de faisabilité : questions de Cagan, prémortem, décision de go dégradé, ADR 0001 (cible, règles de disponibilité, étiquettes, découpage, critères de réussite et d'échec, fonction de coût) et rapport de faisabilité en LaTeX.
- Résumé de travail de l'étude de faisabilité : choix de la pondération de l'indice de température, licences des données ENTSO-E (conditions de 2023, liste du 18/10/2023), options de la fonction de coût.

### Modifié
- Mesure quotidienne de la disponibilité ECMWF : lecture de l'API (référence) et de la copie publique d'Open-Meteo sur AWS, dans une même ligne avec le statut de chacune, et écart entre les deux les jours où les deux répondent. Nouveau fichier `disponibilite-ecmwf.csv` ; l'ancien est gardé comme historique.

### Corrigé
- Mesure quotidienne de la disponibilité ECMWF : la première exécution planifiée a échoué sur un délai de connexion dépassé. Une coupure réseau ou une réponse 5xx donne maintenant lieu à une seule nouvelle tentative après 2 minutes ; un deuxième échec écrit une ligne « échec » datée au lieu de faire échouer le workflow.
