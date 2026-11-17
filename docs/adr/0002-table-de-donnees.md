# ADR 0002 : table de données à la demi-heure

- Statut : proposé
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

La valeur étiquetée t couvre l'intervalle (t − 30 min, t]. La spécification d'éCO2mix dit « puissance moyenne » sans préciser le côté de l'intervalle : c'est une **hypothèse**. Elle est cohérente avec l'alignement mesuré en v0.0, où aucune combinaison gagnante n'utilisait de quart d'heure postérieur à t, mais cette mesure ne la prouve pas.

### Passage de l'heure à la demi-heure

D'après la documentation de l'API historique d'Open-Meteo (tableau « Hourly Parameter Definition », lu le 17/11/2026), la température, la nébulosité, le vent et l'humidité sont des valeurs instantanées à l'heure indiquée. Le rayonnement étiqueté h est la moyenne de l'heure précédente, ce que la v0.0 a vérifié aux 12 points pour les trois sources.

| Variable | Règle | Exemple |
|---|---|---|
| Température, nébulosité, vent | Interpolation linéaire entre les deux heures qui encadrent le milieu de la demi-heure, t − 15 min | Demi-heure 12 h 30 : 0,75 × T(12 h) + 0,25 × T(13 h) |
| Rayonnement | Valeur de l'heure qui contient la demi-heure, étiquetée t arrondi à l'heure supérieure | La valeur de 13 h 00 (moyenne de 12 h à 13 h) s'applique aux demi-heures 12 h 30 et 13 h 00, pas à 13 h 00 et 13 h 30 |
| Températures lissées | Moyenne des températures horaires de (t − 24 h, t] et de (t − 72 h, t] ; manquante si une heure manque | Demi-heure 12 h 30 : heures de 13 h la veille à 12 h |

Tests : `test_radiation_labelled_13h_applies_to_half_hours_12h30_and_13h00`, `test_instant_variables_are_read_at_the_middle_of_the_half_hour`, `test_smoothing_uses_the_hours_of_the_trailing_window_only`.

Les quatre variables sont des indices nationaux, moyennes des 12 points pondérées par la consommation régionale (poids fixés en v0.0). L'humidité, téléchargée, n'entre pas dans la v0.1.

### Source de chaque heure

| Lignes | Heures du jour livré J | Heures passées des lissages |
|---|---|---|
| Entraînement | ERA5 | ERA5 |
| Validation, test, production | Calcul ECMWF de 00 UTC de J-1 | À partir de 00 UTC de J-1 : le même calcul, donc les heures de J-1 avant comme après midi. Avant : les premières heures (échéances 0 à 23 h) du calcul de 00 UTC du jour UTC de chaque heure |

ERA5 est publié avec environ 5 jours de retard : à midi la veille, il n'existe pas pour les jours récents. Il ne sert donc jamais hors de l'entraînement. Tous les calculs lus pour J sont lancés au plus tard à 00 UTC de J-1 et déposés, avec la marge de 2 h de l'ADR 0001, avant midi la veille. Le test `test_nothing_published_after_noon_the_day_before_enters_the_features` remplace tous les calculs plus récents par des valeurs absurdes et vérifie que les variables de J ne changent pas.

Le passage d'ERA5 aux calculs ECMWF dans les lissages est le même type d'écart d'une source à l'autre que celui que mesure la comparaison A / B / C pour la température du jour. Mesuré sur la validation, face à ERA5 traité par les mêmes règles : MAE de 0,66 °C pour la température de la demi-heure, 0,40 °C pour le lissage sur 24 h, 0,32 °C sur 72 h, avec un biais d'environ −0,15 °C dans les trois cas.

**Calcul de secours.** Une valeur absente d'un calcul est prise dans le calcul antérieur le plus récent qui couvre l'heure, comme le ferait la production. Constaté dans le cache le 17/11/2026 : le rayonnement de l'échéance 0 manque dans les 975 calculs (une moyenne de l'heure précédente n'existe pas au lancement), et le calcul du 23/06/2026, dans le test, n'a ni température, ni vent, ni humidité sur ses 72 heures, aux 12 points.

### Niveau récent

Moyenne de la consommation consolidée ou définitive des 52 semaines qui précèdent la fin du consolidé publié à midi la veille (règle M+3 de l'ADR 0001). Une année glissante donne le niveau sans effet de saison. La référence « hebdomadaire réaliste » de la v0.0 (18,8 %) montrait qu'une fenêtre de quatre semaines vieilles de 9 à 13 semaines mêle niveau et saison.

Le niveau est manquant tant que la fenêtre commence avant le début des données (jours livrés du 01/01/2012 au 01/03/2013) ou qu'il manque plus de 1 % de ses demi-heures. Test : `test_level_uses_the_52_weeks_before_the_end_of_published_consolidated_data`, avec des valeurs non publiées mises à 10⁹.

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
| Test | 01/09/2025 → 31/08/2026 | 17 520 | Cible masquée ; météo complète grâce au calcul de secours |
| Prospectif | 01/09/2026 → 14/11/2026 | 3 602 | Cible non publiée |

Rayonnement prévu face à ERA5 sur la validation : corrélation 0,994 sans décalage, 0,973 avec un décalage de 30 min dans un sens ou dans l'autre. Les deux sources suivent donc la même convention une fois passées à la demi-heure.

## Conséquences

- La comparaison A / B / C et le choix de la famille de modèles s'appuient sur cette table, sans la modifier. Tout changement de convention passe par une nouvelle version de cet ADR, datée, avant toute nouvelle mesure.
- Les variantes B et C ont besoin de la série IFS historique sur 2017 → 2024-03-14, qui n'est pas encore téléchargée : seule la validation l'est.

## Points ouverts

| Point | Ce qui le ferme |
|---|---|
| Côté de l'intervalle de la demi-heure d'éCO2mix | Source de RTE, ou mesure sur l'entraînement seulement, règle écrite avant |
| Série IFS historique 2017 → 2024-03-14 pour B et C | Estimation des appels et plafond, puis accord avant le téléchargement |
