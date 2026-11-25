# ADR 0005 : décision d'achat de la v0.3

- Statut : proposé le 25/11/2026, à accepter à la relecture du rapport de la v0.3
- Date : 25 novembre 2026
- Version : v0.3

## Contexte

L'ADR 0001 fixe le dernier critère de réussite : acheter au quantile q du vendeur de journaux doit coûter moins cher qu'acheter la prévision ponctuelle. q se calcule à partir des pénalités d'un écart, c'est-à-dire des prix de règlement des écarts de RTE comparés à un prix de référence fixe P_ref de 61,1 €/MWh. Ce critère se juge sur le test, en v1.0. La v0.3 estime q et mesure le coût sur la validation, sans rien changer à la prévision (ADR 0003 et 0004).

Les règles ont été écrites dans le journal des choix avant tout calcul (entrées 24 et 25), et les résultats y sont notés (entrée 26). Code : `src/day_ahead_load/entsoe.py`, `decision.py` ; calculs : `scripts/decision/` ; résultats : `docs/v0.3-decision/data/decision-achat.json`.

## Correction de l'ADR 0001 : les prix des écarts restent doubles

L'ADR 0001 prévoyait d'estimer q « uniquement sur la partie de la validation postérieure au passage au régime d'écart unique (05/10/2024) ». Le chapitre 3 des Règles de marché de RTE (« Dispositif de Responsable d'Équilibre », version en vigueur au 4 juillet 2026) montre que ce changement porte sur autre chose : à compter du 5 octobre 2024, les processus Écarts et Réconciliation Temporelle de la reconstitution des flux sont fusionnés en « un processus unique Ecarts ». Ce n'est ni un prix unique ni une position unique, mais un changement de traitement des données de comptage. L'ADR 0001 l'a pris pour un changement de prix.

Les prix restent doubles : un prix pour le fournisseur long (PRE positif) et un autre pour le fournisseur court (PRE négatif). C'est ce que disent la section 3.M.1 du même chapitre et la page de RTE sur le prix de règlement des écarts (« Le PRE positif ne peut pas être supérieur au PRE négatif »). Les données d'ENTSO-E le confirment : les deux prix diffèrent dans plus de 99,7 % des périodes, et le prix payé au fournisseur long n'est jamais supérieur au prix payé par le fournisseur court, sur 73 043 périodes de mars 2024 à août 2026.

L'ADR 0001 n'est pas réécrit : cette section le corrige.

## Décision

**Données.** ENTSO-E Transparency Platform, Imbalance Prices [17.1.G], zone France, du 15/03/2024 au 31/08/2026, réutilisés sous licence CC BY 4.0. Le téléchargement a fait 31 appels sur un plafond local de 100 par jour, sans aucun refus. Le jeton d'accès est lu dans `.env`, et un test vérifie qu'il n'apparaît dans aucun fichier écrit, aucune sortie ni aucun message d'erreur. Le règlement se fait à la demi-heure jusqu'au 31/12/2024, puis au quart d'heure à partir du 01/01/2025, heure de Paris.

**Rattachement.** La demi-heure étiquetée t couvre (t − 15 min, t + 15 min]. Elle se coupe en deux quarts d'heure, qui commencent à t − 15 min et à t, chacun réglé au prix de sa période de règlement. Un quart d'heure sans prix est retiré des deux stratégies à la fois.

**Formule de q (précision de l'ADR 0001).** La pénalité courte Cu est la moyenne de (PRE négatif − P_ref) sur les quarts d'heure où la prévision ponctuelle laissait le fournisseur court. La pénalité longue Co est la moyenne de (P_ref − PRE positif) sur ceux où elle le laissait long. q = Cu / (Cu + Co). Si Cu ou Co n'est pas strictement positif, la règle ne s'applique pas, et l'achat reste la prévision ponctuelle. q est estimé du 01/01 au 31/08/2025, avec les règles du test (deux prix, pas de 15 minutes). L'achat au quantile q suit Q1 (ADR 0004).

## Résultat sur la validation

Pour une part de marché de 1 % et P_ref = 61,1 €/MWh :

- q = 0,46 (Cu = 10,97 €/MWh, Co = 12,80 €/MWh) ;
- coût de l'achat à la prévision ponctuelle : 1 015 766 € ; au quantile q : 1 015 166 € ;
- différence : −599 €, intervalle à 95 % de −123 888 € à +136 687 € (par MWh consommé : de −0,042 € à +0,047 €) ;
- avec P_ref = 40 ou 100 €/MWh, une des deux pénalités devient négative, et la règle ne s'applique pas.

Avec un prix de référence fixe, la règle du vendeur de journaux ne peut pas être jugée de façon fiable. Le signe des pénalités dépend de cette hypothèse, puisque 61,1 €/MWh tombe entre les moyennes des deux prix d'écart (54,2 et 64,1). Le coût réel d'un écart se mesure face au prix du marché de la veille de la même période, qui n'est pas disponible sous licence ouverte.

## Conséquences

- **Une prédiction écrite avant le test** : le critère de décision a de fortes chances d'être indiscernable, ou d'échouer, pour les raisons ci-dessus. Le critère de l'ADR 0001 ne change pas.
- q est figé à 0,4616 pour le test, avec P_ref = 61,1 €/MWh, comme le prévoit l'ADR 0001.
- Le compteur des comparaisons faites sur la validation reste à 13 : q vient d'une formule fixée d'avance, sans choix entre options.

## Points ouverts

- **Une correction du biais qui tienne compte de son retard et des saisons.** Q1 recentre déjà sur la médiane des résidus passés, et il reste +311 MW de biais sur q0,5. Ce biais dérive de +1 017 MW en mars à −1 140 MW en juillet 2025, et le recentrage de Q1 (de −80 à +108 MW) ne le suit pas. Une correction serait une nouvelle comparaison, comptée, à décider plus tard.
- **Le prix de référence.** Chercher une source du prix du marché de la veille sous licence ouverte ; sinon, garder la limite.
- **q instable d'un mois à l'autre** : non défini cinq mois sur huit, de 0,001 à 0,78 les autres mois.
- Le coefficient k du prix des écarts varie chaque mois par construction ; ses valeurs mensuelles n'ont pas été lues.
