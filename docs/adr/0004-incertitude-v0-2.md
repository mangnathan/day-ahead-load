# ADR 0004 : incertitude de la v0.2

- Statut : proposé le 24/11/2026, à accepter à la relecture du rapport de la v0.2
- Date : 24 novembre 2026
- Version : v0.2

## Contexte

L'ADR 0001 fixe ce que la prévision doit dire de son incertitude : cinq quantiles (0,025, 0,1, 0,5, 0,9 et 0,975), un intervalle à 80 % qui couvre entre 75 et 85 % des demi-heures et un intervalle à 95 % qui en couvre entre 92 et 98 %, et un score par quantiles (pinball) meilleur que celui d'une référence fondée sur J-7. Ces critères se jugent sur le test, en v1.0. L'ADR 0001 prévoit aussi, sur le test, un réentraînement du modèle au début de chaque mois et une calibration sur les résidus des 12 derniers mois calculés avec la météo prévue.

La v0.2 construit ces quantiles autour du modèle de la v0.1 (ADR 0003), sans changer sa configuration. Les règles ont été écrites dans le journal des choix avant le calcul (entrée 21), les résultats y sont notés (entrées 22 et 23). Code : `src/day_ahead_load/uncertainty.py` et `modelling.py` ; calcul : `scripts/modelling/compare_intervals.py` ; résultats : `docs/v0.2-incertitude/data/intervalles.json`.

## Décision

### Prévision ponctuelle : A17 avec réentraînement mensuel

La procédure de l'ADR 0001 est appliquée dès la validation. Chaque mois, un modèle de même configuration qu'A17 (LightGBM figé, 100 itérations, graine 20261117, 14 variables, entraînement depuis le 01/01/2017 sur la météo ERA5) apprend les jours publiés en consolidé et prévoit le mois. Le modèle du mois M prévoit dès le 1er du mois, donc il doit exister à midi le dernier jour de M − 1 : il apprend jusqu'à la fin de M − 4 seulement, et un test échoue sur toute ligne plus récente. Les 18 modèles de la validation (mars 2024 à août 2025) s'arrêtent exactement à cette date.

**MAPE officielle de validation : 2,667 %.** Le chiffre de 2,617 % reste dans l'historique de la v0.1, sous l'étiquette « modèle figé ». La procédure a été gardée sans condition sur son résultat : son écart avec le modèle figé (+0,050 point, intervalle [−0,022 ; +0,122]) n'est pas distinguable du bruit. Rapport au naïf J-7 sur l'échantillon commun du bilan de la v0.1, à titre d'indication et non comme critère : 0,441, intervalle [0,382 ; 0,512].

### Quantiles : Q1, les résidus passés de la même demi-heure

Chaque quantile est la prévision du modèle du mois plus le quantile empirique des résidus (consommation − prévision) de la même demi-heure de la journée. Les résidus utilisables à midi la veille sont ceux des jours publiés en consolidé, jusqu'à la fin du mois M − 3 où M est le mois de la décision, dans les 12 derniers mois civils disponibles, et calculés avec la météo prévue. Un jour n'est prévu que s'il dispose d'au moins 90 jours de résidus.

Le modèle est réentraîné chaque mois, et les résidus sont relus chaque jour :

| Jour livré | Décision | Modèle : appris jusqu'à | Résidus : jusqu'à |
|---|---|---|---|
| 1er du mois M | dernier jour de M − 1 | fin de M − 4 | fin de M − 4 |
| du 2 au dernier jour de M | dans le mois M | fin de M − 4 (modèle figé pour le mois) | fin de M − 3 |

Aucune fuite : chaque résidu est publié à midi la veille et vient d'un modèle qui n'avait pas vu son jour.

Q1 a été retenu parmi trois candidats selon la règle de l'entrée 21 : admissibilité par la couverture d'abord, puis choix par le pinball avec le test de bruit par blocs d'une semaine. Q3 (tranche de 3 h × type de jour × température) n'était pas admissible ; Q2 (tranche de 3 h × type de jour) faisait 2 % de pinball en plus que Q1, intervalle hors de 0. Le compteur des comparaisons faites sur la validation est de 13.

### Résultat sur la validation

Évaluation du 02/09/2024 au 31/08/2025, 17 464 demi-heures. Étiquettes : « météo prévue en partie rejouée » ; « période de validation déjà utilisée pour choisir A17 (10 comparaisons) » ; « fenêtre de calibration réduite avant juin 2025 ».

| Période | Couverture 80 % | Couverture 95 % | Largeur 95 % |
|---|---|---|---|
| Année d'évaluation | 77,5 % | 94,2 % | 6 624 MW |
| Automne | 84,9 % | 96,0 % | 6 917 MW |
| Hiver | **65,8 %** | **88,2 %** | 6 395 MW |
| Printemps | 83,6 % | 98,8 % | 6 892 MW |
| Été | 75,6 % | 93,8 % | 6 294 MW |

Pinball moyen : 288 MW, contre 831 MW pour la référence J-7 (−542 MW, intervalle [−676 ; −425]). Les intervalles sont environ trois fois plus étroits que ceux de la référence, pour une couverture voisine (78,4 % et 94,1 %). En hiver, ils sont trop étroits : les fenêtres de l'hiver 2024-25 ne contiennent aucun résidu d'hiver.

## Conséquences

- **Une prédiction écrite avant le test.** Sur le test, Q1 mélange les saisons dans chaque groupe : on s'attend à une couverture inférieure à la cible en hiver et supérieure en été. La couverture par saison du test sera lue au regard de cette prédiction. Le critère de l'ADR 0001 et Q1 ne changent pas.
- **Une méthode qui tient compte de la saison** sera une nouvelle comparaison, dans une version ultérieure. Elle ne pourra pas être jugée sur la validation, faute de résidus d'hiver dans les fenêtres de l'hiver 2024-25.
- **Les 15 et 16/03/2024 n'entrent dans aucune fenêtre du test.** Ces 96 demi-heures, les premières de l'archive de météo prévue, n'ont pas de température lissée sur 72 h, faute de calculs antérieurs au 14/03/2024 : leurs résidus sont gonflés de 7 à 8 GW. La première fenêtre de résidus du test commence le 01/06/2024. Un test automatique le vérifie. Sur la validation, à titre d'information et sans effet sur la décision, Q1 sans ces 96 demi-heures dans ses fenêtres couvre 76,45 % et 93,58 %, avec un intervalle à 95 % de 6 345 MW.
- **Limite constatée de la v0.1.** A17 figé a appris sur des consommations consolidées publiées après les premiers jours de validation (du 15/03 au 01/06/2024). Avec la procédure mensuelle, l'écart de MAPE sur mars-juin 2024 est de −0,012 point, intervalle [−0,153 ; +0,179] : pas d'effet mesurable.

## Points ouverts

- **Pour la v0.3 : le biais de la médiane.** q0,5 prévoit trop de 289 MW en moyenne sur l'évaluation, et la prévision ponctuelle mensuelle de 259 MW sur la même période : le biais vient surtout du modèle, et le décalage de la fenêtre de résidus n'y ajoute qu'environ 30 MW. La décision d'achat se prendra à un quantile : ce biais coûtera directement des euros.
- Les valeurs d'entrée manquantes laissées à LightGBM (ADR 0003).
- Le biais par temps froid et la cause de l'effet des années 2012-2016 (ADR 0003).
- Quatre demi-heures de validation n'ont pas de cible : celles du 27/10/2024 entre 2 h et 3 h, heure de Paris, qui existent deux fois le jour du passage à l'heure d'hiver et restent sans cible par construction (ADR 0002). Elles ne sont ni prévues ni jugées.
