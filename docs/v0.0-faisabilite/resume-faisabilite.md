# Étude de faisabilité (v0.0) : résumé de travail

Ce résumé tient le journal daté des constats et des décisions de l'étude de faisabilité. Le rapport LaTeX de la v0.0 et l'ADR 0001 seront rédigés à partir de lui. Les mesures chiffrées sont dans `docs/v0.0-faisabilite/data/`.

## Indice national de température : choix de la pondération (14/11/2026)

La pondération des régions par leur consommation est retenue. Sur la validation croisée temporelle (années de test 2018 à 2023, poids recalculés à chaque pli sur les années antérieures), l'erreur absolue moyenne journalière vaut :

| Pondération | MAE moyenne (MW) |
|---|---|
| Consommation | 2 475 |
| Population | 2 486 |
| Hiver moins été | 2 508 |

La consommation gagne sur les six plis, mais l'écart est faible : 0,5 % face à la population et 1,3 % face à la pondération hiver moins été. Le choix de la pondération compte donc peu pour la suite. Détail : `data/indice-temperature-poids.json`.

## Points et météo (14/11/2026)

### Les 12 points

Chaque point est le centroïde (geo.api.gouv.fr) de la commune-centre de l'aire d'attraction des villes la plus peuplée de la région (INSEE, zonage 2020, géographie au 01/01/2026). La commune la plus peuplée n'a pas été retenue : en Normandie, ce serait Le Havre, sur la côte, alors que l'aire de Rouen est plus grande (715 000 contre 336 000 habitants) et à l'intérieur des terres.

Points : Paris, Lyon, Marseille, Lille, Toulouse, Bordeaux, Nantes, Strasbourg, Rennes, Rouen, Tours, Dijon. Le seul classement serré est Tours devant Orléans (529 000 contre 463 000 habitants). Limite : geo.api.gouv.fr n'indique pas le millésime de la population. Détail : `data/meteo-points-choix.json`.

### Requêtes

Les trois sources reçoivent les mêmes coordonnées exactes, la même altitude (fixée une fois par l'API d'altitude d'Open-Meteo), les mêmes variables, `timezone=GMT` et `cell_selection=land`. La conversion en heure de Paris se fait une seule fois, dans notre code, avec la règle des changements d'heure.

- Variables : température à 2 m, rayonnement solaire global, nébulosité totale, vent à 10 m, humidité relative à 2 m. Les cinq existent dans ERA5 et dans les calculs ECMWF archivés.
- Entraînement : ERA5, avec `models=era5` explicite. Par défaut, l'API historique combine IFS, ERA5 et ERA5-Land sans le signaler.
- Entrée réelle du modèle : calcul ECMWF IFS de 00 UTC de la veille.
- IFS 9 km de l'API historique : disponible depuis 2017, assemblé par Open-Meteo à partir des calculs de 0, 6, 12 et 18 UTC. Il est mesuré face à ERA5 sur la validation, sans assemblage des deux. On ne change de source qu'au vu de cette mesure.

### Essai et contrôle

Essai sur Paris (3 appels), puis contrôle sur les 12 points (37 appels) :

- Décompte : chaque réponse porte l'en-tête `X-RateLimit-Cost`. Il vaut 1,0 pour 14 jours × 5 variables en ERA5, comme pour un calcul ECMWF de 3 jours. L'appel d'altitude sur 12 points a coûté 12,0 : une requête sur plusieurs points compte un appel par point. Le service ne donne qu'un compteur par fenêtre de 60 secondes, aucun compteur journalier : le plafond journalier est tenu par un journal local.
- Convention du rayonnement : dans les 36 cas (12 points × 3 sources), la série suit le mieux la courbe théorique hors atmosphère calculée en moyenne de l'heure précédente, ce qui correspond à la documentation. Il n'y a pas de décalage d'une heure entre les sources.
- Mailles : les 36 centres de maille tombent sur une commune française. Pour IFS (9 km), ils sont à 1,3 à 5,5 km du point demandé ; pour ERA5 (25 km), à 4,7 à 14,2 km, sauf à Marseille. Limite : le centre de maille ne dit pas quelle part de mer contient la maille.
- Marseille, ERA5 : la maille retenue est centrée sur Rognac, à 26,6 km au nord du point, au bord de l'étang de Berre. La sélection terrestre d'Open-Meteo a écarté les mailles côtières. Rognac appartient à l'aire de Marseille - Aix-en-Provence. Le point est gardé tel quel ; l'écart entre ERA5 et ECMWF y sera surveillé en priorité.

Détail : `data/meteo-controle.json`.

### Appels et garde-fous

Estimation (5 variables, tranches de 14 jours, 1 appel par point et par tranche ou par calcul) :

| Source | Période | Appels |
|---|---|---|
| ERA5 | 2012-01-01 → 2026-10-31 | 4 644 |
| IFS historique | 2024-03-15 → 2025-08-31 | 468 |
| ECMWF 00 UTC | calculs du 2024-03-14 au 2026-11-13 | 11 700 |
| Altitude des 12 points | une requête | 12 |
| Total | | 16 824 |

Les 36 requêtes du contrôle sont les premières de chaque source : elles sont mises en cache et comptées dans les lignes ci-dessus. L'estimation donnée avant l'essai (≈ 16 860) comptait le contrôle à part.

Plafond local de 8 000 appels par jour UTC, une requête par seconde au plus, arrêt définitif au premier refus de quota (un fichier d'arrêt bloque tout appel tant qu'une personne ne l'a pas retiré), cache sur disque. Aucun appel en CI.

## Licences des données de prix (14/11/2026)

### Conditions de la plateforme ENTSO-E

Documents consultés le 14/11/2026 sur le centre d'aide de la plateforme de transparence ENTSO-E (article « Legal Terms and Conditions ») :

- conditions générales d'utilisation approuvées le 29/03/2023, applicables depuis le 01/11/2023, qui remplacent celles du 08/11/2018 (sha256 du PDF : `665d0862…d476352b`) ;
- liste des données librement réutilisables, version du 18/10/2023 (sha256 du PDF : `b21717e8…b708ff9a`).

Ce que disent ces documents :

- l'article 3.1 des conditions impose, pour tout usage, de citer la plateforme de transparence ENTSO-E comme source de publication, et interdit d'utiliser le nom ENTSO-E d'une manière qui laisserait croire à un parrainage ;
- les données de la liste sont sous licence CC BY 4.0 : copie, redistribution et adaptation pour tout usage, sans accord préalable du propriétaire de la donnée, à condition de citer la source et d'indiquer les modifications ;
- la liste exclut les données de Moldavie et de Turquie, certaines données d'Ukraine et de BritNed, et les données des interconnexions IFA (France-Angleterre) et Nemo Link. Aucune donnée de RTE n'est exclue ;
- l'utilisateur doit vérifier la liste avant chaque réutilisation. Elle sera donc relue avant chaque téléchargement, et sa version notée.

### Ce que cela permet

| Donnée | Article | Dans la liste | Usage dans le projet |
|---|---|---|---|
| Prix des écarts (ligne 27) | 17.1.g / 17.2.f | Oui | Prix des écarts du coût indicatif |
| Prévision J-1 de la consommation totale (ligne 1) | 6.1.b | Oui | Deuxième source possible pour la prévision J-1 de RTE |
| Prix du marché du lendemain | 12.1.d | Non (données des bourses) | Aucun, même pour un calcul local |

Mention de source retenue pour les prix des écarts :

> Source : ENTSO-E Transparency Platform, Imbalance Prices [17.1.G], zone de prix des écarts France, consulté le JJ/MM/AAAA. Données réutilisées sous licence CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/). Modifications : agrégation et calcul d'un coût indicatif. ENTSO-E ne parraine ni n'approuve ce projet.

### À vérifier sur la prévision J-1 de la plateforme (6.1.b)

Sur une période commune avec éCO2mix :

- est-ce la même série que la prévision J-1 d'éCO2mix, au même pas de temps ?
- une heure de publication est-elle disponible ?

Ces deux points demandent un jeton d'accès à l'API de la plateforme, donc un compte. Ils restent ouverts.

## Fonction de coût : options pour l'ADR 0001 (14/11/2026)

Le choix sera tranché dans l'ADR 0001, dans cet ordre :

1. Un prix moyen du marché du lendemain publié sous licence ouverte, par exemple les moyennes mensuelles de l'observatoire des marchés de la CRE. Licence et pas de temps à vérifier.
2. À défaut, les prix des écarts d'ENTSO-E et un prix de référence fixe, présenté comme une hypothèse.

Dans les deux cas, le coût en euros est indicatif. Les seuils de réussite du modèle restent exprimés en erreur (MAPE, couverture des intervalles), jamais en euros.

## Points encore ouverts

- Pas de règlement des écarts en France : non établi à partir d'une source officielle.
- Prix moyen du lendemain sous licence ouverte (CRE ou autre) : non vérifié.
- Prévision J-1 de la plateforme ENTSO-E : comparaison avec éCO2mix et heure de publication.
