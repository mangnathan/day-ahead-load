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

## 5. Modèle A12 — 17/11/2026

ERA5, entraînement depuis le 01/01/2012 (213 888 demi-heures). MAPE de validation : 2,777 %. **Comparaisons sur la validation : 1.**

## 6. Modèle A17 — 17/11/2026

ERA5, entraînement depuis le 01/01/2017 (126 212 demi-heures). MAPE de validation : 2,617 %. **Comparaisons sur la validation : 2.**

## 7. Modèle C12 — 17/11/2026

ERA5 corrigé, entraînement depuis le 01/01/2012. MAPE de validation : 2,588 %. **Comparaisons sur la validation : 3.**

## 8. Modèle C17 — 17/11/2026

ERA5 corrigé, entraînement depuis le 01/01/2017. MAPE de validation : 2,575 %. **Comparaisons sur la validation : 4.**

## 9. Modèle B17 — 17/11/2026

IFS historique, entraînement depuis le 01/01/2017. MAPE de validation : 2,605 %. **Comparaisons sur la validation : 5.**

## 10. Décision : source et durée — 17/11/2026

Comparaisons sur la validation : 5. Règle de l'entrée 4 appliquée telle qu'écrite, sur 25 674 demi-heures de validation et 77 blocs d'une semaine (`docs/v0.1-prevision-ponctuelle/data/comparaison-sources.json`).

| Étape | Simple | Complexe | MAPE simple | MAPE complexe | Gain relatif | IC 95 % de la différence (points) | Complexe retenue |
|---|---|---|---|---|---|---|---|
| Source | A17 | C17 | 2,617 % | 2,575 % | 1,6 % | [−0,195 ; +0,116] | non : l'intervalle contient 0 |
| Source | A17 | B17 | 2,617 % | 2,605 % | 0,5 % | [−0,150 ; +0,123] | non : gain < 1 % |
| Durée | A12 | A17 | 2,777 % | 2,617 % | 5,8 % | [−0,269 ; −0,052] | oui |

**Retenu : A17, ERA5 à l'entraînement, à partir du 01/01/2017.**

- Source : C17 fait mieux que A17 de 1,6 %, mais l'intervalle va de −0,19 à +0,12 point. Ce gain est du même ordre que le hasard des semaines, et le test de bruit l'écarte. Sans ce test, le seuil de 1 % seul aurait retenu C. B ne passe même pas le seuil.
- Durée : l'entraînement depuis 2017 fait mieux, et l'intervalle exclut 0. Les années 2012-2016 dégradent la prévision de 2024-2025 avec ce modèle et ces variables. Cela peut venir d'un changement des usages de l'électricité, ou de l'absence du niveau des 52 semaines avant mars 2013 ; cette mesure ne permet pas de séparer les deux.
- Observation hors règle : à durée 2012, la correction C fait mieux qu'A de 6,8 % (2,588 % contre 2,777 %), alors qu'à durée 2017 l'écart n'est que de 1,6 % et reste dans le bruit. Cette comparaison ne faisait pas partie de la règle. Elle ne change rien à la décision.
- Correction de C : la nébulosité a été ramenée dans ses bornes pour 19,4 % des heures. Les valeurs ERA5 de 0 ou de 100 %, fréquentes, sont poussées au-delà par un écart moyen non nul. Pour C, cette variable est donc un mélange de correction et de troncature. Les autres variables sont peu touchées : rayonnement 1,3 %, vent 0,03 %, température 0 %.

Point ouvert, à trancher avant la comparaison des familles : l'entrée 2 fait commencer l'entraînement de la régression linéaire et de LightGBM au 02/03/2013. Avec une durée retenue au 01/01/2017, le niveau existe sur toute la période, et la contrainte de l'entrée 2 ne joue plus.

Comparaisons sur la validation après cette entrée : 5. Mesures dans l'entraînement : 2.

## 11. Remplace l'entrée 2 : début de l'entraînement des deux familles — 17/11/2026

Comparaisons sur la validation : 5. Mesures dans l'entraînement : 2.

Remplace l'entrée 2 : les deux familles partent du 01/01/2017, durée retenue en entrée 10. La contrainte du niveau avant le 02/03/2013 ne joue plus. L'entrée 2 reste écrite telle quelle : le journal ne fait que s'allonger.

Point ouvert, non tranché : pourquoi les années 2012-2016 dégradent la prévision de 2024-2025 (entrée 10). Les variantes du niveau touchent au même problème de changement de niveau et pourront apporter un élément de réponse.

## 12. Familles de modèles et variantes du niveau — règle écrite le 17/11/2026, avant le calcul

Comparaisons sur la validation : 5 avant cette entrée. Mesures dans l'entraînement : 2.

**Cadre commun.** Météo ERA5 à l'entraînement, jours livrés du 01/01/2017 au 14/03/2024 (entrées 10 et 11), convention de l'entrée 3. La validation et le test de bruit sont ceux de l'entrée 4, avec les mêmes réglages : différence appariée de MAPE, bootstrap par blocs d'une semaine, 10 000 tirages, graine 20261117. Un modèle plus complexe ne remplace le modèle retenu que s'il fait mieux de plus de 1 % relatif **et** si l'intervalle à 95 % de la différence exclut 0.

**Grille complète, pas d'étapes.** Choisir la famille avec le niveau en variable, puis le niveau pour la famille retenue, laisserait un trou : si la régression linéaire gagnait la première étape, LightGBM avec le rapport ne serait jamais essayé. C'est pourtant la variante qui doit corriger le défaut de LightGBM, qui ne sait pas prolonger une tendance au-delà des valeurs de l'entraînement. Les six combinaisons sont donc évaluées.

**Ordre total de simplicité.** La famille compte avant le niveau :

| Rang | Modèle | Famille | Niveau |
|---|---|---|---|
| 1 | L-sans | régression linéaire | sans niveau |
| 2 | L-niveau | régression linéaire | niveau en variable |
| 3 | L-rapport | régression linéaire | rapport |
| 4 | G-sans | LightGBM | sans niveau |
| 5 | G-niveau | LightGBM | niveau en variable : c'est A17 (entrée 6) |
| 6 | G-rapport | LightGBM | rapport |

- Famille : la régression a un nombre fixe de coefficients, qui se lisent directement, et aucun réglage d'apprentissage. LightGBM apprend des interactions et des seuils qu'on ne lui donne pas.
- Niveau : sans niveau, le modèle a une entrée de moins. Le niveau en variable ajoute une entrée. Le rapport change la cible et demande de remultiplier la prévision.

**Règle sur la grille.** On part du modèle de rang 1. Chaque modèle suivant, dans l'ordre des rangs, est comparé au modèle retenu jusque-là, avec la règle de l'entrée 4. S'il la passe, il devient le modèle retenu. Le dernier modèle retenu est le modèle de la v0.1.

**Compteur connu d'avance.** Cinq modèles nouveaux : L-sans (comparaison 6), L-niveau (7), L-rapport (8), G-sans (9), G-rapport (10). G-niveau est A17, déjà évalué en entrée 6, et n'est pas recompté. **Total cumulé à la fin : 10 comparaisons sur la validation.** Chaque modèle nouveau aura son entrée, avec le total cumulé.

**Variantes du niveau.**

- Sans niveau : l'entrée `niveau_52_semaines` est retirée, la cible reste la consommation.
- Niveau en variable : le niveau est une entrée, la cible est la consommation.
- Rapport : la cible devient consommation / niveau, et le niveau est retiré des entrées. La prévision est le rapport prévu multiplié par le niveau du jour livré, connu à midi la veille. La MAPE est toujours calculée sur la consommation.

**Régression linéaire.** Moindres carrés ordinaires (`numpy.linalg.lstsq`, sans scikit-learn), avec une constante et sans régularisation. Les interactions entre la température et l'heure suivent la référence linéaire classique des prévisions de consommation, le « vanilla benchmark » de Tao Hong dans la compétition GEFCom2012, qui croise la température avec l'heure et avec le mois. Sans elles, LightGBM gagnerait d'avance et la comparaison n'apprendrait rien : l'effet du chauffage n'est pas le même à 3 h du matin et à 19 h. Entrées :

- profil de la journée : une indicatrice par couple (demi-heure, type de jour), avec trois types de jour : ouvré, samedi, dimanche ou férié. Le lundi de Pentecôte reste un jour ouvré avec son indicatrice propre, comme pour LightGBM ;
- jour de la semaine, mois, férié, lundi de Pentecôte, pont, Noël, en indicatrices ;
- degrés de chauffage max(15 − T, 0) et de climatisation max(T − 18, 0). Le seuil de 15 °C vient de la v0.0, où la sensibilité de 2 313 à 2 345 MW par degré était mesurée sous 15 °C. Le seuil de 18 °C est fixé a priori, sans mesure : c'est un réglage de la famille linéaire, fixé ici pour ne pas être ajusté sur la validation ;
- pour la température de la demi-heure, les degrés de chauffage et de climatisation croisés avec 8 tranches horaires de 3 h (heure de Paris : 0 h-3 h, 3 h-6 h, …, 21 h-24 h), et les degrés de chauffage croisés avec le mois ;
- pour les températures lissées sur 24 h et sur 72 h, les degrés de chauffage et de climatisation, sans interaction ;
- nébulosité, vent et rayonnement, bruts ;
- niveau des 52 semaines, brut, selon la variante.

Colinéarité : les indicatrices du jour de la semaine et du férié sont en partie redondantes avec les couples (demi-heure, type de jour), et les degrés croisés avec les tranches et avec le mois se recouvrent. Une modalité de référence est retirée par groupe : le couple (00 h 00, ouvré), le lundi et janvier pour les indicatrices, et janvier pour le chauffage croisé avec le mois. L'effet moyen du chauffage et de la climatisation est déjà porté par les 8 tranches horaires, qui restent toutes. Les redondances qui restent sont laissées à `lstsq`, qui reste stable quand la matrice n'est pas de plein rang : les prévisions ne changent pas, et les coefficients restent interprétables. Le nombre de colonnes et le rang de la matrice d'entraînement sont écrits dans le résultat.

Une entrée manquante est remplacée par sa moyenne sur l'entraînement. Cela concerne la température lissée sur 72 h de 96 demi-heures de validation (15 et 16/03/2024). L'entraînement depuis 2017 n'a aucune entrée manquante (entrée 6).

## 13. Modèle L-sans — 20/11/2026

Régression linéaire sans niveau, ERA5 depuis le 01/01/2017 (126 212 demi-heures). 199 colonnes, rang 199. MAPE de validation : 4,176 %. **Comparaisons sur la validation : 6.**

## 14. Modèle L-niveau — 20/11/2026

Régression linéaire avec le niveau en variable. 200 colonnes, rang 200. MAPE de validation : 3,650 %. **Comparaisons sur la validation : 7.**

## 15. Modèle L-rapport — 20/11/2026

Régression linéaire sur le rapport consommation / niveau. 199 colonnes, rang 199. MAPE de validation : 3,846 %. **Comparaisons sur la validation : 8.**

## 16. Modèle G-sans — 20/11/2026

LightGBM sans niveau. MAPE de validation : 4,348 %. **Comparaisons sur la validation : 9.**

## 17. Modèle G-rapport — 20/11/2026

LightGBM sur le rapport consommation / niveau. MAPE de validation : 3,519 %. **Comparaisons sur la validation : 10.**

G-niveau est A17 (entrée 6) et n'est pas recompté. Le script retrouve exactement sa MAPE de 2,617 %.

## 18. Décision : famille et niveau — 20/11/2026

Comparaisons sur la validation : 10, comme annoncé en entrée 12. Règle de l'entrée 12 appliquée telle qu'écrite, sur 25 674 demi-heures de validation (`docs/v0.1-prevision-ponctuelle/data/comparaison-familles.json`).

| Retenu jusque-là | Candidat | MAPE retenu | MAPE candidat | Gain relatif | IC 95 % de la différence (points) | Candidat retenu |
|---|---|---|---|---|---|---|
| L-sans | L-niveau | 4,176 % | 3,650 % | 12,6 % | [−1,031 ; −0,017] | oui |
| L-niveau | L-rapport | 3,650 % | 3,846 % | −5,4 % | [+0,034 ; +0,348] | non : moins bon |
| L-niveau | G-sans | 3,650 % | 4,348 % | −19,1 % | [+0,088 ; +1,306] | non : moins bon |
| L-niveau | G-niveau | 3,650 % | 2,617 % | 28,3 % | [−1,383 ; −0,679] | oui |
| G-niveau | G-rapport | 2,617 % | 3,519 % | −34,5 % | [+0,591 ; +1,227] | non : moins bon |

**Retenu : G-niveau, LightGBM avec le niveau des 52 semaines en variable, ERA5 à l'entraînement depuis le 01/01/2017.** C'est le modèle A17 : le modèle figé de l'entrée 1, sans changement.

- Rang : la matrice de la régression est de plein rang dans les trois variantes. La redondance attendue entre le jour de la semaine, le férié et le type de jour ne se produit pas, parce que des fériés tombent un dimanche ou un samedi.
- Le rapport est moins bon que le niveau en variable dans les deux familles, nettement pour LightGBM (−34,5 %, intervalle loin de 0). Il ne corrige donc pas, sur cette validation, le défaut d'extrapolation qu'il visait. Cette mesure ne dit pas pourquoi.
- Observations hors règle : le niveau en variable améliore LightGBM de 39,8 % par rapport à LightGBM sans niveau (2,617 % contre 4,348 %). Sans niveau, LightGBM est moins bon que la régression linéaire sans niveau. Ces deux comparaisons ne faisaient pas partie de la règle. Elles ne changent rien à la décision.
- Point ouvert de l'entrée 11 (pourquoi 2012-2016 dégradent la prévision) : le niveau pèse lourd dans la qualité du modèle, ce qui va dans le sens d'un problème de changement de niveau. La mesure ne tranche pas : A12 avait le niveau à partir de mars 2013. La question reste ouverte.

Comparaisons sur la validation après cette entrée : 10. Mesures dans l'entraînement : 2.

## 19. Bilan de la v0.1 — règle écrite le 24/11/2026, avant le calcul

Comparaisons sur la validation : 10. Mesures dans l'entraînement : 2.

**Règle de fond.** Le bilan mesure, il ne choisit rien. Aucune de ses mesures ne modifie le modèle retenu (A17, entrée 18). Une piste qu'il fait apparaître va dans les points ouverts, et toute modification future du modèle sera une comparaison comptée. Le compteur reste à 10.

**Échantillon commun.** Jours livrés du 15/03/2024 au 31/08/2025. Ce sont les demi-heures où la cible, la prévision du modèle et les dix références de la v0.0 existent toutes. Les références sont celles du module `references` de la v0.0, recalculées sur cette période seule, sur leur grille en heure murale de Paris. RTE est alignée sur la moyenne f(t − 15), f(t), l'alignement principal de la v0.0. Les demi-heures du modèle y sont rattachées par leur heure de Paris. Toutes les mesures du bilan portent sur cet échantillon, sauf mention contraire. Biais : prévision − consommation, positif quand le modèle prévoit trop.

**1. Position face aux références.**

- MAPE du modèle et de chaque référence. Pour chaque référence, la différence appariée MAPE(modèle) − MAPE(référence), avec un intervalle à 95 % par bootstrap par blocs d'une semaine, avec les réglages de l'entrée 4 (10 000 tirages, graine 20261117).
- Rapport MAPE(modèle) / MAPE(naïf J-7), avec un intervalle à 95 % : à chaque tirage des mêmes blocs, rapport des deux MAPE de l'échantillon tiré. Il est placé face aux seuils de l'ADR 0001 (0,5 pour la réussite, 0,75 pour l'échec) avec l'étiquette **« indication sur la validation, pas le critère »**. Ce chiffre est probablement optimiste, pour trois raisons : 10 comparaisons ont été faites sur cette période ; la météo prévue est rejouée (cycle 49R1) ; J-7 lui-même est étiqueté « optimiste ».
- Les références RTE brute et corrigées sont étiquetées « avantagées » : elles sont publiées après la décision. Seules des erreurs agrégées sont publiées, jamais les courbes.

**2. Part de l'erreur qui vient de la météo prévue.** A17 est entraîné à l'identique. Il prévoit ensuite la validation avec la météo observée (ERA5) en entrée, à la place des calculs ECMWF de 00 UTC, y compris dans les lissages. On publie sa MAPE et la différence appariée avec A17, avec son intervalle. Étiquette : **« borne informative, météo parfaite, impossible en pratique »**. L'écart entre les deux MAPE mesure ce que coûte l'erreur de prévision météo.

**3. Où le modèle se trompe.** MAPE, biais en MW et biais en % :

- par trimestre civil ;
- par saison météorologique : hiver (décembre à février), printemps (mars à mai), été (juin à août), automne (septembre à novembre) ;
- par tranche de température : < 0 °C, 0-5, 5-10, 10-15, > 15 °C. C'est le contrôle direct du risque de 720 MW du prémortem, qui pèse surtout par temps froid. La température est celle de l'indice national ERA5 à la demi-heure : les tranches décrivent le temps qu'il a fait, indépendamment de l'erreur de la prévision météo ;
- par tranche de 3 h (heure de Paris), par type de jour (ouvré, samedi, dimanche ou férié), pour les ponts et pour la période de Noël.

**4. Les 10 pires jours.** Ce sont les 10 jours livrés de plus forte MAPE journalière, publiés avec leur date, leur MAPE et leur biais. Une explication n'est écrite que si elle se vérifie dans nos données :

- calendrier : férié, lundi de Pentecôte, pont, Noël, changement d'heure ;
- froid ou chaleur marqués : température moyenne du jour (indice ERA5) à plus de 5 °C sous ou au-dessus de la moyenne de son mois civil sur l'entraînement 2017-2024 ;
- erreur de la météo prévue : écart moyen du jour de plus de 2 °C entre la température vue à midi la veille et l'indice ERA5.

Ce sont des constats, pas des causes démontrées. Sans aucun de ces constats : **« cause non établie »**.

**5. Importance des variables.**

- Gain de LightGBM sur l'entraînement, publié avec sa réserve : il favorise les variables qui offrent beaucoup de coupures possibles.
- Importance par permutation sur la validation : hausse de la MAPE quand une variable est mélangée entre les demi-heures. On fait 5 permutations par variable, avec la graine 20261117, et on publie leur moyenne. Réserve : mélanger une variable fortement liée à d'autres, comme la température et ses lissages, sous-estime son importance, puisque les autres portent encore l'information.

**6. Calcul de secours.** On rappelle son nombre d'utilisations sur la validation : 0 (ADR 0002).

## 20. Résultats du bilan de la v0.1 — 24/11/2026

Comparaisons sur la validation : 10, inchangé. Règle de l'entrée 19 appliquée telle qu'écrite ; le modèle n'a pas changé. Une seconde exécution redonne le même fichier (`docs/v0.1-prevision-ponctuelle/data/bilan-v0-1.json`).

**Échantillon commun** : 25 607 demi-heures sur 25 674 avec cible. MAPE du modèle : 2,614 %.

**Rapport à J-7 — indication sur la validation, pas le critère** : 0,433, intervalle à 95 % [0,375 ; 0,503], face aux seuils de 0,5 (réussite) et de 0,75 (échec). Ce chiffre est probablement optimiste : 10 comparaisons ont été faites sur cette période, la météo prévue est rejouée (cycle 49R1), et J-7 lui-même est étiqueté « optimiste ».

**Références** (modèle − référence, en points, intervalle à 95 %) :

| Référence | Catégorie | MAPE | Différence | Intervalle |
|---|---|---|---|---|
| Naïf J-7 | optimiste | 6,036 % | −3,422 | [−4,303 ; −2,594] |
| Naïf J-2 | optimiste | 8,433 % | −5,819 | [−6,253 ; −5,381] |
| Veille le matin, J-2 l'après-midi | optimiste | 6,746 % | −4,131 | [−4,485 ; −3,768] |
| Moyenne des 4 mêmes jours | optimiste | 6,464 % | −3,850 | [−4,784 ; −2,968] |
| Dernier même jour publié | réaliste | 18,757 % | −16,142 | [−19,013 ; −13,359] |
| Même jour 52 semaines avant | réaliste | 6,343 % | −3,728 | [−4,597 ; −2,893] |
| RTE J-1 brute | avantagée | 2,580 % | +0,034 | [−0,238 ; +0,309] |
| RTE corrigée, retard réel | avantagée | 1,918 % | +0,696 | [+0,450 ; +0,959] |
| RTE corrigée, même mois l'an dernier | avantagée | 1,720 % | +0,894 | [+0,679 ; +1,126] |
| RTE corrigée, 4 semaines idéales | borne | 1,579 % | +1,035 | [+0,825 ; +1,265] |

Le modèle est indiscernable de la prévision brute de RTE, publiée après la décision, et reste derrière les versions corrigées.

**Météo parfaite — borne informative, météo parfaite, impossible en pratique** : 2,583 % avec ERA5 en entrée, contre 2,614 % avec la météo prévue, soit −0,032 point, intervalle [−0,167 ; +0,088]. L'erreur de la prévision météo à J-1 ne coûte presque rien ici : l'erreur vient surtout du modèle.

**Découpages** (biais : prévision − consommation) :

- biais global d'environ +210 MW ; par saison, de −200 MW (été) à +536 MW (hiver) ;
- par température de l'indice ERA5 : +845 MW sous 0 °C (214 demi-heures), +764 MW de 0 à 5 °C, +673 MW de 5 à 10 °C, +455 MW de 10 à 15 °C, −177 MW au-dessus de 15 °C. C'est le signe et l'ordre de grandeur du risque de 720 MW du prémortem. La mesure de la météo parfaite montre pourtant que la source météo pèse peu : la cause n'est pas établie ;
- par tranche de 3 h : la pire est 6 h-9 h (MAPE 3,336 %, +940 MW), puis 3 h-6 h (3,002 %) ; biais négatif de 12 h à 15 h (−455 MW) ;
- par type de jour : 2,453 % en jour ouvré, 2,765 % le samedi, 3,137 % le dimanche ou un jour férié ; ponts 3,146 % (+897 MW), période de Noël 3,547 % (+1 508 MW) ;
- par trimestre : de 2,246 % à 2,873 %, sauf 2024-T1 (4,455 %, 811 demi-heures).

**Les 10 pires jours** : 16/03/2024 (17,7 %), 15/03/2024 (14,2 %), 02/01/2025 (9,6 %), 09/04/2024 (9,1 %), 15/09/2024 (8,9 %, froid marqué), 25/12/2024 (8,6 %, férié et période de Noël), 14/09/2024 (7,6 %, froid marqué), 06/10/2024 (7,5 %), 08/04/2024 (7,3 %), 03/01/2025 (7,2 %). Sans autre mention : cause non établie.

**Importance des variables.** Par permutation, la demi-heure arrive en tête (+8,65 points), puis la température lissée sur 72 h (+6,45), le jour de la semaine (+3,90), la température lissée sur 24 h (+2,38) et le mois (+1,36). Par gain, la température lissée sur 72 h compte pour 53 %. Le calcul de secours n'a servi à aucune demi-heure de validation.

**Observations hors règle**, constatées après le calcul et qui ne changent rien au modèle :

- Les deux pires jours, les 15 et 16/03/2024, sont exactement les 96 demi-heures de validation où la température lissée sur 72 h manque (entrée 12). Le cache des calculs ECMWF commence trop tard pour couvrir leurs 72 heures. LightGBM envoie ces valeurs manquantes dans une branche qui surestime de 7 à 8 GW, alors que ce lissage est sa variable la plus forte. En production, le calcul de secours aurait pris le relais. C'est un artefact du début de la validation, qui gonfle la MAPE de validation (environ 0,06 point, par simple calcul sur les chiffres publiés) et le trimestre 2024-T1. La règle des constats ne prévoyait pas ce cas : la table des pires jours garde « cause non établie ».
- Le niveau n'apporte que +0,14 point par permutation, alors que la grille de l'entrée 18 montrait 39,8 % d'écart entre LightGBM avec et sans niveau. Ce n'est pas une contradiction. La permutation mesure ce qu'une variable apporte à l'intérieur de la validation, où le niveau varie peu. Son rôle est de décaler toute la période par rapport à l'entraînement, ce que la permutation ne voit pas.

**Points ouverts** ajoutés :

- Faut-il interdire les valeurs d'entrée manquantes dans LightGBM (calcul de secours ou refus de prévoir), plutôt que de les laisser à une branche apprise sur d'autres cas ?
- D'où vient le biais par temps froid (+0,67 à +0,85 GW sous 10 °C) ?

Toujours ouvert depuis l'entrée 11 : pourquoi les années 2012-2016 dégradent la prévision de 2024-2025.

Comparaisons sur la validation après cette entrée : 10. Mesures dans l'entraînement : 2.
