# ADR 0003 : modèle de prévision ponctuelle de la v0.1

- Statut : accepté le 24/11/2026, après relecture du rapport de la v0.1
- Date : 24 novembre 2026
- Version : v0.1

## Contexte

La v0.1 choisit la prévision ponctuelle de la consommation du lendemain, par demi-heure, en ne regardant que la validation (15/03/2024 → 31/08/2025). Le test reste fermé jusqu'à la v1.0 (ADR 0001). La table de données est fixée par l'ADR 0002.

Chaque choix a été fait par une règle écrite et commitée avant le calcul, dans le journal des choix (`docs/v0.1-prevision-ponctuelle/journal-des-choix.md`). Le journal compte les comparaisons faites sur la validation : plus il y en a, plus le score de validation du modèle retenu est optimiste. Ce compteur est de **10**.

Le test de bruit commun à toutes les comparaisons est défini en entrée 4. Une option plus complexe ne remplace la plus simple que si elle fait mieux de plus de 1 % relatif **et** si l'intervalle à 95 % de la différence appariée de MAPE, par bootstrap par blocs d'une semaine, exclut 0.

## Décision

Le modèle de la v0.1 est **A17** :

- LightGBM 4.7.0, interface native, réglages par défaut (100 itérations, taux d'apprentissage 0,1, 31 feuilles), graine 20261117, exécution déterministe sur un seul fil (entrée 1) ;
- 14 variables : demi-heure, jour de la semaine, mois, férié, lundi de Pentecôte, pont, Noël, température, nébulosité, vent, rayonnement, températures lissées sur 24 h et sur 72 h, niveau des 52 dernières semaines consolidées ;
- cible : la consommation en MW, avec le niveau en variable ;
- entraînement sur les jours livrés du 01/01/2017 au 14/03/2024, avec la météo ERA5 ;
- en validation, en test et en production, la météo vient des calculs ECMWF de 00 UTC vus à midi la veille, selon l'ADR 0002 ;
- convention de la demi-heure : (t − 15 min, t + 15 min].

Code : `src/day_ahead_load/modelling.py`. Chaque script de comparaison et le bilan vérifient qu'ils retrouvent la MAPE de validation de 2,617 %.

## Chaîne des décisions

| Décision | Entrée du journal | Options | Retenu | Mesure |
|---|---|---|---|---|
| Convention de la demi-heure | 3 | (t − 30, t] ou (t − 15, t + 15] | (t − 15, t + 15] | −2,1 % en validation croisée 2019-2023, dans l'entraînement ; signal fragile |
| Source météo de l'entraînement | 4, 10 | ERA5, IFS historique, ERA5 corrigé | ERA5 | ERA5 corrigé : +1,6 %, mais intervalle [−0,195 ; +0,116] ; IFS : +0,5 % |
| Durée de l'entraînement | 4, 10 | depuis 2012 ou depuis 2017 | 2017 | +5,8 %, intervalle [−0,269 ; −0,052] |
| Famille et niveau | 12, 18 | linéaire ou LightGBM × sans niveau, niveau en variable, rapport | LightGBM, niveau en variable | +28,3 % face à la régression linéaire avec niveau, intervalle [−1,383 ; −0,679] |

L'entrée 11 remplace l'entrée 2 : les deux familles partent du 01/01/2017.

## Résultats sur la validation (bilan, entrées 19 et 20)

Mesures faites sans rien changer au modèle, sur 25 607 demi-heures communes au modèle et aux références de la v0.0. Le détail est dans `docs/v0.1-prevision-ponctuelle/data/bilan-v0-1.json`.

- **MAPE : 2,614 %.**
- **Rapport au naïf J-7 : 0,433**, intervalle [0,375 ; 0,503]. C'est une indication sur la validation, pas le critère. Ce chiffre est probablement optimiste : 10 comparaisons ont été faites sur cette période, la météo prévue est rejouée (cycle 49R1), et J-7 est lui-même optimiste.
- Le modèle bat tous les naïfs. Il ne se distingue pas de la prévision J-1 brute de RTE (2,580 %, différence +0,034 point, intervalle [−0,238 ; +0,309]), qui est publiée après la décision. Il reste derrière les versions corrigées de RTE, de +0,70 à +0,89 point.
- **Météo parfaite** (ERA5 en entrée, impossible en pratique) : 2,583 %, soit −0,032 point, intervalle [−0,167 ; +0,088]. L'erreur vient surtout du modèle, pas de la prévision météo.
- **Biais** : environ +210 MW en moyenne. Il atteint +0,67 à +0,85 GW sous 10 °C, et les ponts et la période de Noël sont surestimés.

## Conséquences

- La v0.2 construit l'incertitude autour de A17, sans le modifier. Le bilan indique que l'erreur à couvrir vient surtout du modèle : la météo prévue y pèse peu à J-1.
- Toute modification de A17 sera une comparaison de plus sur la validation, comptée dans le journal.
- Le test reste fermé. Le rapport à J-7 sur la validation ne préjuge pas du critère, qui se juge sur le test en v1.0.

## Points ouverts

- Les 15 et 16/03/2024, les deux pires jours de la validation, sont les 96 demi-heures où la température lissée sur 72 h manque, parce que le cache des calculs ECMWF commence trop tard. Faut-il interdire les valeurs d'entrée manquantes dans LightGBM, par le calcul de secours ou par un refus de prévoir ?
- D'où vient le biais par temps froid, dont le signe et l'ordre de grandeur rejoignent le risque de 720 MW du prémortem, alors que la météo parfaite ne change presque rien ?
- Pourquoi les années 2012-2016 dégradent-elles la prévision de 2024-2025 (entrée 11) ?
- Les vacances scolaires ne sont pas dans le modèle (ADR 0002). Elles sont une piste plausible pour les 2 et 3/01/2025, mais pas une cause établie.
