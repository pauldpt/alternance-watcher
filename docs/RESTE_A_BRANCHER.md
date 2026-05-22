# Reste a brancher

Le projet est pret cote code et GitHub. Il manque seulement deux secrets externes pour activer la veille cloud complete.

## 1. Discord

Objectif: recevoir les nouvelles offres directement dans un salon Discord.

Etapes:

1. Ouvre ton serveur Discord.
2. Va dans le salon ou tu veux recevoir les offres.
3. `Modifier le salon` -> `Integrations` -> `Webhooks`.
4. Cree un webhook.
5. Copie l'URL du webhook.
6. Ajoute-la dans GitHub Actions comme secret:

```bash
gh secret set DISCORD_WEBHOOK_URL --repo pauldpt/alternance-watcher
```

Puis colle l'URL quand GitHub CLI la demande.

Pour tester en local, ajoute aussi dans `.env`:

```text
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
```

Puis lance:

```bash
python3 offres_alternance.py --test-discord
```

## 2. Supabase / PostgreSQL

Objectif: garder l'historique des offres deja envoyees entre deux executions GitHub Actions.

Etapes:

1. Cree un projet Supabase.
2. Va dans `Project Settings` -> `Database`.
3. Copie l'URL PostgreSQL en mode pooler/transaction si possible.
4. Ajoute `?sslmode=require` a la fin si l'URL ne l'a pas.
5. Ajoute l'URL dans GitHub Actions comme secret:

```bash
gh secret set DATABASE_URL --repo pauldpt/alternance-watcher
```

Puis colle l'URL quand GitHub CLI la demande.

Le script cree automatiquement les tables `offers` et `runs`.

## 3. Verifier

En local:

```bash
python3 offres_alternance.py --check-config
python3 offres_alternance.py --self-test
```

Sur GitHub:

1. Va dans `Actions`.
2. Ouvre `Veille alternance`.
3. Clique `Run workflow`.
4. Si les trois secrets sont presents, le watcher s'execute.

Secrets requis:

- `LBA_API_TOKEN`
- `DATABASE_URL`
- `DISCORD_WEBHOOK_URL`

Aujourd'hui, `LBA_API_TOKEN` est deja configure. Il reste donc `DATABASE_URL` et `DISCORD_WEBHOOK_URL`.
