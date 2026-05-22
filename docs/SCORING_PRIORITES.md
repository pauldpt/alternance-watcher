# Scoring et priorites

## Objectif

Le pipeline ne doit pas seulement envoyer beaucoup d'offres. Il doit faire remonter les offres les plus utiles pour un objectif Cloud/Data/DevOps.

Le tri final repond a une question simple:

> Si je ne vois que quelques offres dans Discord, lesquelles doivent apparaitre en premier ?

## Ordre de priorite

Le script applique maintenant un tri en trois niveaux:

1. entreprises ciblees en premier;
2. score le plus eleve;
3. offre la plus recente.

Donc une offre CGI, Capgemini, Orange Business, Thales ou OVHcloud peut passer devant une offre non prioritaire, meme si l'autre offre a un score brut plus haut.

## Entreprises ciblees

Les entreprises ciblees sont celles qui correspondent le mieux au projet Cloud/Data/DevOps:

- CGI
- Capgemini
- Thales
- Orange Business
- Orange
- Sopra Steria
- OVHcloud
- OVH
- EDF
- Microsoft
- Amazon Web Services
- AWS
- Airbus

Ces entreprises ont deux avantages:

- bonus de score;
- priorite d'affichage dans Discord et dans les rapports.

## Mots-cles positifs

Le score augmente avec les signaux suivants:

- Bac+3
- BUT3
- Licence
- niveau 6
- DevOps
- Cloud
- Data Engineer
- Infrastructure
- Platform Engineer
- SRE
- MLOps
- Linux
- Docker
- Kubernetes
- Azure
- AWS
- GCP
- Terraform
- Python
- SQL
- CI/CD
- Spark
- ETL

Les mots dans le titre valent plus que les mots dans la description.

Les offres qui indiquent clairement Bac+3, BUT3, Licence ou niveau 6 recoivent aussi un bonus, parce qu'elles correspondent mieux a une recherche d'alternance en 3eme annee d'IUT / BUT.

## Signaux negatifs

Le score baisse si l'offre ressemble trop a quelque chose a eviter:

- Business Analyst pur
- RH / Data RH
- QA ou test uniquement
- support bureautique
- helpdesk
- reporting Excel pur
- commercial
- marketing

## Pourquoi ce choix

Le but n'est pas de trouver n'importe quelle alternance en informatique. Le but est de se rapprocher d'un profil:

- Cloud Engineer
- DevOps Cloud
- Data Platform Engineer
- Infrastructure Engineer
- futur Cloud Architect

Le scoring favorise donc les offres ou tu peux toucher au cloud reel, a l'infra, au reseau, a la data engineering et aux outils de production.

## Parametres importants

`MIN_SCORE` controle le seuil minimum.

```text
MIN_SCORE=18
```

Plus le seuil est bas, plus le bot envoie d'offres. Plus il est haut, plus les offres sont filtrees.

`DISCORD_MAX_OFFERS` controle le nombre maximum d'offres envoyees dans Discord par run.

```text
DISCORD_MAX_OFFERS=20
```

Si 50 offres nouvelles arrivent et que Discord en affiche 20, le bot garde les 20 premieres apres tri:

1. entreprises ciblees;
2. meilleur score;
3. offres les plus recentes.

`DISCORD_BATCH_SIZE` controle l'organisation des messages Discord.

```text
DISCORD_BATCH_SIZE=5
```

Avec 20 offres, Discord recoit donc 4 messages de 5 offres. Chaque titre contient le rang et le score:

```text
#01 | score 92 | entreprise ciblee | Alternance DevOps Cloud
```
