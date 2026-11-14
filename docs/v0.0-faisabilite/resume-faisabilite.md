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
