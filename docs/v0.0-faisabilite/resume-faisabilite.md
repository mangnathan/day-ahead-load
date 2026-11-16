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

### Calculs ECMWF archivés : rejoués avant le 12/05/2026 (constat et décision du 14/11/2026)

- La documentation Single Runs d'Open-Meteo indique : « ECMWF IFS HRES at native 9 km resolution is available from March 14, 2024 (IFS Cycle 49R1 hindcasts). From May 12, 2026 06 UTC, runs use the updated IFS Cycle 50R1. »
- ECMWF a mis le cycle 49r1 en service opérationnel le 12/11/2024 et le cycle 50r1 le 12/05/2026 à partir du calcul de 06 UTC.
- Les calculs du 14/03/2024 au 11/11/2024 ne sont donc pas les prévisions émises à l'époque : ils ont été produits plus tard avec un cycle plus récent. Pour la période du 12/11/2024 au 12/05/2026, la documentation parle aussi de « hindcasts » sans dire si ce sont les sorties en temps réel. L'annonce d'Open-Meteo (15/05/2026) ne tranche pas non plus.
- Conséquences : sur la validation et le test, l'entrée météo est une prévision rejouée, qui peut être un peu meilleure que celle qu'aurait eue le fournisseur ; aucune heure de disponibilité réelle n'existe pour ces calculs ; un changement de cycle tombe dans la période de test (12/05/2026). À partir du 13/05/2026 à 00 UTC, les calculs utilisent le cycle opérationnel du moment. La documentation ne dit pas explicitement qu'il s'agit des sorties en temps réel, mais rien n'indique le contraire. Le test prospectif (à partir de septembre 2026) se trouve dans cette période.

Ordre de grandeur de l'avantage, d'après ECMWF (Newsletter 181, automne 2024, « IFS upgrade improves near-surface wind and temperature forecasts », doi 10.21957/crx2bn4is8) : face au cycle 48r1, le cycle 49r1 améliore le CRPS de la température à 2 m de 11 % à 1 jour d'échéance et de 2 % à 10 jours, et celui du vent à 10 m de 12 % à 1 jour et de 6 % à 10 jours. Ces chiffres portent sur la prévision d'ensemble, en hiver (75 prévisions du 01/12/2022 au 13/02/2023), en moyenne sur l'hémisphère nord, face aux observations. Ils ne s'appliquent pas tels quels à notre prévision déterministe aux 12 points. Le cycle 49r1 étant opérationnel du 12/11/2024 au 12/05/2026, cet écart de cycle ne concerne que les calculs rejoués du 14/03/2024 au 11/11/2024, c'est-à-dire le début de la validation. Pour la suite, le seul avantage possible tiendrait à la façon dont les calculs ont été rejoués, ce qui n'est pas établi.

Décisions (à reprendre dans l'ADR 0001) :

- Le test rétrospectif (09/2025 → 08/2026) reste la mesure principale de la v1.0. Il porte l'étiquette « météo prévue rejouée (cycle 49R1) sur environ 8 mois sur 12, avantage possible ». Ses résultats sont publiés aussi séparément avant et après le 13/05/2026.
- La comparaison avant/après le 13/05/2026 n'est pas présentée comme la mesure de l'avantage : elle mélange le changement de cycle et la saison. L'ordre de grandeur vient des scores d'ECMWF ci-dessus.
- Le test prospectif (à partir de septembre 2026) est la mesure réaliste, publiée ensuite mois par mois au fil des données consolidées. Il ne bloque pas la v1.0. La couverture des intervalles y sert de contrôle.
- La validation porte la même étiquette.
- Novembre 2024 → mai 2026 : « temps réel ou rejoué : non établi », tant qu'Open-Meteo n'a pas répondu.

Risque à inscrire au prémortem : calibrés sur une validation dont l'entrée météo est rejouée, les intervalles peuvent être trop étroits face à la prévision réellement disponible. Contrôle : leur couverture sur le test prospectif.

### Heure de disponibilité du calcul ECMWF : mesure quotidienne

- Point de métadonnées revérifié le 14/11/2026 : `https://api.open-meteo.com/data/ecmwf_ifs/static/meta.json` (documenté dans le dépôt open-data d'Open-Meteo sous la forme `data/<model>/static/meta.json`). Il ne décrit que le dernier calcul publié. À 17 h 51 UTC, c'était encore celui de 06 UTC, disponible à 12 h 40 min 55 s UTC (6,7 h après l'initialisation), avec une fin de données à J+6 et une mise à jour toutes les 6 h : c'est bien la prévision en temps réel. La réponse ne porte aucun en-tête de quota.
- Limite : l'heure mesurée est celle de l'API de prévision. La documentation Single Runs dit seulement que les calculs y sont disponibles « peu après » le dernier pas de temps publié.
- Workflow GitHub Actions planifié, séparé de la CI (`.github/workflows/disponibilite-ecmwf.yml`) : un appel par jour vers 10 h UTC, au plus un par jour, arrêt définitif au premier 429, ligne ajoutée à un CSV sur la branche `donnees/disponibilite-ecmwf`. La CI et les tests restent sans aucun appel réseau.

Constat du 16/11/2026 : depuis la machine de GitHub, l'API n'a répondu à aucune des trois tentatives de la journée (11 h 05 et 13 h 49 UTC), toutes arrêtées par un délai dépassé pendant l'établissement de la connexion sécurisée. Le même appel passe en local. Diagnostic lancé une fois le 16/11/2026 vers 13 h 58 UTC, depuis la machine de GitHub (workflow ponctuel sur une branche jamais mergée) :

- délai d'attente du script : 30 s, donc pas en cause ;
- `api.open-meteo.com` n'a qu'une adresse IPv4 (167.114.211.86) et aucune adresse IPv6 ; le témoin AWS n'a pas d'IPv6 non plus ;
- connexion forcée en IPv4 vers l'API : poignée de main TLS 1.3 complète et réponse 200 en 0,06 s ; vers le témoin AWS : réponse 200 en 0,2 s.

Conclusion : il n'y a pas de filtrage des adresses de GitHub. Le problème est intermittent : l'API a échoué à 11 h 05 et deux fois à 13 h 49, puis répondu à 13 h 58 depuis le même environnement. Il rejoint les deux coupures observées en local pendant le téléchargement. La cause la plus probable est le côté serveur d'Open-Meteo, qui n'expose qu'une adresse, mais ce n'est pas établi. La parade est la nouvelle tentative et la lecture AWS en complément ; le taux d'échec de l'API est suivi dans le CSV, et la question n'entre dans les points ouverts de l'ADR que s'il reste élevé.

Choix (16/11/2026) : deux sources lues chaque jour, dans la même ligne, avec le statut de chacune.

- L'API (`api.open-meteo.com`) reste la référence : c'est là que notre chaîne lit la prévision, et son heure est donc celle qui compte pour la règle de midi.
- La copie publique d'Open-Meteo sur AWS (`openmeteo.s3.amazonaws.com`) est lue en complément permanent. Son heure est celle du dépôt des fichiers, un peu plus tôt que la disponibilité sur l'API : 12 h 01 contre 12 h 40 UTC pour le calcul de 06 UTC du 14/11/2026 (environ 40 min), 12 h 01 contre 12 h 55 UTC pour celui du 16/11/2026 (53,7 min, mesure locale).
- Les jours où les deux répondent sur le même calcul, l'écart est mesuré. Les jours sans API, l'heure retenue est l'heure AWS plus le plus grand écart observé, présentée comme une estimation.
- Ce qui compte pour la règle de midi est la marge restante, de l'ordre de 3 h 30 à 4 h 30 pour le calcul de 00 UTC : un écart de 40 à 55 min entre les deux sources ne la menace pas.

### Appels et garde-fous

Bilan au 16/11/2026 : 16 827 appels décomptés pour 16 824 estimés, en trois séances (7 269, 8 000 et 1 558), zéro refus de quota. Les 3 appels de plus sont des tentatives coupées, comptées par prudence. Le contrôle de la maille de Marseille a ensuite ajouté 402 appels, estimés avant le lancement.

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

## Pas de règlement des écarts et règle de passage (14/11/2026)

Source officielle : CRE, consultation publique n° 2025-01 du 13 mars 2025, relative à l'adaptation des contrats de complément de rémunération au pas de temps 15 minutes (sha256 du PDF : `91787af4…3d5a2dd1`). Elle indique : « le pas de temps de règlement des déséquilibres ou "écarts" (ISP, Imbalance Settlement Period) est passé de 30 à 15 minutes le 1er janvier 2025 ». Le pas du marché du lendemain est passé à 15 minutes pour la livraison du 01/10/2025 (vérifié plus tôt sur le site du comité des bourses européennes).

Conséquence : la validation (03/2024 → 08/2025) chevauche le changement de pas. Avant le 01/01/2025, il y a un prix des écarts par demi-heure ; à partir de cette date, deux par demi-heure.

Règle de passage entre nos demi-heures et ce pas :

- La consommation cible (consolidée ou définitive) et notre prévision sont des puissances moyennes sur la demi-heure.
- Chaque demi-heure se partage en deux quarts d'heure qui reçoivent la même puissance moyenne. L'énergie d'un quart d'heure vaut cette puissance multipliée par 0,25 h.
- L'écart d'un quart d'heure est la différence entre la consommation et la prévision. Les deux quarts d'heure d'une même demi-heure ont donc le même écart en énergie, mais chacun reçoit son propre prix des écarts.
- Avant le 01/01/2025, une demi-heure a un seul écart (puissance × 0,5 h) et un seul prix.
- Limite : les variations à l'intérieur d'une demi-heure ne sont pas vues, ce qui sous-estime un peu les écarts réels.

## Prix de référence du lendemain : hypothèse fixe (14/11/2026)

Aucune série de prix du lendemain sous licence claire n'a été trouvée dans la séance consacrée à la question :

- les prix du lendemain de la plateforme ENTSO-E (12.1.d) appartiennent aux bourses et sont exclus de la liste des données réutilisables ;
- la rubrique Open Data de la CRE (observatoires des marchés de gros) ne propose que des données jusqu'au 4e trimestre 2020, mises à jour le 10/02/2022, sans licence indiquée.

L'option 2 est donc retenue : un prix de référence fixe, présenté comme une hypothèse. Il doit venir d'une moyenne annuelle publiée dans un rapport public. Valeur retenue le 15/11/2026 : 61,1 €/MWh, prix day-ahead moyen en France en 2025 (CRE, « La surveillance et le fonctionnement des marchés de gros de l'électricité et du gaz naturel en 2025 », rapport n° 2026-07 du 17 juin 2026, tableau 13, qui donne aussi 57,8 €/MWh pour 2024). La valeur de 60 €/MWh proposée la veille n'était publiée nulle part et a été abandonnée. Sensibilité à 40 et 100 €/MWh. Le coût en euros reste indicatif.

## Écart entre sources météo sur la validation (16/11/2026)

Téléchargement terminé le 16/11/2026 : 16 827 appels comptés en trois séances (7 269, 8 000 et 1 558), pour une estimation de 16 824 ; l'écart vient des tentatives coupées, comptées par prudence. Aucun refus de quota.

Mesure sur la validation (15/03/2024 → 31/08/2025, 535 jours) : pour chaque jour J à Paris, prévision = calcul ECMWF de 00 UTC de J-1, échéances 22 à 47 h. Les calculs de cette période sont rejoués (cycle 49R1). Détail : `data/meteo-ecart-sources.json`.

Indice national de température (pondération par la consommation), en °C, sur 12 839 heures :

| Comparaison | Erreur absolue moyenne | Biais | Écart-type |
|---|---|---|---|
| Prévision face à ERA5 | 0,67 | -0,14 | 0,85 |
| Prévision face à IFS historique | 0,39 | +0,17 | 0,50 |
| ERA5 face à IFS historique | 0,61 | +0,31 | 0,72 |

Par point, température à 2 m : la prévision est plus proche d'IFS historique que d'ERA5 aux 12 points (0,63 à 0,80 °C contre 0,88 à 1,68 °C). L'écart avec ERA5 est le plus grand à Marseille (1,68 °C), où la maille ERA5 est décalée de 26,6 km, puis à Lyon (1,31 °C) et à Strasbourg (1,20 °C). Les autres variables vont dans le même sens, avec des écarts plus faibles pour le rayonnement et la nébulosité.

Lecture : IFS historique est assemblé à partir du même modèle que la prévision. Il est plus cohérent avec l'entrée du modèle, ce qui ne prouve pas qu'il donnerait une meilleure prévision de consommation. L'écart entre ERA5 et IFS historique (0,61 °C) montre que les deux « météos observées » diffèrent déjà nettement, surtout par la résolution (25 km contre 9 km). La source d'entraînement n'est pas changée à ce stade : la question est tranchée en v0.1, par la mesure décrite dans les points ouverts.

Ordre de grandeur : ERA5 est en moyenne 0,31 °C plus chaud qu'IFS historique sur l'indice. Avec une sensibilité de 2 313 à 2 345 MW par degré sous 15 °C, cela représente environ 720 MW en hiver : un modèle entraîné sur ERA5 et nourri par une prévision proche d'IFS pourrait garder un biais de cet ordre. Ce risque chiffré est inscrit au prémortem.

### Maille ERA5 de Marseille (16/11/2026)

Le contrôle terrestre est passé : le centre de maille (43,50 ; 5,25) tombe sur Rognac. Mais ce contrôle ne voit pas l'étang de Berre, car les contours des communes l'incluent (un point au milieu de l'étang tombe sur Berre-l'Étang). La part d'eau a donc été estimée à part, avec l'altitude du modèle de terrain Copernicus GLO-90 servi par Open-Meteo, sur une grille de 20 × 20 points couvrant la maille (402 appels décomptés, points témoins compris) :

- les témoins sont bien vus comme de l'eau : -2 m au milieu de l'étang, 0 m dans la rade de Marseille ;
- au plus 10,5 % des points sont à 0,5 m ou moins (borne haute, une terre très basse comptant comme eau) ;
- l'altitude médiane est de 128 m, contre 58 m pour le point de Marseille.

La maille n'est donc pas dominée par l'eau. Sa limite est autre : elle représente surtout l'arrière-pays, de Rognac vers Aix-en-Provence, plus haut et plus continental que Marseille, ce qui explique probablement l'écart de 1,68 °C. Noté pour la v0.1 : la variante C (ERA5 corrigé vers IFS par point, mois et heure) corrige la part systématique de cet écart ; les résidus de Marseille seront regardés à part. Détail : `data/marseille-maille-era5.json`.

## Points encore ouverts

- Source d'entraînement : tranchée en v0.1 par la comparaison de trois variantes, entraînées avec le même modèle et comparées sur la MAPE de la validation, avec la météo prévue en entrée :
  - A, ERA5 brut ;
  - B, IFS historique (2017 → 2024-03) ;
  - C, ERA5 corrigé vers IFS : écart moyen par point, par mois et par heure, calculé sur la période commune 2017 → 2024-03-14, dans l'entraînement seulement, puis appliqué à tout ERA5. Cette variante garde les années 2012 à 2016.
  Pour comparer à durée égale, A et C sont aussi entraînés sur 2017 → 2024-03-14. Le gain des années 2012 à 2016 est mesuré à part.
- Prévision J-1 de la plateforme ENTSO-E (6.1.b) : comparaison avec éCO2mix et heure de publication (compte ENTSO-E reporté).
