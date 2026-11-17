# ADR 0002 : table de données à la demi-heure

- Statut : accepté le 17/11/2026 ; convention de la demi-heure tranchée le même jour par la mesure prévue
- Date : 17 novembre 2026
- Version : v0.1

## Contexte

La v0.1 produit une prévision ponctuelle, jugée sur la validation seulement. Avant tout modèle, la table qui le nourrit est fixée : une ligne par demi-heure, la cible, le calendrier, la météo telle qu'elle est connue à midi la veille et le niveau récent de la consommation. Chaque convention est écrite ici avant toute mesure de performance, et chacune a un test.

Code : `src/day_ahead_load/table.py`, `weather_features.py`, `calendar_features.py`. Construction : `scripts/modelling/build_table.py`, qui ne lit que le cache local. Comptages : `docs/v0.1-prevision-ponctuelle/data/table-resume.json`.

## Décisions

### Lignes et cible

- Une ligne par demi-heure réelle, indexée par l'instant UTC de fin : 48 par jour, 46 le jour du passage à l'heure d'été, 50 le jour du retour à l'heure d'hiver.
- Le jour livré est la date publiée par éCO2mix (demi-heures étiquetées de 00 h 00 à 23 h 30, heure de Paris), comme pour les références de la v0.0.
- Cible : consommation consolidée ou définitive aux demi-heures pleines. Les deux demi-heures ambiguës du retour à l'heure d'hiver restent sans cible et ne sont jamais jugées.
- Découpage de l'ADR 0001 : entraînement jusqu'au 14/03/2024, validation du 15/03/2024 au 31/08/2025, test du 01/09/2025 au 31/08/2026. La cible du test est masquée par défaut à la construction (test `test_test_target_is_masked_unless_opened`).

### Convention de la demi-heure

Première version : la valeur étiquetée t couvre l'intervalle (t − 30 min, t]. La spécification d'éCO2mix dit « puissance moyenne » sans préciser le côté de l'intervalle : c'était une **hypothèse**, cohérente avec l'alignement mesuré en v0.0 mais non prouvée.

**Règle de décision, écrite avant de calculer (17/11/2026).** Deux options sont comparées : (t − 30 min, t] et (t − 15 min, t + 15 min]. Même modèle LightGBM figé, validation croisée temporelle à l'intérieur de l'entraînement seulement, sans toucher à la validation. On garde l'option à la plus faible MAPE. Si l'écart relatif entre les deux est inférieur à 1 %, on garde (t − 30 min, t], qui suit l'alignement mesuré en v0.0. La mesure est notée dans le journal des choix de la v0.1. L'interpolation au milieu de la demi-heure et la règle du rayonnement découlent de la convention : si la mesure fait changer la convention, elles changent avec elle.

**Résultat (17/11/2026, journal des choix, entrée 3).** MAPE moyenne sur 2019 → 2023 : 4,387 % pour (t − 30 min, t], 4,295 % pour (t − 15 min, t + 15 min], soit un écart relatif de −2,1 %, au-delà du seuil de 1 %. **Convention retenue : (t − 15 min, t + 15 min].** Le signal est fragile : cette option gagne trois années sur cinq (2019, 2021, 2023), et l'écart vient surtout de 2021 (−0,22 point) et de 2023 (−0,31 point) ; elle perd de 0,05 point en 2020 et en 2022. La règle est appliquée telle qu'écrite. Détail : `docs/v0.1-prevision-ponctuelle/data/convention-demi-heure.json`.

### Passage de l'heure à la demi-heure

D'après la documentation de l'API historique d'Open-Meteo (tableau « Hourly Parameter Definition », lu le 17/11/2026), la température, la nébulosité, le vent et l'humidité sont des valeurs instantanées à l'heure indiquée. Le rayonnement étiqueté h est la moyenne de l'heure précédente, ce que la v0.0 a vérifié aux 12 points pour les trois sources.

| Variable | Règle | Exemple |
|---|---|---|
| Variable | Convention retenue (t − 15, t + 15] | Option écartée (t − 30, t] |
|---|---|---|
| Température, nébulosité, vent | Interpolation linéaire au milieu de l'intervalle, t. Demi-heure 12 h 30 : 0,5 × T(12 h) + 0,5 × T(13 h) ; demi-heure 13 h 00 : T(13 h) | Milieu t − 15 min. Demi-heure 12 h 30 : 0,75 × T(12 h) + 0,25 × T(13 h) |
| Rayonnement | Moyenne des heures qui recouvrent l'intervalle, pondérée par la durée. Demi-heure 12 h 30 : valeur de 13 h 00 ; demi-heure 13 h 00 : moitié de 13 h 00, moitié de 14 h 00 | La valeur de 13 h 00 (moyenne de 12 h à 13 h) s'applique aux demi-heures 12 h 30 et 13 h 00 |
| Températures lissées | Moyenne des 24 et 72 heures qui finissent à la fin de l'intervalle arrondie à l'heure inférieure ; manquante si une heure manque. Demi-heure 12 h 30 : heures de 13 h la veille à 12 h | Identique pour les demi-heures pleines |

Tests : `test_retained_centred_option_splits_radiation_between_the_two_hours_it_overlaps`, `test_end_option_radiation_labelled_13h_applies_to_half_hours_12h30_and_13h00`, `test_end_option_reads_instant_variables_at_the_middle_of_the_half_hour`, `test_smoothing_uses_the_hours_of_the_trailing_window_only`.

Les quatre variables sont des indices nationaux, moyennes des 12 points pondérées par la consommation régionale (poids fixés en v0.0). L'humidité, téléchargée, n'entre pas dans la v0.1.

### Source de chaque heure

| Lignes | Heures du jour livré J | Heures passées des lissages |
|---|---|---|
| Entraînement | ERA5 | ERA5 |
| Validation, test, production | Calcul ECMWF de 00 UTC de J-1 | À partir de 00 UTC de J-1 : le même calcul, donc les heures de J-1 avant comme après midi. Avant : les premières heures (échéances 0 à 23 h) du calcul de 00 UTC du jour UTC de chaque heure |

ERA5 est publié avec environ 5 jours de retard : à midi la veille, il n'existe pas pour les jours récents. Il ne sert donc jamais hors de l'entraînement. Tous les calculs lus pour J sont lancés au plus tard à 00 UTC de J-1 et déposés, avec la marge de 2 h de l'ADR 0001, avant midi la veille. Le test `test_nothing_published_after_noon_the_day_before_enters_the_features` remplace tous les calculs plus récents par des valeurs absurdes et vérifie que les variables de J ne changent pas.

Le passage d'ERA5 aux calculs ECMWF dans les lissages est le même type d'écart d'une source à l'autre que celui que mesure la comparaison A / B / C pour la température du jour. Mesuré sur la validation, face à ERA5 traité par les mêmes règles : MAE de 0,66 °C pour la température de la demi-heure, 0,40 °C pour le lissage sur 24 h, 0,32 °C sur 72 h, avec un biais d'environ −0,15 °C dans les trois cas.

**Calcul de secours.** Une valeur absente d'un calcul est prise dans le calcul antérieur le plus récent qui couvre l'heure, comme le ferait la production. Constaté dans le cache le 17/11/2026 : le rayonnement de l'échéance 0 manque dans les 975 calculs (une moyenne de l'heure précédente n'existe pas au lancement), et le calcul du 23/06/2026, dans le test, n'a ni température, ni vent, ni humidité sur ses 72 heures, aux 12 points.

Trois conditions, chacune vérifiée :

- le calcul de secours est plus ancien que le calcul prévu, donc lancé au plus tard à 00 UTC de J-1 et disponible à midi la veille (test `test_fallback_runs_are_all_available_at_noon_the_day_before`) ;
- chaque utilisation est enregistrée, avec le jour livré, la variable, l'heure, le calcul prévu et le calcul utilisé (`docs/v0.1-prevision-ponctuelle/data/calcul-de-secours.csv`). Seules les heures que lit réellement une variable sont comptées. Le rayonnement de l'échéance 0 n'est pas une panne et n'est jamais compté (test `test_radiation_at_lead_zero_is_not_counted_as_a_fallback`) ;
- le test est évalué tel quel, avec le secours, puisque c'est ce qui se passerait en production. Ses résultats indiqueront le nombre de jours concernés.

Comptage du 17/11/2026 : aucune utilisation en validation. Dans le test, 4 jours livrés (24 au 27/06/2026), tous dus au calcul du 23/06/2026 : 96 valeurs horaires de température, lues surtout par les lissages, et 25 de vent (26 avec l'option écartée).

### Niveau récent

Moyenne de la consommation consolidée ou définitive des 52 semaines qui précèdent la fin du consolidé publié à midi la veille (règle M+3 de l'ADR 0001). Une année glissante donne le niveau sans effet de saison. La référence « hebdomadaire réaliste » de la v0.0 (18,8 %) montrait qu'une fenêtre de quatre semaines vieilles de 9 à 13 semaines mêle niveau et saison.

Le niveau est manquant tant que la fenêtre commence avant le début des données (jours livrés du 01/01/2012 au 01/03/2013) ou qu'il manque plus de 1 % de ses demi-heures. LightGBM gère ces valeurs manquantes. La régression linéaire ne les gère pas : son entraînement commence au 02/03/2013. Pour que les deux familles soient comparées sur les mêmes jours, ce choix est noté dans le journal des choix. Test : `test_level_uses_the_52_weeks_before_the_end_of_published_consolidated_data`, avec des valeurs non publiées mises à 10⁹.

Trois variantes seront mesurées en v0.1 : la consommation avec le niveau en variable ; le rapport consommation / niveau comme cible, car un gradient boosting ne sait pas prolonger une tendance ; la consommation sans niveau.

### Calendrier

- Jours fériés : bibliothèque `holidays` (licence MIT, version 0.107 figée par `uv.lock`). Elle calcule les jours fériés sans appel réseau ni fichier à tenir à jour, ce qui respecte la règle « aucun appel en CI ». Le jeu de calendrier.api.gouv.fr aurait demandé un téléchargement, un cache et une vérification de licence pour la même information.
- Lundi de Pentecôte : indicateur à part. Il est férié en droit, mais il est la journée de solidarité depuis 2005 et une partie des entreprises travaille.
- Limite : le Vendredi saint et le 26/12, fériés en Alsace-Moselle seulement, ne sont pas marqués.
- Pont : jour ouvré coincé entre un jour férié et le week-end, c'est-à-dire un lundi dont le mardi est férié, ou un vendredi dont le jeudi est férié. Un mercredi férié ne crée pas de pont.
- Noël : indicateur du 24/12 au 01/01 inclus.
- Autres variables : demi-heure du jour (heure de Paris), jour de la semaine, mois. Pas de vacances scolaires en v0.1 ; les résidus de la v0.2 diront s'il en faut.

## Constats de la construction (17/11/2026)

| Période | Jours | Demi-heures | Valeurs manquantes |
|---|---|---|---|
| Entraînement | 01/01/2012 → 14/03/2024 | 213 936 | Cible 48 (heures ambiguës d'octobre) ; niveau 20 448 (426 jours, avant le 02/03/2013) ; météo des premières heures de 2012 (1 à 144 selon la variable) |
| Validation | 15/03/2024 → 31/08/2025 | 25 678 | Cible 4 (heures ambiguës) ; lissage sur 72 h 96 (15 et 16/03/2024 : aucun calcul avant le 14/03/2024) |
| Test | 01/09/2025 → 31/08/2026 | 17 520 | Cible masquée ; météo complète grâce au calcul de secours (4 jours concernés) |
| Prospectif | 01/09/2026 → 14/11/2026 | 3 602 | Cible non publiée |

Rayonnement prévu face à ERA5 sur la validation, avec la convention retenue : corrélation 0,995 sans décalage, 0,984 et 0,985 avec un décalage de 30 min (0,994 et 0,973 avec l'option écartée). Les deux sources suivent la même convention une fois passées à la demi-heure. La température prévue s'écarte d'ERA5 de 0,66 °C en MAE, comme avec l'option écartée.

## Conséquences

- La comparaison A / B / C et le choix de la famille de modèles s'appuient sur cette table, sans la modifier. Tout changement de convention passe par une nouvelle version de cet ADR, datée, avant toute nouvelle mesure.
- Les variantes B et C ont besoin de la série IFS historique sur 2017 → 2024-03-14 : téléchargement en cours le 17/11/2026.
- La convention retenue l'a été sur un signal fragile ; si une source de RTE précise l'intervalle, elle prime, par une nouvelle version datée de cet ADR.

## Points ouverts

| Point | Ce qui le ferme |
|---|---|
| Série IFS historique 2017 → 2024-03-14 pour B et C | Téléchargement accordé le 17/11/2026 : 188 tranches × 12 points = 2 256 appels, plafond de 8 000 par jour, une seule nouvelle tentative sur coupure réseau ou 5xx, arrêt définitif au premier 429 |
