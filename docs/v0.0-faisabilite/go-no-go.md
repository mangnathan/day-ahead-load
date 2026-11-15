# Étude de faisabilité (v0.0) : décision de go ou de no-go

Rédigé le 14/11/2026, avant toute modélisation. Les chiffres viennent des scripts de `scripts/feasibility` et de leurs sorties dans `docs/v0.0-faisabilite/data/` ; le détail daté des constats est dans `resume-faisabilite.md`.

## 1. Les dix questions de Cagan

| # | Question | Réponse |
|---|---|---|
| 1 | Quel problème ? | Un fournisseur achète la veille, avant midi, l'énergie que ses clients consommeront le lendemain. Chaque MWh d'erreur est réglé au prix des écarts. Il lui faut une prévision par demi-heure de la consommation du lendemain, avec son incertitude, construite seulement avec les données disponibles à midi. |
| 2 | Pour qui ? | Un fournisseur représentatif, dont le portefeuille est le profil national multiplié par une part de marché s. C'est une hypothèse de modélisation : le portefeuille d'un vrai fournisseur n'est pas public. Les erreurs en pourcentage ne dépendent pas de s ; les euros lui sont proportionnels. Un vrai portefeuille est plus bruité que le total national. |
| 3 | Quelle taille ? | La consommation française corrigée de la température était de 446,6 TWh en 2025 (CRE, communiqué du 25 juin 2026). L'enjeu en euros sera calculé avec la fonction de coût de l'ADR 0001 ; il reste indicatif, avec un prix de référence fixe. |
| 4 | Quelles alternatives ? | Le naïf J-7 (même demi-heure une semaine avant) : 6,19 % de MAPE sur 2024-03-15 → 2026-08-31. La prévision J-1 de RTE : 2,60 % brute, 1,69 % corrigée de son biais, mais publiée après midi, donc « avantagée ». La prévision J-2 de RTE (API Consumption, appel conseillé vers 7 h) : à mesurer, compte RTE nécessaire. Les prestataires commerciaux, payants et non comparables publiquement. |
| 5 | Pourquoi ce projet ? | Il ajoute ce que la référence publique ne donne pas : une bande d'incertitude calibrée, une prévision qui respecte l'heure de décision, une traduction en coût, et une évaluation publique dont chaque avantage est étiqueté (réaliste, optimiste, avantagée, borne). |
| 6 | Pourquoi maintenant ? | Le pas de règlement des écarts est passé à 15 minutes le 01/01/2025 et le pas du marché du lendemain le 01/10/2025. Le biais de la prévision J-1 de RTE grandit depuis 2022 (environ -1 100 MW en 2023-2024, surtout entre 13 h et 16 h). Les calculs ECMWF 9 km archivés depuis le 14/03/2024 rendent possible un test sur une météo prévue. |
| 7 | Comment l'utilisateur la reçoit ? | Une prévision chaque jour avant midi, par API et sur un tableau de bord. Le tableau de bord ne montre que nos erreurs comparées, jamais les courbes de RTE (CGU de RTE, art. 7.1). |
| 8 | Comment mesurer le succès ? | En erreur, pas en euros : MAPE sur le test au moins deux fois plus faible que celle du naïf J-7 ; couverture des intervalles proche de leur niveau nominal ; écart à RTE mesuré et publié, jamais visé. Seuils fixés dans l'ADR 0001. |
| 9 | Facteurs critiques | La météo prévue disponible avant midi (calcul de 06 UTC disponible 6,7 h après son lancement, une mesure ; mesure quotidienne mise en place). Le décalage du consolidé (règle prudente M+3). L'indice national de température (12 points). Les changements d'heure. L'absence de tout appel réseau en CI. |
| 10 | Recommandation | Go dégradé, voir la partie 3. |

## 2. Prémortem

On suppose que le projet a échoué, et on cherche pourquoi.

| Risque | Ce qui se passerait | Parade |
|---|---|---|
| Pas de valeurs récentes | À midi, le consolidé s'arrête trois mois avant. Le modèle v0 ne voit pas la consommation de la veille et rate les écarts de niveau récents (sobriété, crise des prix). | Modèle v0 sans valeurs récentes : calendrier, météo prévue, valeurs assez anciennes pour être consolidées. Les références J-2 et J-7 sont étiquetées « optimistes ». Le temps réel, s'il est archivé un jour, sera étudié à part. |
| Météo rejouée | Sur la validation et 8 mois du test, l'entrée météo est un calcul rejoué (cycle 49R1). Les erreurs et les intervalles calibrés dessus sont trop flatteurs. | Étiquette « météo prévue rejouée (cycle 49R1), avantage possible ». Résultats publiés aussi avant et après le 13/05/2026. Ordre de grandeur par les scores d'ECMWF. Couverture des intervalles contrôlée sur le test prospectif. |
| Intervalles trop étroits | Calibrés sur une météo rejouée, ils couvrent moins que leur niveau nominal en conditions réelles. | Calibration sur les résidus des 12 derniers mois calculés avec la météo prévue ; contrôle de la couverture sur le test prospectif, publiée mois par mois. |
| Consolidé contre temps réel | Le biais de RTE change de signe en septembre 2026, au moment où la nature passe au temps réel. Une comparaison sur le temps réel ne mesure pas la même grandeur. | Cible : consolidé et définitif seulement. Le temps réel ne sert jamais de cible. Vérification vers le 15/12/2026, quand le consolidé de septembre et octobre 2026 sera publié. |
| Modèle moins bon que RTE corrigé | Le modèle reste au-dessus de 1,69 % de MAPE, ce qui semble un échec. | L'objectif n'est jamais de battre RTE : l'écart est mesuré et publié. RTE J-1 est publiée après la décision (« avantagée »). Le seuil de réussite porte sur le naïf J-7 et sur la couverture. |
| Coût en euros indicatif | Un lecteur prend le coût pour un gain réel. | Prix de référence fixe présenté comme une hypothèse, analyse de sensibilité, portefeuille représentatif écrit comme hypothèse. Les seuils restent en erreur. |
| Quantile d'achat proche de 0,5 | Si les pénalités courte et longue sont voisines, acheter au quantile revient presque à acheter la prévision ponctuelle : l'incertitude n'apporte presque rien à la décision d'achat. | Calculer q dès que les prix des écarts sont disponibles (v0.1, compte ENTSO-E). Si q est proche de 0,5, l'écrire : la valeur des intervalles tient alors surtout à l'information sur le risque, pas au volume acheté. |
| Fin du compte AWS gratuit | Le plan gratuit ferme après 6 mois ou quand les crédits sont épuisés, et une carte peut être demandée. | Compte créé seulement au début de la phase AWS ; tout en Terraform, détruit après chaque séance ; LocalStack si une carte est demandée. La démonstration publique reste sur Render et GitHub. |
| Quota ou service Open-Meteo | Un refus de quota ou un changement d'API arrête la collecte. | Plafond local de 8 000 appels par jour, une requête par seconde, arrêt définitif au premier 429, cache local. |
| Écart entre ERA5 et la prévision | Le modèle apprend sur une météo observée et prédit sur une météo prévue, d'une autre résolution. | Mêmes points, même altitude, mêmes variables ; écart mesuré sur la validation ; IFS historique mesuré à part, sans assemblage. |
| Fuite de données du futur | Une valeur publiée après midi entre dans une variable. | Règle de midi codée, tests « poison » sur l'heure de décision et sur le délai du consolidé. |
| Test regardé trop tôt | Un réglage est choisi en voyant le test. | Test ouvert une seule fois, avec la version des données figée (sha256 et date). |

## 3. Go ou no-go (règles de la partie C)

| Règle | Mesure | Verdict |
|---|---|---|
| Une décision réaliste s'écrit avec les données disponibles à l'heure limite | Décision à midi la veille ; consolidé jusqu'au mois M-3 ; météo du calcul ECMWF de 00 UTC de la veille, disponible vers 6 h 40 UTC d'après une mesure. | Respectée |
| Au moins 3 années complètes en commun entre consommation, prévision J-1 de RTE et météo, avec moins de 1 % de trous | Consommation et prévision J-1 : 2012-01-01 → 2026-08-31 en consolidé ou définitif ; 60 horodatages absents sur 521 568, tous dus aux changements d'heure et traités. Échantillon commun des références : 126 demi-heures manquantes sur 43 198 (0,29 %). Météo observée (ERA5, 2012-01-01 → 2026-10-31) : 0 heure manquante sur 130 032 par point, pour chacune des 5 variables aux 12 points (mesure du 14/11/2026, `data/meteo-completude.json`). | Respectée |
| Le naïf saisonnier fait au moins deux fois l'erreur de RTE | 6,19 / 1,69 = 3,66 (3,58 à 3,68 selon l'alignement). | Respectée |
| Archive de prévisions météo | Elle existe, mais rejouée avant le 12/05/2026. | Go dégradé : étiquette « météo prévue rejouée » |
| Prix des écarts publics | Prix des écarts ENTSO-E (17.1.g) sous CC BY 4.0. Pas de prix du lendemain sous licence claire. | Go dégradé : prix de référence fixe de 61,1 €/MWh (moyenne 2025, CRE, rapport n° 2026-07), hypothèse, sensibilité à 40 et 100 €/MWh |
| AWS sans carte | Pas encore testé. | Go dégradé si une carte est demandée : LocalStack |

**Décision : go dégradé.** La condition laissée ouverte (moins de 1 % de trous dans la météo observée aux 12 points) a été mesurée le 14/11/2026, une fois ERA5 téléchargé : aucune heure ne manque. La série IFS historique de la validation est complète elle aussi (0 heure manquante sur 12 840 par point).
