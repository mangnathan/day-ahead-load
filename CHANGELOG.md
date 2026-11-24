# Changelog

Les évolutions notables du projet sont notées ici, selon le format [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/). Chaque version correspond à une étape du projet et porte un tag Git (`v0.0`, `v0.1`, etc.).

## [Non publié]

## [v0.2] — 2026-11-24

Incertitude autour de la prévision, mesurée sur la validation, test fermé (ADR 0004).

### Ajouté
- Incertitude de la v0.2 : réentraînement mensuel appliqué à la validation (18 modèles, entraînement jusqu'à la fin du mois M − 4, garde-fou testé), quantiles 0,025 à 0,975 par les résidus passés de la demi-heure (Q1), retenu selon la règle écrite avant le calcul : couverture 77,5 % et 94,2 % sur l'évaluation, pinball 288 MW contre 831 MW pour la référence J-7. 13 comparaisons sur la validation.
- Limite constatée de la v0.1 : A17 a appris sur des consommations consolidées publiées après les premiers jours de validation (15/03 au 01/06/2024). Écart mesuré avec la procédure mensuelle sur mars-juin 2024 : −0,012 point de MAPE, non distinguable du bruit.
- ADR 0004 (incertitude de la v0.2) et rapport de la v0.2 en LaTeX, avec la couverture par saison et une prédiction écrite avant le test : couverture trop basse en hiver et trop haute en été.
- Test automatique : les résidus des 15 et 16/03/2024, sans température lissée sur 72 h au début de l'archive de météo prévue, n'entrent dans aucune fenêtre de calibration du test.

### Modifié
- Prévision ponctuelle officielle : A17 réentraîné chaque mois, MAPE de validation 2,667 % (2,617 % pour le modèle figé de la v0.1) et rapport à J-7 de 0,441. README mis à jour : état, résultats, figure, versions.

## [v0.1] — 2026-11-24

Prévision ponctuelle choisie sur la validation, test fermé (ADR 0003). L'étude de faisabilité (v0.0) n'a pas reçu de tag propre : ses entrées sont incluses dans cette version.

### Ajouté
- Table de données de la v0.1 à la demi-heure (ADR 0002) : cible consolidée ou définitive, calendrier (jours fériés par la bibliothèque `holidays`, lundi de Pentecôte, ponts, période de Noël), météo nationale passée à la demi-heure et vue à midi la veille (ERA5 à l'entraînement, calculs ECMWF de 00 UTC ensuite, y compris dans les lissages, avec calcul de secours dont chaque utilisation est enregistrée), niveau des 52 dernières semaines consolidées publiées. Cible du test masquée par défaut.
- Journal des choix de la v0.1 : modèle LightGBM figé (réglages par défaut, graine fixée), règles écrites avant chaque calcul, compteur des comparaisons faites sur la validation.
- Série IFS historique d'entraînement (2017 → 2024-03-14), pour la comparaison des sources météo.
- Comparaison des sources météo et de la durée de l'entraînement (5 modèles sur la validation) : test de bruit par différence appariée de MAPE et bootstrap par blocs d'une semaine, correction de l'écart moyen IFS − ERA5. ERA5 retenu, entraînement à partir du 01/01/2017.
- Comparaison des familles et des variantes du niveau sur la grille complète (régression linéaire avec interactions température × tranche horaire et × mois, LightGBM ; sans niveau, niveau en variable, rapport), 10 comparaisons au total sur la validation. LightGBM avec le niveau en variable retenu.
- Bilan de la v0.1 sur la validation, sans modifier le modèle : position face aux références de la v0.0 avec intervalles par blocs, rapport au naïf J-7 (indication, pas le critère), borne de la météo parfaite, erreurs par saison, température, heure et type de jour, pires jours, importance des variables. ADR 0003 (modèle de la v0.1) et rapport de la v0.1 en LaTeX.
- CI GitHub Actions bloquante sur chaque PR et chaque push sur `main` : installation depuis `uv.lock`, ruff, mypy strict et pytest. Actions épinglées sur un SHA de commit.
- Garde-fou des tests : toute connexion réseau pendant un test échoue ; les tests ne tournent que sur des données fictives.
- Étude de faisabilité : mesures de l'historique éCO2mix, diagnostic de la prévision J-1 de RTE (alignement, changements d'heure, biais mensuel), références simples sous la règle de midi la veille, choix des poids de l'indice national de température.
- Points météo : 12 points fixés sur les aires d'attraction des villes de l'INSEE, contrôle terrestre des mailles et de la convention du rayonnement.
- Téléchargement de la météo Open-Meteo (ERA5, IFS historique, calculs ECMWF de 00 UTC) sous plafond local de 8 000 appels par jour, avec arrêt définitif au premier refus de quota.
- Workflow planifié, séparé de la CI, qui mesure chaque jour l'heure de disponibilité du calcul ECMWF (un appel par jour au plus, arrêt définitif au premier refus de quota) et l'écrit sur la branche `donnees/disponibilite-ecmwf`.
- Clôture de l'étude de faisabilité : questions de Cagan, prémortem, décision de go dégradé, ADR 0001 (cible, règles de disponibilité, étiquettes, découpage, critères de réussite et d'échec, fonction de coût) et rapport de faisabilité en LaTeX.
- Résumé de travail de l'étude de faisabilité : choix de la pondération de l'indice de température, licences des données ENTSO-E (conditions de 2023, liste du 18/10/2023), options de la fonction de coût.

### Modifié
- Convention de la demi-heure : (t − 15 min, t + 15 min] retenue à la place de (t − 30 min, t] par une mesure dans l'entraînement seulement, selon la règle fixée avant le calcul (écart relatif de 2,1 %, signal fragile noté dans l'ADR 0002).
- Mesure quotidienne de la disponibilité ECMWF : elle vise le calcul de 00 UTC, celui de la règle de midi. Lecture de l'API à 9 h UTC avec le calcul lu et l'adresse du serveur atteint, et lecture du fichier propre au calcul de 00 UTC sur la copie AWS (heure de dépôt). Nouveau fichier `disponibilite-ecmwf-00utc.csv`.
- Règle de disponibilité de la météo prévue : dépôt sur AWS + 2 h, vérifiée sur 95 calculs de 00 UTC, en heure d'été comme en heure d'hiver.
- Mesure quotidienne de la disponibilité ECMWF : lecture de l'API (référence) et de la copie publique d'Open-Meteo sur AWS, dans une même ligne avec le statut de chacune, et écart entre les deux les jours où les deux répondent. Nouveau fichier `disponibilite-ecmwf.csv` ; l'ancien est gardé comme historique.

### Corrigé
- Mesure quotidienne de la disponibilité ECMWF : la première exécution planifiée a échoué sur un délai de connexion dépassé. Une coupure réseau ou une réponse 5xx donne maintenant lieu à une seule nouvelle tentative après 2 minutes ; un deuxième échec écrit une ligne « échec » datée au lieu de faire échouer le workflow.
