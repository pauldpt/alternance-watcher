# Architecture du pipeline

## Objectif

Automatiser une veille d'alternances Cloud/Data/DevOps:

- ingestion d'offres via API;
- scoring selon le profil cible;
- priorisation des entreprises ciblees;
- deduplication;
- stockage durable;
- notification Discord;
- suivi des candidatures.

## Architecture

```mermaid
flowchart LR
    A["GitHub Actions<br/>cron toutes les 30 min"] --> B["Script Python"]
    B --> C["API La Bonne Alternance"]
    C --> B
    B --> D["Scoring Cloud/Data/DevOps"]
    D --> J["Priorisation entreprises ciblees"]
    J --> E["PostgreSQL / Supabase"]
    E --> F{"Offre deja notifiee ?"}
    F -->|Non| G["Discord Webhook"]
    F -->|Oui| H["Silence"]
    B --> I["Rapport Markdown / CSV"]
```

## Stockage

En local, le script utilise SQLite:

```text
/Users/paul/Documents/Offres Alternance/offres_alternance.db
```

En cloud, GitHub Actions doit utiliser PostgreSQL ou Supabase via le secret:

```text
DATABASE_URL=postgresql://...
```

Tables principales:

- `offers`: offres, score, statut de candidature, notification.
- `runs`: historique des executions.

## Scoring et priorisation

Le scoring donne une note aux offres selon:

- l'adequation Bac+3 / BUT3 / Licence / niveau 6;
- les mots-cles Cloud/Data/DevOps dans le titre;
- les technologies presentes dans la description;
- les entreprises ciblees;
- les signaux negatifs a eviter.

Les entreprises ciblees ne recoivent pas seulement un bonus de score. Elles passent aussi en priorite dans l'ordre d'affichage quand le nombre d'offres est limite.

Ordre final:

1. offres venant d'entreprises ciblees;
2. score le plus eleve;
3. date de publication la plus recente.

Details: [SCORING_PRIORITES.md](SCORING_PRIORITES.md)

## Statuts candidature

Valeurs prevues:

- `new`
- `to_apply`
- `applied`
- `follow_up`
- `rejected`
- `ignored`

Exemple:

```bash
python3 offres_alternance.py --set-status "France Travail:123" --status applied --notes "CV envoye"
```

## Secrets GitHub Actions

Dans le repo GitHub:

- `LBA_API_TOKEN`
- `DATABASE_URL`
- `DISCORD_WEBHOOK_URL`
- optionnel: `DISCORD_MENTION`

## Pourquoi c'est un projet CV solide

Ce projet montre:

- automatisation planifiee;
- integration API;
- gestion de secrets;
- persistance PostgreSQL;
- deduplication;
- notifications webhook;
- reporting;
- logique de scoring metier.
- priorisation metier explicite des opportunites.
