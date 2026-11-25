# Sécurité

## Signaler une faille

Merci de **ne pas ouvrir d'issue publique** pour une faille. Utilisez le signalement privé de GitHub : onglet **Security**, puis **Report a vulnerability**. Une réponse est donnée sous sept jours.

*English: please do not open a public issue for a vulnerability; use GitHub's private vulnerability reporting (Security tab, "Report a vulnerability").*

## Ce qui est exposé

Le projet n'a ni site web, ni comptes d'utilisateurs, ni base de données. Les surfaces d'attaque sont :

- **la chaîne GitHub Actions**, qui écrit chaque jour sur les branches `donnees/previsions` et `donnees/disponibilite-ecmwf` ;
- **les branches de données**, qui servent de preuve qu'une prévision a été écrite avant la consommation qu'elle prévoit ;
- **le jeton ENTSO-E**, utilisé en local pour télécharger les prix des écarts.

## Mesures en place

- Le jeton ENTSO-E n'est lu que dans `.env`, qui n'est jamais versionné. Il est masqué dans les messages d'erreur, et un test vérifie qu'il n'apparaît dans aucune sortie ni aucun fichier.
- Les actions GitHub sont référencées par l'empreinte de leur commit, jamais par une étiquette qui pourrait être déplacée.
- Chaque workflow ne reçoit que les droits dont il a besoin. Le jeton d'écriture n'est jamais gardé dans la copie du dépôt : seule l'étape qui pousse sur la branche de données le reçoit, pas celles qui téléchargent des données externes.
- Aucune valeur venue de l'extérieur n'est insérée directement dans un script shell, et aucun workflow ne donne de droits d'écriture à du code venu d'un fork.
- Les dépendances sont verrouillées par `uv.lock`, et la CI refuse un fichier de verrouillage désynchronisé.
- Le XML téléchargé est refusé s'il contient des déclarations de document ou d'entités.
- Les règles de sécurité de ruff (bandit) sont actives.

Un test (`tests/unit/test_workflows.py`) vérifie les règles portant sur les workflows.
