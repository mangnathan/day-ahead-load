# Journal des choix de la v0.1

Chaque choix fait en regardant des résultats est noté ici, daté, avec sa règle écrite avant le calcul. Le compteur « comparaisons sur la validation » donne le nombre de modèles déjà évalués sur la validation au moment de l'entrée : plus il grandit, plus le résultat de validation du modèle retenu devient optimiste, et le test, ouvert une seule fois en v1.0, sert à mesurer cet effet. Les mesures faites à l'intérieur de l'entraînement ne touchent pas à la validation et sont comptées à part.

## 1. Modèle figé pour les comparaisons — 17/11/2026

Comparaisons sur la validation : 0. Mesures dans l'entraînement : 0.

- LightGBM 4.7.0, interface native (`lightgbm.train`, sans scikit-learn), objectif de régression, réglages par défaut : 100 itérations, taux d'apprentissage 0,1, 31 feuilles, profondeur libre, 20 lignes au moins par feuille, aucun sous-échantillonnage, aucune régularisation, perte quadratique.
- Reproductibilité : graine 20261117, `deterministic=True`, `force_row_wise=True`, un seul fil d'exécution.
- Variables : demi-heure du jour, jour de la semaine, mois, férié, lundi de Pentecôte, pont, Noël, température, nébulosité, vent, rayonnement, températures lissées sur 24 h et 72 h, niveau des 52 dernières semaines. Les indicateurs valent 0 ou 1 ; les variables de calendrier entières sont lues comme des nombres, réglage par défaut. Les valeurs manquantes sont laissées à LightGBM.
- Cible : la consommation, en MW. Les variantes du niveau (rapport consommation / niveau, sans niveau) sont mesurées plus tard, chacune comptée.

Ce modèle ne change pas d'une comparaison à l'autre. Code : `src/day_ahead_load/modelling.py`.

## 2. Début de l'entraînement de la régression linéaire — 17/11/2026

Comparaisons sur la validation : 0. Mesures dans l'entraînement : 0.

Le niveau des 52 semaines manque pour les jours livrés du 01/01/2012 au 01/03/2013. LightGBM gère ces valeurs manquantes, la régression linéaire non : son entraînement commence au 02/03/2013. Dans la comparaison des deux familles, LightGBM est lui aussi entraîné à partir du 02/03/2013, pour que les deux familles soient comparées sur les mêmes jours.

## 3. Convention de la demi-heure — règle écrite le 17/11/2026, avant le calcul

Comparaisons sur la validation : 0. Mesures dans l'entraînement : 0 avant cette entrée.

- Options : (t − 30 min, t], convention de l'ADR 0002, et (t − 15 min, t + 15 min]. L'interpolation des valeurs instantanées au milieu de l'intervalle, le rayonnement pondéré par la durée de recouvrement de chaque heure et la fin des fenêtres de lissage suivent l'option.
- Données : entraînement seulement (jours livrés jusqu'au 14/03/2024), météo ERA5, modèle de l'entrée 1.
- Validation croisée temporelle : chaque année de 2019 à 2023 est mise de côté à tour de rôle ; le modèle est entraîné sur tous les jours livrés antérieurs au 1er janvier de cette année, depuis le 01/01/2012. Critère : moyenne des cinq MAPE annuelles, sur les demi-heures où la cible existe.
- Décision : l'option à la plus faible MAPE moyenne. Si l'écart relatif entre les deux est inférieur à 1 %, on garde (t − 30 min, t], qui suit l'alignement mesuré en v0.0.

Résultat, le 17/11/2026 (`docs/v0.1-prevision-ponctuelle/data/convention-demi-heure.json`) :

| Année mise de côté | (t − 30, t] | (t − 15, t + 15] |
|---|---|---|
| 2019 | 2,490 % | 2,461 % |
| 2020 | 6,068 % | 6,116 % |
| 2021 | 3,210 % | 2,987 % |
| 2022 | 4,120 % | 4,168 % |
| 2023 | 6,049 % | 5,742 % |
| Moyenne | 4,387 % | 4,295 % |

Écart relatif −2,1 %, au-delà du seuil de 1 % : **(t − 15 min, t + 15 min] est retenue**, règle appliquée telle qu'écrite. Le signal est fragile : trois années sur cinq, l'écart moyen vient surtout de 2021 et de 2023. Les MAPE annuelles, de 2,5 % à 6,1 %, varient bien plus d'une année à l'autre que d'une option à l'autre : 2020 (confinements) et 2022-2023 (baisse de la consommation) pèsent sur le modèle quelle que soit la convention.

Mesures dans l'entraînement après cette entrée : 2. Comparaisons sur la validation : toujours 0.

Ce choix est définitif : on n'y revient pas, même si la comparaison des sources ou la suite le rendent gênant.

## 4. Source météo et durée de l'entraînement — règle écrite le 17/11/2026, avant le calcul

Comparaisons sur la validation : 0 avant cette entrée. Mesures dans l'entraînement : 2.

**Modèles.** Cinq modèles, tous avec le modèle de l'entrée 1 et la convention de l'entrée 3. Ils ne diffèrent que par la météo de l'entraînement et par le premier jour livré de l'entraînement (dernier jour : 14/03/2024) :

| Modèle | Météo de l'entraînement | Entraînement depuis |
|---|---|---|
| A12 | ERA5 | 01/01/2012 |
| A17 | ERA5 | 01/01/2017 |
| C12 | ERA5 corrigé de l'écart moyen IFS − ERA5 | 01/01/2012 |
| C17 | ERA5 corrigé de l'écart moyen IFS − ERA5 | 01/01/2017 |
| B17 | IFS historique (n'existe pas avant 2017) | 01/01/2017 |

La validation est la même pour les cinq : jours livrés du 15/03/2024 au 31/08/2025, météo des calculs ECMWF de 00 UTC vue à midi la veille, demi-heures où la cible existe. Critère : la MAPE. Chaque modèle est une entrée du journal, avec le total cumulé des comparaisons sur la validation : 5 à la fin de cette comparaison. Les familles de modèles et les variantes du niveau s'y ajouteront.

**Correction de C.** Pour chaque point, chaque mois civil et chaque heure UTC, l'écart moyen IFS − ERA5 est calculé sur les heures communes du 01/01/2017 au 14/03/2024, donc dans l'entraînement seulement. Il est ajouté aux valeurs ERA5 du point, de 2012 à 2024, avant le passage à l'indice national. Les valeurs corrigées sont ensuite ramenées dans leurs bornes physiques :

| Variable | Corrigée | Bornes |
|---|---|---|
| Température à 2 m | oui | aucune |
| Rayonnement | oui | ≥ 0 |
| Nébulosité | oui | entre 0 et 100 |
| Vent à 10 m | oui | ≥ 0 |
| Humidité relative | non | entre 0 et 100 si elle entre plus tard dans le modèle |

L'humidité n'est pas corrigée parce qu'elle n'entre pas dans le modèle de la v0.1 (ADR 0002) : la corriger ne changerait aucun des cinq modèles.

**Test de bruit.** Une différence de 1 % sur 17,5 mois peut venir du hasard des semaines. Pour chaque comparaison entre une option simple S et une option plus complexe K :

- on calcule l'erreur absolue en pourcentage de S et de K sur chaque demi-heure de la validation, puis la différence appariée MAPE(K) − MAPE(S) ;
- on calcule un intervalle de confiance à 95 % de cette différence par un bootstrap par blocs d'une semaine, pour respecter la dépendance dans le temps. Les blocs sont 7 jours livrés consécutifs à partir du 15/03/2024 : 76 blocs complets et un dernier bloc de 3 jours, du 29/08 au 31/08/2025. On fait 10 000 tirages avec remise de 77 blocs, avec la graine 20261117, et on prend les percentiles 2,5 et 97,5 ;
- on retient K seulement si elle fait mieux de plus de 1 % relatif, (MAPE(S) − MAPE(K)) / MAPE(S) > 1 %, **et** si l'intervalle exclut 0 (borne haute < 0). Sinon on garde S.

**Ordre de simplicité : A, puis C, puis B.** A n'a qu'une source et le plus long historique. C ajoute une étape de correction mais garde 2012-2016. B demande une seconde source et perd 5 ans.

**Décision 1 : la source, à durée égale (A17, C17, B17).** Option retenue au départ : A17. C17 lui est opposée avec la règle du test de bruit et la remplace si elle passe. B17 est ensuite opposée à l'option retenue, avec la même règle.

**Décision 2 : la durée, pour la source retenue.** Si la source est A ou C, 2012 est l'option de référence. 2017 la remplace seulement si elle passe la même règle : plus de 1 % relatif de mieux, et un intervalle qui exclut 0. Si la source est B, la durée est 2017, faute de données IFS avant.
