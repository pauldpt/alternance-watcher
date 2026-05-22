# Deploiement cloud GitHub Actions + Supabase

## 1. Creer le repo GitHub

Depuis ce dossier:

```bash
git init
git add .
git commit -m "Initial alternance watcher pipeline"
```

Puis cree un repo GitHub et pousse le code.

Attention: `.env` est ignore par `.gitignore`, donc ton token local ne sera pas pousse.

## 2. Creer la base Supabase

1. Cree un projet Supabase.
2. Va dans `Project Settings`.
3. Va dans `Database`.
4. Copie l'URL de connexion PostgreSQL.
5. Utilise une URL avec SSL, par exemple:

```text
postgresql://postgres.xxx:PASSWORD@aws-0-eu-west-3.pooler.supabase.com:6543/postgres?sslmode=require
```

Le script cree les tables automatiquement au premier run.

## 3. Ajouter les secrets GitHub

Dans GitHub:

`Settings` -> `Secrets and variables` -> `Actions` -> `New repository secret`

Ajoute:

- `LBA_API_TOKEN`
- `DATABASE_URL`
- `DISCORD_WEBHOOK_URL`
- optionnel: `DISCORD_MENTION`

## 4. Lancer le workflow

Va dans `Actions` -> `Veille alternance` -> `Run workflow`.

Ensuite le workflow tourne toutes les 30 minutes.

Si `DATABASE_URL` ou `DISCORD_WEBHOOK_URL` manque, le workflow reste vert mais ignore la veille. C'est volontaire pour garder un repo propre tant que la configuration cloud n'est pas terminee.

## 5. Tester en local

Sans envoyer Discord:

```bash
python3 offres_alternance.py --no-email --no-discord --dry-run --max 5
```

Avec Discord:

```bash
python3 offres_alternance.py --no-email
```

## 6. Export du suivi de candidatures

```bash
python3 offres_alternance.py --export-csv
```

Le fichier sort ici:

```text
/Users/paul/Documents/Offres Alternance/suivi_candidatures.csv
```
