# day-ahead-load : prévisions quotidiennes

**Prévisions produites par ce projet, pas des données RTE.**

Cette branche est écrite par les workflows « Prévision quotidienne » et « Niveau mensuel » du dépôt [day-ahead-load](https://github.com/mangnathan/day-ahead-load). Elle ne se modifie pas à la main. Chaque jour, avant midi heure de Paris, une prévision de la consommation électrique française du lendemain est ajoutée, demi-heure par demi-heure.

## Ce qui tourne

- Un modèle et une fourchette **figés à la fin de la période de validation (31/08/2025)**. La période de test du projet (du 01/09/2025 au 31/08/2026) reste fermée : aucune erreur n'y est calculée avant son ouverture unique.
- Le volume au quantile d'achat q = 0,4616 porte l'étiquette **« règle de la v0.3, non validée »** : avec un prix de référence fixe, cette règle n'a pas pu être jugée de façon fiable.

## Fichiers

| Chemin | Contenu |
|---|---|
| `previsions/AAAA-MM-JJ.json` | La prévision du jour livré : pour chaque demi-heure, la prévision centrale, les quantiles 0,025, 0,1, 0,5, 0,9 et 0,975 et le volume au quantile q, en MW. Le fichier donne aussi les calculs météo utilisés, le niveau des 52 semaines, les empreintes du modèle et de la fourchette, et les champs de l'exécution. |
| `absences/AAAA-MM-JJ.json` | Un jour sans prévision, avec sa cause (une entrée manquait). |
| `meteo/run-AAAA-MM-JJ.csv` | L'indice national horaire du calcul ECMWF de 00 UTC de ce jour : température, nébulosité, vent et rayonnement, moyennes des 12 points du projet pondérées par la consommation régionale. |
| `niveau/AAAA-MM.json` | Le niveau des 52 semaines (une moyenne de consommation consolidée) de chaque jour livré dont la décision tombe dans ce mois. |

## Preuve qu'une prévision précède la consommation

Les dates des commits ne prouvent rien : elles se règlent à la main. Chaque fichier de prévision enregistre donc :

- l'identifiant de l'exécution du workflow (`execution.workflow_run_id`) et son heure de départ, lue par l'API de GitHub ;
- l'heure de fin de l'étape de prévision, lue de la même façon, et le statut qui en découle : « à l'heure » si elle précède midi, heure de Paris, la veille du jour livré, sinon « en retard » ;
- l'empreinte sha256 du contenu de prévision (`contenu_sha256`), aussi écrite dans le journal de l'exécution.

Limite : GitHub ne garde les journaux d'exécution que pendant une durée limitée. Passé ce délai, il reste la prévision, son empreinte et l'identifiant de l'exécution.

## Sources et licences

- **éCO2mix** (RTE, via la plateforme ODRÉ), sous Licence Ouverte 2.0 : seul le niveau des 52 semaines, une moyenne, en est tiré. Aucune série de consommation n'est publiée ici.
- **Open-Meteo**, calculs du modèle IFS d'ECMWF, sous licence CC BY 4.0 : indice national horaire tiré des données d'Open-Meteo (open-meteo.com).

Ce projet est indépendant : il n'est ni soutenu ni validé par RTE, ECMWF ou Open-Meteo.
