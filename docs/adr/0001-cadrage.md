# ADR 0001 : utilisateur, données, découpage et critères de succès

- Statut : accepté
- Date : 15 novembre 2026
- Version : v0.0

## Contexte

Le projet prévoit la consommation électrique française du lendemain, par demi-heure, avec son incertitude. Il traduit ensuite l'erreur en une décision d'achat et en un coût pour un fournisseur.

Ces règles sont écrites et versionnées avant toute modélisation, pour que les seuils ne puissent pas être choisis après avoir vu les résultats. Les chiffres cités viennent des scripts de `scripts/feasibility` et de leurs sorties dans `docs/v0.0-faisabilite/data`. Le journal daté des constats est dans `docs/v0.0-faisabilite/resume-faisabilite.md`, la décision de go dans `docs/v0.0-faisabilite/go-no-go.md`.

## Décisions

### Un fournisseur représentatif, qui décide à midi la veille

L'utilisateur est un fournisseur qui achète la veille l'énergie de ses clients pour le lendemain. Son portefeuille est le profil national multiplié par une part de marché s. C'est une hypothèse de modélisation : le portefeuille d'un vrai fournisseur n'est pas public. Les erreurs en pourcentage ne dépendent pas de s, les euros lui sont proportionnels, et un vrai portefeuille est plus bruité que le total national.

La décision est prise à **midi, heure de Paris, la veille** du jour livré. Seules les données publiées avant cette heure peuvent entrer dans une prévision.

### La cible : la consommation consolidée ou définitive, par demi-heure

- Grandeur : consommation nationale d'éCO2mix (RTE, via ODRÉ, Licence Ouverte 2.0), puissance moyenne sur la demi-heure, au pas de 30 minutes. C'est le seul pas renseigné sur tout l'historique.
- Natures retenues : définitives (2012 à 2025) et consolidées (depuis janvier 2026). Le temps réel ne sert jamais de cible : RTE le décrit comme une puissance instantanée, et le biais de la prévision de RTE change de signe exactement quand la nature passe au temps réel (septembre 2026).
- Heure : les instants sont reconstruits à partir de la date et de l'heure locales, car l'horodatage UTC d'ODRÉ est faux les jours de changement d'heure. Les deux heures de 2 h d'octobre sont exclues comme ambiguës.

### Ce qui est disponible à midi

- Consommation consolidée : un mois M est considéré comme disponible le 1er du mois M+3. C'est une règle prudente tirée d'une observation datée : le 14/11/2026, le consolidé s'arrêtait au 31/08/2026, alors que la documentation annonce la mi-M+1.
- Météo prévue : le calcul ECMWF IFS 9 km de 00 UTC de la veille (Open-Meteo, Single Runs API). Le calcul de 06 UTC du 14/11/2026 était disponible 6,7 h après son lancement ; celui de 00 UTC l'est donc vers 6 h 40 UTC, plusieurs heures avant midi. L'heure de disponibilité est mesurée chaque jour par un workflow séparé de la CI.
- Prévision J-1 de RTE : publiée après midi. Toute référence qui l'utilise est étiquetée « avantagée ».

### Météo

- Points : le centroïde de la commune-centre de l'aire d'attraction des villes la plus peuplée de chaque région (INSEE, zonage 2020), soit 12 points.
- Variables : température à 2 m, rayonnement solaire global, nébulosité totale, vent à 10 m, humidité relative à 2 m.
- Requêtes : mêmes coordonnées, même altitude fixée, mêmes variables, `timezone=GMT` et `cell_selection=land` pour toutes les sources. La conversion en heure de Paris se fait une seule fois, dans le code.
- Entraînement : ERA5, avec `models=era5` explicite. La série IFS historique est mesurée face à ERA5 sur la validation, sans assemblage des deux ; la source d'entraînement ne change qu'au vu de cette mesure.
- Indice national de température : moyenne des 12 points pondérée par la part de chaque région dans la consommation. L'écart avec les autres pondérations testées est faible (0,5 % face à la population, 1,3 % face à hiver moins été) : le choix compte peu.

### Étiquettes

Chaque résultat publié porte une étiquette.

| Étiquette | Sens |
|---|---|
| Réaliste | N'utilise que des données disponibles à midi la veille |
| Optimiste | Respecte l'heure de midi, mais lit des données consolidées que le fournisseur n'aurait pas encore (naïf J-7, J-2) |
| Avantagée | Utilise la prévision J-1 de RTE, publiée après la décision, même corrigée de son biais |
| Borne | Enfreint volontairement les règles, pour mesurer ce qu'elles coûtent |
| Météo prévue rejouée | Entrée météo issue des calculs ECMWF archivés avant le 13/05/2026, décrits comme des « hindcasts » du cycle 49R1 ; avantage possible |

Les calculs du 14/03/2024 au 11/11/2024 ont été rejoués avec un cycle devenu opérationnel plus tard (12/11/2024). Pour la période du 12/11/2024 au 12/05/2026, « temps réel ou rejoué » n'est pas établi. Ordre de grandeur de l'avantage d'un cycle sur l'autre, d'après ECMWF (Newsletter 181) : le passage de 48r1 à 49r1 améliore le CRPS de la température à 2 m de 11 % à 1 jour, et celui du vent à 10 m de 12 %, en prévision d'ensemble, en hiver, sur l'hémisphère nord.

### Alignement de la prévision de RTE, figé

La prévision J-1 de RTE est au pas de 15 minutes, la cible au pas de 30 minutes. Mesuré sur les données définitives (erreur absolue moyenne, en MW) :

| Année | f(t) | f(t-15) | Moyenne de f(t-15) et f(t) |
|---|---|---|---|
| 2015 | 757 | 829 | 737 |
| 2019 | 788 | 836 | 760 |
| 2022 | 973 | 965 | 927 |
| 2024 | 1 364 | 1 273 | 1 295 |
| 2025 | 1 324 | 1 211 | 1 241 |

La meilleure version change selon les années. L'alignement principal est **la moyenne de f(t-15) et de f(t)**, jamais pire que la deuxième. Il est figé le 14/11/2026 et ne changera plus. f(t) et f(t-15) sont publiés comme sensibilité : le rapport du critère de go varie de 3,58 à 3,68, avec la même conclusion. L'alignement ne concerne que les références fondées sur RTE.

### Découpage dans le temps

| Période | Dates | Météo en entrée |
|---|---|---|
| Entraînement | 2012-01-01 → 2024-03-14 | Observée (ERA5) |
| Validation | 2024-03-15 → 2025-08-31 | Prévue (calcul de 00 UTC de la veille, rejoué) |
| Test rétrospectif | 2025-09-01 → 2026-08-31 | Prévue (rejouée sur environ 8 mois sur 12) |
| Test prospectif | À partir du 2026-09-01 | Prévue (calculs de cycle 50r1, depuis le 13/05/2026) |

- **Réentraînement mensuel sur le test.** Au début de chaque mois du test, le modèle est réentraîné sur toutes les données disponibles à cette date, avec la même règle de délai du consolidé (fenêtre croissante). La procédure est figée avant d'ouvrir le test : famille de modèle, réglages choisis en validation, règle de calibration.
- **Calibration des intervalles.** Elle utilise les résidus des 12 derniers mois disponibles, calculés avec la météo prévue.
- **Test ouvert une seule fois.** Les données du test sont figées (sha256 et date de téléchargement) avant l'ouverture, qui demande un accord explicite.
- **Test prospectif.** Le modèle est figé à un commit noté avant la publication du consolidé des mois concernés. Il est évalué une fois, mois par mois, au fil de la publication du consolidé.

## Critères de succès

Le test rétrospectif est la mesure principale de la v1.0, avec l'étiquette « météo prévue rejouée (cycle 49R1) sur environ 8 mois sur 12, avantage possible ». Ses résultats sont publiés aussi séparément avant et après le 13/05/2026. Cette comparaison n'est pas présentée comme la mesure de l'avantage : elle mélange le changement de cycle et la saison. Le test prospectif est la mesure réaliste, publiée ensuite mois par mois. Il ne bloque pas la v1.0.

| Critère, sur le test rétrospectif | Réussite | Échec |
|---|---|---|
| Prévision ponctuelle : MAPE par demi-heure | Au plus 0,5 × la MAPE du naïf J-7 sur le même test | Plus de 0,75 × la MAPE du naïf J-7 |
| Intervalles : couverture | Intervalle à 80 % couvrant entre 75 et 85 %, **et** intervalle à 95 % couvrant entre 92 et 98 % | Une des deux couvertures hors de sa plage |
| Intervalles : score quantile (pinball moyen aux niveaux 0,025, 0,1, 0,5, 0,9 et 0,975) | Meilleur que celui de la référence de quantiles | Égal ou moins bon |
| Décision | Coût de l'achat au quantile choisi inférieur au coût de l'achat égal à la prévision ponctuelle | Égal ou supérieur |

- Les deux conditions sur les intervalles doivent être réunies.
- Entre 0,5 et 0,75 × la MAPE de J-7, le résultat est publié comme insuffisant, sans être un échec.
- Le naïf J-7 est **optimiste** : la consommation de J-7 n'est pas consolidée à midi la veille. Le seuil est donc plus dur qu'avec une référence réaliste.
- **Référence de quantiles** : la valeur du naïf J-7, plus les quantiles empiriques des erreurs passées de J-7 par demi-heure de la journée, calculés sur les 12 derniers mois de consolidé disponibles à midi la veille.
- **Publication complémentaire** : MAPE par trimestre ; couverture par saison et par tranche horaire.
- **Écart à RTE** : mesuré et publié face aux prévisions J-1 brute et corrigée, étiquetées « avantagées ». Il n'est jamais visé et ne fait pas partie des critères.
- Le coût en euros est un résultat indicatif, jamais un seuil.

## Fonction de coût

Pour chaque période de règlement k, de 30 minutes avant le 01/01/2025 et de 15 minutes ensuite (CRE, consultation publique n° 2025-01 du 13/03/2025) :

- Passage des demi-heures aux quarts d'heure : chaque demi-heure se coupe en deux quarts d'heure de même puissance moyenne. Énergie d'une période = puissance × durée de la période. Limite : les variations à l'intérieur d'une demi-heure ne sont pas vues.
- Écart : Δk = s × (consommation − achat), en MWh.
- Coût de l'écart face à un achat parfait :
  - si Δk > 0 (le fournisseur est court), Δk × (prix des écarts du sens « court » − P_ref) ;
  - si Δk < 0 (il est long), |Δk| × (P_ref − prix des écarts du sens « long »).
- Coût total : somme sur les périodes. Il peut être négatif sur une période où le prix des écarts est favorable.

Paramètres :

- Prix des écarts : ENTSO-E Transparency Platform, Imbalance Prices [17.1.G], zone France, réutilisés sous licence CC BY 4.0, avec la mention de source fixée dans le résumé de faisabilité. La liste des données réutilisables est relue avant chaque téléchargement.
- Prix de référence P_ref : **61,1 €/MWh**, prix day-ahead moyen en France en 2025 (CRE, « La surveillance et le fonctionnement des marchés de gros de l'électricité et du gaz naturel en 2025 », rapport n° 2026-07 du 17 juin 2026, tableau 13 ; sources EPEX SPOT et Nord Pool, analyse CRE). C'est une hypothèse fixe ; sensibilité à 40 et 100 €/MWh.
- Quantile d'achat : choisi sur la validation à partir des pénalités moyennes, q = pénalité courte / (pénalité courte + pénalité longue), puis figé avant le test.
- Part de marché s : les erreurs en pourcentage n'en dépendent pas ; les euros sont publiés pour s = 1 % et proportionnels à s.

## Transparence

- Les références naïves ont été mesurées sur la période du 2024-03-15 au 2026-08-31, qui inclut le test. C'est sans effet sur l'évaluation : ce sont des règles fixes, sans paramètre ajusté.
- Le choix de l'alignement de RTE a utilisé l'année 2025, qui appartient en partie au test. C'est sans effet sur le modèle, qui ne dépend pas de cet alignement, et prudent, puisqu'il porte sur une référence.
- Le consolidé de septembre et d'octobre 2026 sera vérifié vers le 15/12/2026, pour confirmer que la rupture du biais de RTE vient du passage au temps réel.

## Points ouverts, sans effet sur la v0.0

| Point | Ce qui le ferme |
|---|---|
| Panier de 32 stations de RTE | Seulement si les résidus régionaux montrent un écart dû aux 12 points |
| Prévision J-1 de la plateforme ENTSO-E (6.1.b) face à éCO2mix, et son heure de publication | Compte ENTSO-E |
| Calculs ECMWF de novembre 2024 à mai 2026 : temps réel ou rejoués | Réponse d'Open-Meteo |
| Source d'entraînement : ERA5 ou IFS historique | Mesure de l'écart sur la validation, montrée avant tout changement |
| Prévision J-2 de RTE : première version ou version révisée dans l'historique | Compte RTE (champ `updated_date`) |
| Rupture du biais de RTE en septembre 2026 | Consolidé de septembre et d'octobre 2026, vers le 15/12/2026 |
| Plan gratuit AWS sans carte | Essai au début de la phase AWS ; LocalStack si une carte est demandée |

## Alternatives écartées

| Option | Raison |
|---|---|
| Analyste de marché comme utilisateur | Mélange deux métiers : l'analyste anticipe les prix, le fournisseur achète un volume |
| Temps réel comme cible | Puissance instantanée, autre grandeur ; pas d'historique |
| Battre RTE comme objectif | RTE publie après la décision ; l'écart est mesuré, pas visé |
| Prix du lendemain ENTSO-E (12.1.d) | Propriété des bourses, hors de la liste des données réutilisables |
| ERA5 et IFS historique assemblés | Créerait une rupture cachée |
| Météo observée bruitée à la place de la météo prévue | Remplace un biais connu par une hypothèse sur la taille du bruit |

## Conséquences

- La v0.1 construit les variables (calendrier, météo prévue, valeurs assez anciennes pour être consolidées) et les références sous la règle de midi, avec des tests sur l'heure de décision.
- La source d'entraînement est tranchée par la mesure de l'écart entre sources sur la validation.
- Aucune valeur du test n'est lue avant l'accord explicite d'ouverture.
