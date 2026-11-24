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

## 21. Incertitude de la v0.2 — règle écrite le 24/11/2026, avant le calcul

Comparaisons sur la validation : 10 avant cette entrée. Mesures dans l'entraînement : 2.

### Limite constatée de la v0.1 : un avantage de date

A17 a été entraîné une fois, sur les jours livrés jusqu'au 14/03/2024. Avec la règle M+3, les consommations consolidées de janvier, février et mars 2024 ne sont publiées que le 1er avril, le 1er mai et le 1er juin 2024. Pour les jours de validation du 15/03 au 01/06/2024, A17 a donc appris sur des données qu'un fournisseur n'aurait pas encore eues à midi la veille. Les variables, niveau compris, respectent toutes la règle de midi. Le bilan de la v0.1 n'est pas réécrit. Le tag v0.1 étant posé, cette limite est mentionnée dans le rapport de la v0.2 et dans le CHANGELOG. Elle est mesurée plus bas : écart de MAPE entre A17 figé et la procédure mensuelle, du 15/03 au 30/06/2024.

### Réentraînement mensuel appliqué à la validation

La procédure de l'ADR 0001, prévue pour le test, est appliquée dès maintenant à la validation. Ce n'est pas une comparaison : aucun choix n'en dépend.

- **Dix-huit modèles**, de mars 2024 à août 2025. Le modèle du mois M prévoit tous les jours de validation du mois M.
- **Fin de l'entraînement : dernier jour du mois M − 4.** Le modèle du mois M doit exister à midi la veille du 1er de M, c'est-à-dire le dernier jour de M − 1. À cette heure, le consolidé publié s'arrête à la fin de M − 4 : le mois M − 3 ne paraît que le 1er de M. Un test automatique échoue si une ligne d'entraînement d'un modèle est datée après la fin de M − 4, donc a fortiori après la fin de M − 3.
- **Début de l'entraînement** : 01/01/2017, comme A17 (entrées 10 et 11).
- **Configuration figée** : les réglages de l'entrée 1 (LightGBM par défaut, objectif de régression), 100 itérations comme A17, qui n'a pas d'arrêt anticipé, la graine 20261117 pour chaque entraînement, une exécution déterministe sur un seul fil, et les 14 variables d'A17.
- **Météo** : ERA5 pour toutes les lignes d'entraînement, y compris les jours de validation une fois entrés dans l'entraînement. ERA5 paraît avec environ 5 jours de retard : il est disponible bien avant la fin de M − 4. Les jours prévus gardent la météo vue à midi la veille (ADR 0002).
- **Niveau** : la moyenne des 52 semaines de consolidé respecte déjà la règle M+3 pour chaque jour livré, ce que vérifie un test de la table. Pour la ligne d'entraînement la plus récente d'un modèle, le niveau ne lit donc que du consolidé publié avant cette ligne, donc avant la fin de M − 4.
- **On garde la procédure quel que soit le résultat.** Si sa MAPE de validation est moins bonne que celle d'A17 figé, la procédure ne change pas, et A17 figé ne revient pas. Les deux MAPE sont publiées côte à côte, pour information : sur toute la validation, sur l'évaluation, et du 15/03 au 30/06/2024 pour mesurer l'avantage de date.
- **Traçabilité** : pour chaque modèle, le mois, la date de la dernière ligne d'entraînement, le nombre de lignes et l'empreinte sha256 de la configuration. Le tableau des 18 modèles est publié avec les résultats.

### Résidus et fenêtre de calibration

- **Résidu** : consommation − prévision du modèle de son mois, avec la météo prévue. Chaque résidu est hors échantillon par construction : le jour n'était pas dans l'entraînement de son modèle.
- **Disponibilité** : à midi la veille d'un jour livré D, on dispose des résidus des jours publiés en consolidé, c'est-à-dire jusqu'à la fin du mois M − 3, où M est le mois de la décision (la veille de D). On garde ceux des 12 derniers mois civils disponibles. Il n'y a que des résidus calculés avec la météo prévue, donc postérieurs au 15/03/2024, et aucun complément par ERA5.
- **Jours jugés** : seuls les jours qui disposent d'au moins 90 jours de résidus. Le 01/09/2024 se décide le 31/08, avec les résidus du 15/03 au 31/05/2024, soit 78 jours : il n'est pas jugé. Les jours suivants se décident en septembre, avec 108 jours. **Période d'évaluation : du 02/09/2024 au 31/08/2025.**
- **Fenêtre réduite** : moins de 12 mois de résidus pour les décisions antérieures à juin 2025. Étiquette « fenêtre de calibration réduite avant juin 2025 ».
- **Hiver sans résidus d'hiver** : les jours de décembre 2024 à février 2025 sont calibrés sur des résidus de mars à novembre 2024 au plus, sans aucun mois d'hiver. Risque connu : couverture probablement basse en hiver sur la validation. Ce défaut n'existe pas sur le test, dont la fenêtre contient l'hiver 2024-25. On ne corrige rien. La couverture est publiée par saison, et aussi sur l'évaluation hors hiver 2024-25, à titre d'information seulement. L'admissibilité reste jugée sur les 12 mois entiers.

### Candidats

Chaque quantile est la prévision du modèle du mois plus le quantile empirique (interpolation linéaire de `numpy.quantile`) des résidus du groupe de la demi-heure prévue, aux niveaux 0,025, 0,1, 0,5, 0,9 et 0,975. Intervalle à 80 % : de q0,1 à q0,9. Intervalle à 95 % : de q0,025 à q0,975.

| Ordre | Candidat | Groupes de résidus |
|---|---|---|
| 1 | Q1 | demi-heure de la journée (48 groupes) |
| 2 | Q2 | tranche de 3 h (heure de Paris) × type de jour (24 groupes) |
| 3 | Q3 | Q2 × température prévue de la demi-heure, sous 10 °C ou à 10 °C et plus (48 groupes) |

- **Types de jour** : ouvré ; samedi ; dimanche, jour férié, pont ou période du 24/12 au 01/01. Le lundi de Pentecôte reste un jour ouvré, comme dans le modèle.
- **Repli de Q3** : un groupe qui compte moins de 100 résidus à la date de calibration prend les résidus de son groupe Q2. La règle s'applique à chaque date de calibration. Le nombre de groupes et de demi-heures concernés est publié.
- **La médiane n'est pas la prévision ponctuelle.** La prévision ponctuelle reste celle du modèle. q0,5 est une sortie à part : son biais et sa MAPE sont publiés à titre d'information, sans comparaison à A17 et sans effet sur aucun choix.

### Référence

C'est la référence de l'ADR 0001 : J-7, plus les quantiles empiriques des erreurs passées de J-7 par demi-heure de la journée, sur les 12 derniers mois de consolidé disponibles à midi la veille, aux mêmes cinq niveaux, sur les mêmes demi-heures jugées. Elle n'a pas besoin de la météo prévue et dispose donc d'emblée de 12 mois d'erreurs, ce qui l'avantage au début de l'évaluation. Elle n'est pas une option et n'est pas comptée.

### Règle de décision

1. **Admissibilité** : sur toute la période d'évaluation, l'intervalle à 80 % couvre entre 75 et 85 % des demi-heures, **et** l'intervalle à 95 % entre 92 et 98 %, bornes des intervalles comprises. Un candidat non admissible n'est jamais retenu, même avec un meilleur pinball.
2. **Choix** : le premier candidat admissible dans l'ordre Q1, Q2, Q3 est retenu au départ. Chaque candidat admissible suivant le remplace seulement s'il fait mieux de plus de 1 % relatif sur le pinball moyen des cinq niveaux **et** si l'intervalle à 95 % de la différence appariée exclut 0. L'intervalle est calculé par bootstrap par blocs de 7 jours livrés consécutifs à partir du 02/09/2024, avec 10 000 tirages et la graine 20261117.
3. **Aucun candidat admissible** : on ne règle rien pour forcer la couverture. Le résultat est écrit tel quel, et toute correction devient une nouvelle comparaison, avec sa règle écrite avant.

**Compteur** : Q1, Q2 et Q3 sont les comparaisons 11, 12 et 13. La procédure mensuelle et la référence J-7 ne sont pas comptées. **Total à la fin : 13.**

### Ce qui est publié

- Pour chaque candidat et pour la référence : la couverture à 80 et à 95 %, le pinball par niveau et en moyenne (en MW), et la largeur moyenne des intervalles à 80 et à 95 % (en MW). Le tout sur l'évaluation entière, par saison et par tranche de 3 h. Une couverture juste avec des intervalles très larges ne vaut rien, et la largeur se lit plus facilement que le pinball.
- La couverture sur l'évaluation hors hiver 2024-25 et sur juin-août 2025 (fenêtre complète), à titre d'information.
- Le biais et la MAPE de q0,5, à titre d'information.
- Les MAPE d'A17 figé et de la procédure mensuelle, et le tableau des 18 modèles.

**Étiquettes** : « météo prévue en partie rejouée » ; « période de validation déjà utilisée pour choisir A17 (10 comparaisons) » ; « fenêtre de calibration réduite avant juin 2025 ».

## 22. Résultats de l'incertitude de la v0.2 — 24/11/2026

Règle de l'entrée 21 appliquée telle qu'écrite (`docs/v0.2-incertitude/data/intervalles.json`). **Comparaisons sur la validation : 13** (Q1 : 11, Q2 : 12, Q3 : 13). Étiquettes : « météo prévue en partie rejouée » ; « période de validation déjà utilisée pour choisir A17 (10 comparaisons) » ; « fenêtre de calibration réduite avant juin 2025 ».

**Évaluation** : du 02/09/2024 au 31/08/2025, 17 464 demi-heures jugées, de 108 à 365 jours de résidus selon la date de décision.

### Procédure mensuelle

| Mois | Dernière ligne d'entraînement | Fin autorisée (M − 4) | Lignes |
|---|---|---|---|
| 2024-03 | 30/11/2023 | 30/11/2023 | 121 172 |
| 2024-04 | 31/12/2023 | 31/12/2023 | 122 660 |
| 2024-05 | 31/01/2024 | 31/01/2024 | 124 148 |
| 2024-06 | 29/02/2024 | 29/02/2024 | 125 540 |
| 2024-07 | 31/03/2024 | 31/03/2024 | 127 026 |
| 2024-08 | 30/04/2024 | 30/04/2024 | 128 466 |
| 2024-09 | 31/05/2024 | 31/05/2024 | 129 954 |
| 2024-10 | 30/06/2024 | 30/06/2024 | 131 394 |
| 2024-11 | 31/07/2024 | 31/07/2024 | 132 882 |
| 2024-12 | 31/08/2024 | 31/08/2024 | 134 370 |
| 2025-01 | 30/09/2024 | 30/09/2024 | 135 810 |
| 2025-02 | 31/10/2024 | 31/10/2024 | 137 296 |
| 2025-03 | 30/11/2024 | 30/11/2024 | 138 736 |
| 2025-04 | 31/12/2024 | 31/12/2024 | 140 224 |
| 2025-05 | 31/01/2025 | 31/01/2025 | 141 712 |
| 2025-06 | 28/02/2025 | 28/02/2025 | 143 056 |
| 2025-07 | 31/03/2025 | 31/03/2025 | 144 542 |
| 2025-08 | 30/04/2025 | 30/04/2025 | 145 982 |

Les 18 modèles ont la même empreinte de configuration (sha256 commençant par `89536f7563a5`, valeur complète dans le fichier de résultats).

MAPE, pour information (mensuelle − figée, en points, intervalle à 95 %) :

| Période | A17 figé | Procédure mensuelle | Différence |
|---|---|---|---|
| Toute la validation | 2,617 % | 2,667 % | +0,050 [−0,022 ; +0,122] |
| Évaluation | 2,563 % | 2,590 % | +0,027 [−0,047 ; +0,102] |
| 15/03 → 30/06/2024 (avantage de date) | 2,995 % | 2,983 % | −0,012 [−0,153 ; +0,179] |

La procédure mensuelle est gardée, comme écrit d'avance. Son écart avec A17 figé n'est pas distinguable du bruit, et l'avantage de date de la v0.1 n'a pas d'effet mesurable sur mars-juin 2024.

### Candidats et référence

| | Couverture 80 % | Couverture 95 % | Largeur 80 % | Largeur 95 % | Pinball moyen | Admissible |
|---|---|---|---|---|---|---|
| Q1 | 77,50 % | 94,20 % | 3 774 MW | 6 624 MW | 288,2 MW | oui |
| Q2 | 76,83 % | 93,98 % | 3 846 MW | 6 914 MW | 293,9 MW | oui |
| Q3 | 73,52 % | 92,43 % | 3 642 MW | 6 709 MW | 297,9 MW | **non** (80 % sous 75 %) |
| Référence J-7 | 78,40 % | 94,14 % | 11 280 MW | 20 362 MW | 830,5 MW | (référence) |

**Décision** : Q1 et Q2 sont admissibles, Q3 ne l'est pas. Q1 est retenu au départ. Q2 fait moins bien que Q1 (+5,7 MW de pinball, intervalle [+3,3 ; +8,3], soit −2,0 %) : **Q1 est retenu**. Q3 n'est jamais jugé sur le pinball, puisqu'il n'est pas admissible. Son repli vers Q2 a joué pour 125 couples (mois de décision, groupe), soit 3 808 demi-heures jugées.

**Face à la référence — indication sur la validation, pas le critère** : pinball de Q1 288,2 MW contre 830,5 MW pour J-7, soit −542,4 MW, intervalle [−676,0 ; −424,6]. Les intervalles de Q1 sont environ trois fois plus étroits que ceux de la référence pour une couverture voisine.

**Par saison (Q1)** :

| Saison | Couverture 80 % | Couverture 95 % | Largeur 95 % |
|---|---|---|---|
| Automne | 84,89 % | 95,97 % | 6 917 MW |
| Hiver | 65,81 % | 88,15 % | 6 395 MW |
| Printemps | 83,64 % | 98,78 % | 6 892 MW |
| Été | 75,59 % | 93,82 % | 6 294 MW |

Le risque connu se vérifie : en hiver, la couverture tombe à 65,8 % et 88,2 %, parce que les intervalles d'hiver sont calibrés sur des résidus sans hiver. Ils sont même plus étroits qu'au printemps et à l'automne. Hors hiver 2024-25, à titre d'information : 81,35 % et 96,19 %. Sur juin-août 2025, avec la fenêtre complète : 75,59 % et 93,82 %. La référence J-7 souffre du même défaut en hiver (56,9 % et 89,1 %) et couvre trop en été (96,5 % et 99,98 %).

**Par tranche de 3 h (Q1)** : la couverture à 80 % va de 73,9 % (12 h-15 h) à 81,5 % (6 h-9 h), celle à 95 % de 91,2 % (15 h-18 h) à 95,7 % (21 h-24 h).

**Médiane, pour information** : q0,5 de Q1 a un biais de +289 MW et une MAPE de 2,540 %.

### Observation hors règle

Les fenêtres de calibration qui contiennent mars 2024 incluent les résidus des 15 et 16/03/2024, gonflés de 7 à 8 GW par le lissage sur 72 h manquant (entrée 20). Ils peuvent élargir les quantiles extrêmes des décisions antérieures à juin 2025. L'effet n'est pas mesuré, et la règle n'est pas changée.

Comparaisons sur la validation après cette entrée : 13. Mesures dans l'entraînement : 2.

## 23. Précisions sur les résultats de la v0.2 — 24/11/2026

Comparaisons sur la validation : 13, inchangé. Aucune règle ne change ; les mesures ci-dessous sont des informations, sans effet sur la décision de l'entrée 22.

**Fin de l'entraînement des modèles mensuels.** L'entrée 21 fixe bien la fin de l'entraînement au dernier jour de M − 4, et non de M − 3. Le modèle du mois M prévoit dès le 1er du mois, donc il doit exister à midi le dernier jour de M − 1, quand le consolidé publié ne va que jusqu'à la fin de M − 4.

**Modèle et résidus ne sont pas alignés jour par jour.** Le modèle est réentraîné chaque mois, et la fenêtre des résidus est relue chaque jour, comme l'écrit l'entrée 21. Ce décalage est gardé ; ce n'est pas une nouvelle comparaison.

| Jour livré | Décision | Modèle : appris jusqu'à | Résidus : jusqu'à |
|---|---|---|---|
| 1er du mois M | dernier jour de M − 1 | fin de M − 4 | fin de M − 4 |
| du 2 au dernier jour de M | dans le mois M | fin de M − 4 (modèle figé pour le mois) | fin de M − 3 |

Aucune fuite : chaque résidu est publié à midi la veille et vient d'un modèle qui n'avait pas vu son jour.

**Cause des résidus gonflés des 15 et 16/03/2024.** L'archive de météo prévue commence au calcul du 14/03/2024. La première demi-heure du 15/03 (23 h UTC le 14/03) demande, pour sa température lissée sur 72 h, les heures à partir du 12/03 à 0 h UTC, qu'aucun calcul en cache ne contient. Les 96 demi-heures des 15 et 16/03 n'ont donc pas ce lissage ; le premier lissage complet arrive le 17/03 à 0 h, heure de Paris. Il ne manque aucun calcul, le calcul de secours n'a servi à rien sur la validation, et la prévision de ces deux jours n'a pas de valeur aberrante : écart moyen avec ERA5 de 0,97 °C pour la température (au plus 1,78 °C), 0,92 °C pour le lissage sur 24 h, 1,5 m/s pour le vent. Ce n'est pas un défaut des données mais la limite de début de l'archive : l'observation de l'entrée 22 est gardée telle quelle.

- Information, sans effet sur la décision : Q1 sans ces 96 demi-heures dans les fenêtres de résidus couvre 76,45 % et 93,58 %, avec des intervalles de 3 685 et 6 345 MW et un pinball de 289,0 MW (contre 77,50 %, 94,20 %, 3 774 et 6 624 MW, 288,2 MW).
- Ces 96 demi-heures n'entrent dans aucune fenêtre de résidus du test : la première commence le 01/06/2024. Un test automatique le vérifie.

**Prévision ponctuelle officielle.** C'est désormais A17 avec réentraînement mensuel : **MAPE de validation 2,667 %**. Le chiffre de 2,617 % reste dans l'historique de la v0.1, sous l'étiquette « modèle figé ». Rapport au naïf J-7 sur l'échantillon commun du bilan de la v0.1 (25 607 demi-heures), indication sur la validation et non critère : **0,441, intervalle [0,382 ; 0,512]**. Le modèle figé y retrouve son rapport de 0,433 [0,375 ; 0,503]. Sur le même échantillon, la prévision mensuelle fait 2,665 % ; son écart à RTE J-1 brute est de +0,084 point, intervalle [−0,200 ; +0,370], et à J-7 de −3,372 points, intervalle [−4,252 ; −2,548].

**Biais de la médiane et du modèle.** Sur l'évaluation, q0,5 prévoit trop de 289 MW en moyenne, et la prévision ponctuelle mensuelle de 259 MW. Le biais vient donc surtout du modèle ; le décalage de la fenêtre de résidus n'y ajoute qu'environ 30 MW. Point ouvert pour la v0.3 : la décision d'achat se prendra à un quantile, et ce biais coûtera directement des euros.

**Prédiction pour le test.** Sur le test, Q1 mélange les saisons dans chaque groupe : on s'attend à une couverture inférieure à la cible en hiver et supérieure en été. La couverture par saison du test sera lue au regard de cette prédiction. Une méthode qui tient compte de la saison sera une nouvelle comparaison, dans une version ultérieure ; elle ne pourra pas être jugée sur la validation, faute de résidus d'hiver dans les fenêtres de l'hiver 2024-25.

**Cibles absentes.** Les quatre demi-heures de validation sans cible sont celles du 27/10/2024 étiquetées 2 h 00 et 2 h 30, qui existent chacune deux fois le jour du passage à l'heure d'hiver et restent sans cible par construction (ADR 0002).

Comparaisons sur la validation après cette entrée : 13. Mesures dans l'entraînement : 2.

## 24. Décision d'achat de la v0.3 — règle écrite le 24/11/2026, avant le calcul

Comparaisons sur la validation : 13. Mesures dans l'entraînement : 2.

### Correction de l'ADR 0001 : le « régime d'écart unique » du 05/10/2024

L'ADR 0001 prévoyait d'estimer q « uniquement sur la partie de la validation postérieure au passage au régime d'écart unique (05/10/2024) ». La source de cette date est le chapitre 3 des Règles de marché de RTE (« Dispositif de Responsable d'Équilibre », version V02.1 en vigueur au 4 juillet 2026, délibération CRE 2026-109 du 26 mai 2026), section 3.A :

- la section décrit l'évolution des « processus de Reconstitution des Flux, à partir de la date du 5 octobre 2024 » : avant cette date, deux processus (Écarts et Réconciliation Temporelle) ; « A compter de la date du 5 octobre 2024 : un processus unique Ecarts » ;
- « Profilage permet de fusionner les processus Ecarts et Réconciliation Temporelle en un processus unique Ecarts ».

Ces citations viennent d'une extraction automatique du texte du PDF ; la phrase sur la situation d'avant le 5 octobre en est sortie abîmée et n'est donc donnée qu'en substance.

Il ne s'agit ni d'un prix unique ni d'une position unique, mais de la fusion de deux traitements des données de comptage dans la reconstitution des flux. L'ADR 0001 a pris ce changement de traitement pour un changement du prix. **Les prix restent doubles** :

- même chapitre, section 3.M.1 (« Règlement des Ecarts positifs ») : un prix s'applique aux écarts positifs, et dans le « cas contraire, le Prix de Règlement des Ecarts négatifs est alors appliqué » ;
- page de RTE « Le prix de règlement des écarts de responsable d'équilibre » : « le PRE est calculé en fonction de la tendance d'équilibrage, du prix moyen pondéré des activations (PMP), de la valeur applicable du coefficient « k », et du signe de l'écart du responsable d'équilibre (positif ou négatif) » ; « Le PRE positif ne peut pas être supérieur au PRE négatif ».

Sources non lisibles : le rapport de surveillance 2024 de la CRE et le rapport d'équilibrage 2024 de RTE (PDF illisibles par nos outils). L'ADR 0001 n'est pas réécrit ; la correction figurera dans l'ADR de la v0.3. Dès le jeton reçu, on vérifie dans les données d'ENTSO-E que les deux prix diffèrent, et à quelle fréquence.

**Coefficient k.** La page de RTE décrit, depuis le 1er janvier 2023, un pilotage dynamique ex ante du coefficient k, avec des paramètres fixes : « keq » 0,045, « kmin » 0, « kmax » 0,200, palier de 5 M€, pente de 0,0015 par M€. Aucun changement de ces paramètres entre 2025 et 2026 n'apparaît dans les pages lues. La valeur de k, elle, varie d'un mois à l'autre par construction. C'est une limite : q, estimé sur 2025, suppose que le niveau des pénalités reste comparable en 2025-26. Les valeurs mensuelles de k publiées par RTE n'ont pas été lues.

### Période d'estimation de q

Du 01/01/2025 au 31/08/2025 : deux prix et pas de 15 minutes, les mêmes règles que sur tout le test. Limite : cette période ne contient ni septembre, ni l'automne, ni la fin de l'année. Sont publiés à titre d'information : q mois par mois, et q sur toute la validation (du 15/03/2024 au 31/08/2025, pas de 30 minutes avant 2025).

### Formule de q (B), précision de l'ADR 0001

La prévision ponctuelle est la procédure mensuelle de la v0.2. Pour chaque période de règlement k de la période d'estimation, l'écart de la prévision ponctuelle vaut consommation − prévision. La demi-heure est coupée en deux quarts d'heure, de même écart de puissance, chacun avec son propre prix.

- Pénalité courte Cu : moyenne de (PRE négatif − P_ref) sur les périodes où la prévision ponctuelle nous laissait courts (consommation > prévision).
- Pénalité longue Co : moyenne de (P_ref − PRE positif) sur les périodes où elle nous laissait longs (consommation < prévision).
- q = Cu / (Cu + Co).
- Si Cu ou Co n'est pas strictement positif, la règle du vendeur de journaux ne s'applique pas : on l'écrit, et l'achat reste la prévision ponctuelle.

**L'achat au quantile q** est la prévision ponctuelle plus le quantile empirique de niveau q des résidus de la même demi-heure, avec la fenêtre et les règles de Q1 (entrée 21).

Deux réserves, écrites d'avance :

- B utilise le signe de l'écart de la prévision ponctuelle. Une fois qu'on achète à q, les signes changent un peu ;
- la couverture de la v0.2 n'a été contrôlée qu'aux cinq niveaux de l'ADR 0001. La couverture empirique de q (part des demi-heures où la consommation est sous le quantile q) est publiée sur la période d'estimation.

Sont publiés à titre d'information, sans choix possible et sans comparaison comptée :

- la formule A de l'ADR 0001 (moyennes sur toutes les périodes) ;
- la courbe du coût selon le quantile d'achat, de 0,05 à 0,95 par pas de 0,05, sur la période d'estimation. Elle montre si q tombe près du minimum. **La courbe n'est pas une option** : elle ne sert à rien choisir.

### Coût

Fonction de coût de l'ADR 0001. Pour chaque période k, l'écart vaut Δk = s × (consommation − achat), en MWh. Si Δk > 0 (court), le coût est Δk × (PRE négatif − P_ref). Si Δk < 0 (long), il vaut |Δk| × (P_ref − PRE positif). P_ref vaut 61,1 €/MWh. La sensibilité à 40 et à 100 €/MWh recalcule q et les coûts avec chaque P_ref. Les montants sont publiés pour s = 1 % et en euros par MWh consommé.

**Comparaison, indication sur la validation** : coût d'un achat au quantile q contre coût d'un achat à la prévision ponctuelle, sur la période d'estimation, avec la différence appariée et un intervalle à 95 % par bootstrap par blocs de 7 jours (10 000 tirages, graine 20261117). Le critère de l'ADR 0001 se juge sur le test. Étiquette : **« q estimé et jugé sur la même période : indication optimiste »**.

**Biais** : aucune correction en v0.3. Le coût est décomposé pour montrer la part due au biais. On publie le coût d'un achat au quantile q diminué du biais moyen de q0,5 sur la période d'estimation, à titre d'information. Étiquette : « borne informative, biais connu après coup, impossible en pratique ».

**Compteur** : q est calculé par une formule fixée d'avance, sans choix entre options. Le compteur reste à 13.

**Étiquettes** : « météo prévue en partie rejouée » ; « période de validation déjà utilisée pour choisir A17 et Q1 (13 comparaisons) » ; « q estimé et jugé sur la même période ».

### Données des prix des écarts

- ENTSO-E Transparency Platform, Imbalance Prices [17.1.G], zone France (code EIC 10YFR-RTE------C), du 15/03/2024 au 31/08/2026. Lire les prix du test ne l'ouvre pas : sa cible reste masquée. Licence CC BY 4.0, mention « ENTSO-E Transparency Platform ».
- API : `https://web-api.tp.entsoe.eu/api`, type de document A85, dates en UTC, au plus un an par requête. La documentation distingue deux champs, `PositiveImbalancePrice` et `NegativeImbalancePrice`. La limite publiée est de 400 requêtes par minute par jeton, avec un code 429 en cas de dépassement.
- Non vérifiés faute de lecture possible : le nom exact du paramètre de zone (documentation Postman illisible par nos outils) et le format de la réponse. Ils sont vérifiés par **un appel de contrôle** sur une seule journée avant tout téléchargement.
- **Estimation écrite avant le premier appel** : 1 appel de contrôle, puis une requête par mois civil (30 mois, du 03/2024 au 08/2026), pour rester loin de la limite de 200 documents par réponse. Soit 31 appels. **Plafond local : 100 appels par jour**, au plus un appel toutes les 2 secondes. **Arrêt définitif au premier code 429.** Une coupure réseau ou une réponse 5xx donne lieu à une seule nouvelle tentative, comptée.
- **Jeton** : lu dans `.env` uniquement, jamais affiché ni journalisé, jamais écrit dans un fichier du cache. Un test vérifie qu'il n'apparaît dans aucune sortie ni aucun fichier écrit.
