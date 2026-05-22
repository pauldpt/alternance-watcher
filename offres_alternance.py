#!/usr/bin/env python3
"""
Veille automatique d'offres d'alternance Cloud/Data/DevOps.

Source principale: API officielle La bonne alternance.
Docs: https://api.apprentissage.beta.gouv.fr/fr/documentation-technique
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import html
import json
import os
import re
import smtplib
import sqlite3
import ssl
import sys
import textwrap
import unicodedata
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus, urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DEFAULT_OUTPUT_DIR = Path("/Users/paul/Documents/Offres Alternance")
LEGACY_SEEN_FILE = DATA_DIR / "seen_jobs.json"
LATEST_REPORT_NAME = "dernieres_nouvelles_offres.md"
STATUS_REPORT_NAME = "statut_veille.md"
SEEN_REPORT_NAME = ".offres_deja_recues.json"
LOCAL_DB_NAME = "offres_alternance.db"

LBA_SEARCH_URL = "https://api.apprentissage.beta.gouv.fr/api/job/v1/search"

# ROME utiles pour un profil BUT Science des donnees vers cloud/data/devops.
# Tu peux ajuster dans .env avec ROME_CODES=...
DEFAULT_ROME_CODES = [
    "M1801",  # Administration de systemes d'information
    "M1802",  # Expertise et support en systemes d'information
    "M1805",  # Etudes et developpement informatique
    "M1806",  # Conseil et maitrise d'ouvrage en SI
    "M1810",  # Production et exploitation de systemes d'information
    "M1403",  # Etudes et prospectives socio-economiques / data selon offres
]

PREFERRED_COMPANIES = [
    "CGI",
    "Capgemini",
    "Thales",
    "Orange Business",
    "Orange",
    "Sopra Steria",
    "OVHcloud",
    "OVH",
    "EDF",
    "Microsoft",
    "Amazon Web Services",
    "AWS",
    "Airbus",
]

TITLE_KEYWORDS = [
    "devops",
    "cloud",
    "data engineer",
    "data engineering",
    "ingenieur data",
    "ingenieur cloud",
    "infrastructure",
    "platform engineer",
    "sre",
    "site reliability",
    "mlops",
    "automation",
    "automatisation",
    "kubernetes",
    "docker",
    "linux",
    "terraform",
    "azure",
    "aws",
    "gcp",
    "big data",
    "data platform",
    "dataops",
    "ia",
    "intelligence artificielle",
]

BODY_KEYWORDS = [
    *TITLE_KEYWORDS,
    "python",
    "sql",
    "git",
    "ci/cd",
    "cicd",
    "ansible",
    "monitoring",
    "observability",
    "reseau",
    "reseaux",
    "virtualisation",
    "spark",
    "etl",
    "pipeline",
]

NEGATIVE_KEYWORDS = [
    "business analyst",
    "analyste fonctionnel",
    "fonctionnel",
    "rh",
    "ressources humaines",
    "data rh",
    "qa",
    "testeur",
    "testing",
    "support bureautique",
    "technicien support",
    "helpdesk",
    "reporting excel",
    "excel",
    "power bi uniquement",
    "commercial",
    "marketing",
]


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Job:
    uid: str
    title: str
    company: str
    location: str
    url: str
    partner: str
    created_at: str
    contract: str
    remote: str
    rome_codes: str
    score: int
    reasons: list[str]
    description: str


@dataclass(frozen=True)
class ExternalLink:
    category: str
    label: str
    url: str


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def env_list(name: str, default: list[str] | None = None) -> list[str]:
    value = os.getenv(name, "")
    if not value:
        return default or []
    return [item.strip() for item in re.split(r"[,;]", value) if item.strip()]


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ConfigError(f"{name} doit etre un nombre entier, valeur recue: {value}") from exc


def output_dir() -> Path:
    return Path(os.getenv("OUTPUT_DIR", str(DEFAULT_OUTPUT_DIR))).expanduser()


def archive_dir() -> Path:
    return output_dir() / "archives"


def seen_file() -> Path:
    return output_dir() / SEEN_REPORT_NAME


def fold(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text or "")
    ascii_text = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return ascii_text.lower()


def contains_phrase(text: str, phrase: str) -> bool:
    text_folded = fold(text)
    phrase_folded = fold(phrase)
    if len(phrase_folded) <= 3:
        return bool(re.search(rf"\b{re.escape(phrase_folded)}\b", text_folded))
    return phrase_folded in text_folded


def priority_company_name(company: str) -> str:
    for company_name in PREFERRED_COMPANIES:
        if contains_phrase(company, company_name):
            return company_name
    return ""


def is_priority_company(company: str) -> bool:
    return bool(priority_company_name(company))


def first_non_empty(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def shorten(text: str, max_chars: int = 360) -> str:
    compact = re.sub(r"\s+", " ", text or "").strip()
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 1].rstrip() + "..."


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "oui", "on"}


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def database_url() -> str:
    value = os.getenv("DATABASE_URL", "").strip()
    if value:
        return value
    if env_bool("REQUIRE_PERSISTENT_DB", False):
        raise ConfigError(
            "DATABASE_URL est requis pour le pipeline cloud. "
            "Ajoute une URL PostgreSQL/Supabase dans les secrets GitHub."
        )
    return f"sqlite:///{output_dir() / LOCAL_DB_NAME}"


def is_postgres_url(url: str) -> bool:
    return url.startswith(("postgres://", "postgresql://"))


def sqlite_path_from_url(url: str) -> Path:
    if not url.startswith("sqlite:///"):
        raise ConfigError("DATABASE_URL doit commencer par sqlite:/// ou postgresql://")
    return Path(url.removeprefix("sqlite:///")).expanduser()


class JobStore:
    def __init__(self, conn: Any, driver: str) -> None:
        self.conn = conn
        self.driver = driver

    @classmethod
    def open(cls) -> "JobStore":
        url = database_url()
        if is_postgres_url(url):
            try:
                import psycopg
                from psycopg.rows import dict_row
            except ImportError as exc:
                raise ConfigError(
                    "DATABASE_URL pointe vers PostgreSQL/Supabase mais psycopg n'est pas installe. "
                    "Lance: python3 -m pip install -r requirements.txt"
                ) from exc
            return cls(psycopg.connect(url, row_factory=dict_row, prepare_threshold=None), "postgres")

        db_path = sqlite_path_from_url(url)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return cls(conn, "sqlite")

    def close(self) -> None:
        self.conn.close()

    def sql(self, query: str) -> str:
        if self.driver == "postgres":
            return query.replace("?", "%s")
        return query

    def execute(self, query: str, params: tuple[Any, ...] = ()) -> Any:
        return self.conn.execute(self.sql(query), params)

    def fetchone(self, query: str, params: tuple[Any, ...] = ()) -> Any | None:
        cursor = self.execute(query, params)
        return cursor.fetchone()

    def fetchall(self, query: str, params: tuple[Any, ...] = ()) -> list[Any]:
        cursor = self.execute(query, params)
        return list(cursor.fetchall())

    def commit(self) -> None:
        self.conn.commit()

    def rollback(self) -> None:
        self.conn.rollback()

    def init_schema(self) -> None:
        self.execute(
            """
            CREATE TABLE IF NOT EXISTS offers (
                uid TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                company TEXT NOT NULL,
                location TEXT,
                url TEXT NOT NULL,
                partner TEXT,
                source_created_at TEXT,
                contract TEXT,
                remote TEXT,
                rome_codes TEXT,
                score INTEGER NOT NULL,
                reasons_json TEXT NOT NULL,
                description TEXT,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                notified_at TEXT,
                notified_channels TEXT,
                application_status TEXT NOT NULL DEFAULT 'new',
                applied_at TEXT,
                notes TEXT
            )
            """
        )
        self.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL,
                found_count INTEGER NOT NULL DEFAULT 0,
                new_count INTEGER NOT NULL DEFAULT 0,
                notified_count INTEGER NOT NULL DEFAULT 0,
                error TEXT
            )
            """
        )
        self.execute("CREATE INDEX IF NOT EXISTS idx_offers_notified_at ON offers(notified_at)")
        self.execute("CREATE INDEX IF NOT EXISTS idx_offers_status ON offers(application_status)")
        self.execute("CREATE INDEX IF NOT EXISTS idx_offers_score ON offers(score)")
        self.commit()
        self.import_legacy_seen()

    def import_legacy_seen(self) -> None:
        legacy_seen = load_seen()
        if not legacy_seen:
            return
        now = utc_now()
        for uid in legacy_seen:
            self.execute(
                """
                INSERT INTO offers (
                    uid, title, company, location, url, partner, source_created_at, contract,
                    remote, rome_codes, score, reasons_json, description, first_seen_at,
                    last_seen_at, notified_at, notified_channels, application_status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(uid) DO NOTHING
                """,
                (
                    uid,
                    "Offre importee depuis l'ancien historique",
                    "Inconnu",
                    "",
                    "",
                    "legacy",
                    "",
                    "",
                    "",
                    "",
                    0,
                    "[]",
                    "",
                    now,
                    now,
                    now,
                    "legacy",
                    "new",
                ),
            )
        self.commit()

    def start_run(self) -> str:
        run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        self.execute(
            "INSERT INTO runs (id, started_at, status) VALUES (?, ?, ?)",
            (run_id, utc_now(), "running"),
        )
        self.commit()
        return run_id

    def finish_run(
        self,
        run_id: str,
        status: str,
        found_count: int,
        new_count: int,
        notified_count: int,
        error: str = "",
    ) -> None:
        self.execute(
            """
            UPDATE runs
            SET finished_at = ?, status = ?, found_count = ?, new_count = ?,
                notified_count = ?, error = ?
            WHERE id = ?
            """,
            (utc_now(), status, found_count, new_count, notified_count, error, run_id),
        )
        self.commit()

    def is_unnotified(self, job: Job) -> bool:
        row = self.fetchone("SELECT notified_at FROM offers WHERE uid = ?", (job.uid,))
        return row is None or not row["notified_at"]

    def upsert_jobs(self, jobs: list[Job]) -> list[Job]:
        new_jobs: list[Job] = []
        now = utc_now()
        for job in jobs:
            if self.is_unnotified(job):
                new_jobs.append(job)
            self.execute(
                """
                INSERT INTO offers (
                    uid, title, company, location, url, partner, source_created_at,
                    contract, remote, rome_codes, score, reasons_json, description,
                    first_seen_at, last_seen_at, application_status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(uid) DO UPDATE SET
                    title = excluded.title,
                    company = excluded.company,
                    location = excluded.location,
                    url = excluded.url,
                    partner = excluded.partner,
                    source_created_at = excluded.source_created_at,
                    contract = excluded.contract,
                    remote = excluded.remote,
                    rome_codes = excluded.rome_codes,
                    score = excluded.score,
                    reasons_json = excluded.reasons_json,
                    description = excluded.description,
                    last_seen_at = excluded.last_seen_at
                """,
                (
                    job.uid,
                    job.title,
                    job.company,
                    job.location,
                    job.url,
                    job.partner,
                    job.created_at,
                    job.contract,
                    job.remote,
                    job.rome_codes,
                    job.score,
                    json.dumps(job.reasons, ensure_ascii=False),
                    job.description,
                    now,
                    now,
                    "new",
                ),
            )
        self.commit()
        return new_jobs

    def unnotified_jobs(self, jobs: list[Job]) -> list[Job]:
        return [job for job in jobs if self.is_unnotified(job)]

    def mark_notified(self, jobs: list[Job], channels: list[str]) -> None:
        if not jobs:
            return
        now = utc_now()
        channel_text = ",".join(channels)
        for job in jobs:
            self.execute(
                "UPDATE offers SET notified_at = ?, notified_channels = ? WHERE uid = ?",
                (now, channel_text, job.uid),
            )
        self.commit()
        save_seen({row["uid"] for row in self.fetchall("SELECT uid FROM offers WHERE notified_at IS NOT NULL")})

    def reset_notifications(self) -> None:
        self.execute("UPDATE offers SET notified_at = NULL, notified_channels = NULL")
        self.commit()
        save_seen(set())

    def update_application_status(self, uid: str, status: str, notes: str = "") -> bool:
        allowed = {"new", "to_apply", "applied", "follow_up", "rejected", "ignored"}
        if status not in allowed:
            raise ConfigError(f"Statut invalide. Valeurs possibles: {', '.join(sorted(allowed))}")
        applied_at = utc_now() if status == "applied" else None
        if notes:
            self.execute(
                """
                UPDATE offers
                SET application_status = ?, applied_at = COALESCE(?, applied_at), notes = ?
                WHERE uid = ?
                """,
                (status, applied_at, notes, uid),
            )
        else:
            self.execute(
                """
                UPDATE offers
                SET application_status = ?, applied_at = COALESCE(?, applied_at)
                WHERE uid = ?
                """,
                (status, applied_at, uid),
            )
        self.commit()
        return self.conn.total_changes > 0 if self.driver == "sqlite" else True

    def recent_offers(self, limit: int = 30, status: str = "") -> list[Any]:
        if status:
            return self.fetchall(
                """
                SELECT uid, title, company, score, application_status, notified_at, url
                FROM offers
                WHERE application_status = ?
                ORDER BY notified_at DESC, first_seen_at DESC
                LIMIT ?
                """,
                (status, limit),
            )
        return self.fetchall(
            """
            SELECT uid, title, company, score, application_status, notified_at, url
            FROM offers
            ORDER BY notified_at DESC, first_seen_at DESC
            LIMIT ?
            """,
            (limit,),
        )

    def export_csv(self, path: Path) -> Path:
        rows = self.fetchall(
            """
            SELECT uid, title, company, location, url, partner, score, application_status,
                   notified_at, applied_at, notes
            FROM offers
            ORDER BY notified_at DESC, first_seen_at DESC
            """
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(
                [
                    "uid",
                    "title",
                    "company",
                    "location",
                    "url",
                    "partner",
                    "score",
                    "application_status",
                    "notified_at",
                    "applied_at",
                    "notes",
                ]
            )
            for row in rows:
                writer.writerow([row[key] for key in row.keys()])
        return path


def external_search_links() -> list[ExternalLink]:
    if not env_bool("INCLUDE_EXTERNAL_LINKS", True):
        return []

    queries = env_list(
        "EXTERNAL_SEARCH_QUERIES",
        [
            "alternance devops cloud",
            "alternance data engineer",
            "alternance infrastructure cloud",
        ],
    )
    location = os.getenv("EXTERNAL_SEARCH_LOCATION", "France").strip() or "France"

    links: list[ExternalLink] = []
    for query in queries:
        query_encoded = quote_plus(query)
        location_encoded = quote_plus(location)
        links.extend(
            [
                ExternalLink(
                    "Plateformes",
                    f"JobTeaser - {query}",
                    f"https://www.jobteaser.com/fr/job-offers?query={query_encoded}",
                ),
                ExternalLink(
                    "Plateformes",
                    f"Welcome to the Jungle - {query}",
                    f"https://www.welcometothejungle.com/fr/jobs?query={query_encoded}",
                ),
                ExternalLink(
                    "Plateformes",
                    f"Indeed - {query}",
                    f"https://fr.indeed.com/jobs?q={query_encoded}&l={location_encoded}",
                ),
            ]
        )

    if env_bool("INCLUDE_DIRECT_CAREERS", True):
        links.extend(
            [
                ExternalLink("Sites carrieres directs", "CGI Careers", "https://www.cgi.com/fr/fr/carrieres"),
                ExternalLink("Sites carrieres directs", "Capgemini Careers", "https://www.capgemini.com/fr-fr/carrieres/"),
                ExternalLink("Sites carrieres directs", "Thales Careers", "https://careers.thalesgroup.com"),
                ExternalLink("Sites carrieres directs", "Orange Jobs", "https://orange.jobs/jobs/v3/search.html"),
                ExternalLink("Sites carrieres directs", "OVHcloud Careers", "https://careers.ovhcloud.com/"),
                ExternalLink("Sites carrieres directs", "Sopra Steria Careers", "https://www.soprasteria.com/fr/carrieres"),
                ExternalLink("Sites carrieres directs", "EDF Recrute", "https://www.edf.fr/edf-recrute"),
                ExternalLink("Sites carrieres directs", "Microsoft Careers", "https://careers.microsoft.com/"),
                ExternalLink("Sites carrieres directs", "AWS Careers", "https://www.amazon.jobs/content/fr/teams/amazon-web-services"),
                ExternalLink("Sites carrieres directs", "Airbus Careers", "https://www.airbus.com/en/careers"),
            ]
        )

    return links


def append_external_links_markdown(lines: list[str]) -> None:
    links = external_search_links()
    if not links:
        return

    lines.extend(
        [
            "## Recherches complementaires sans LinkedIn",
            "",
            "Liens a verifier manuellement: JobTeaser, Welcome to the Jungle, Indeed et sites carrieres directs.",
            "",
        ]
    )

    current_category = ""
    for link in links:
        if link.category != current_category:
            if current_category:
                lines.append("")
            current_category = link.category
            lines.extend([f"### {current_category}", ""])
        lines.append(f"- [{link.label}]({link.url})")
    lines.append("")


def external_links_html() -> str:
    links = external_search_links()
    if not links:
        return ""

    sections: list[str] = [
        "<h2>Recherches complementaires sans LinkedIn</h2>",
        "<p>Liens a verifier manuellement: JobTeaser, Welcome to the Jungle, Indeed et sites carrieres directs.</p>",
    ]
    current_category = ""
    for link in links:
        if link.category != current_category:
            if current_category:
                sections.append("</ul>")
            current_category = link.category
            sections.append(f"<h3>{html.escape(current_category)}</h3><ul>")
        sections.append(f'<li><a href="{html.escape(link.url)}">{html.escape(link.label)}</a></li>')
    if current_category:
        sections.append("</ul>")
    return "\n".join(sections)


def build_searches() -> list[dict[str, Any]]:
    rome_codes = env_list("ROME_CODES", DEFAULT_ROME_CODES)
    departments = env_list("SEARCH_DEPARTEMENTS")
    target_level = os.getenv("TARGET_DIPLOMA_LEVEL", "6").strip() or "6"

    latitude = os.getenv("SEARCH_LATITUDE", "").strip()
    longitude = os.getenv("SEARCH_LONGITUDE", "").strip()
    radius = os.getenv("SEARCH_RADIUS_KM", "").strip()

    searches: list[dict[str, Any]] = []
    for rome in rome_codes:
        params: dict[str, Any] = {
            "romes": rome,
            "target_diploma_level": target_level,
        }
        if departments:
            params["departements"] = departments
        elif latitude and longitude:
            params["latitude"] = latitude
            params["longitude"] = longitude
            if radius:
                params["radius"] = radius
        searches.append(params)

    if os.getenv("INCLUDE_BROAD_SEARCH", "false").lower() in {"1", "true", "yes", "oui"}:
        params = {"target_diploma_level": target_level}
        if departments:
            params["departements"] = departments
        elif latitude and longitude:
            params["latitude"] = latitude
            params["longitude"] = longitude
            if radius:
                params["radius"] = radius
        searches.append(params)

    return searches


def fetch_lba_jobs(params: dict[str, Any]) -> list[dict[str, Any]]:
    token = os.getenv("LBA_API_TOKEN", "").strip()
    if not token or token == "COLLE_TON_TOKEN_ICI":
        raise ConfigError(
            "LBA_API_TOKEN est manquant. Cree un compte sur l'espace developpeurs "
            "La bonne alternance, genere un jeton, puis ajoute-le dans .env."
        )

    url = f"{LBA_SEARCH_URL}?{urlencode(params, doseq=True)}"
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "alternance-watch/1.0 (+script personnel)",
        },
    )

    try:
        with urlopen(request, timeout=40) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Erreur API La bonne alternance {exc.code}: {body[:500]}") from exc
    except URLError as exc:
        raise RuntimeError(f"Impossible de contacter La bonne alternance: {exc}") from exc

    return payload.get("jobs", [])


def score_job(raw: dict[str, Any]) -> tuple[int, list[str]]:
    offer = raw.get("offer") or {}
    workplace = raw.get("workplace") or {}

    title = first_non_empty(offer.get("title"))
    company = first_non_empty(workplace.get("name"), workplace.get("brand"), workplace.get("legal_name"))
    description = " ".join(
        [
            str(offer.get("description") or ""),
            " ".join(offer.get("desired_skills") or []),
            " ".join(offer.get("to_be_acquired_skills") or []),
            str(workplace.get("description") or ""),
        ]
    )
    title_text = fold(title)
    body_text = fold(description)

    score = 0
    reasons: list[str] = []

    company_priority = priority_company_name(company)
    if company_priority:
        score += 45
        reasons.append(f"entreprise prioritaire: {company_priority}")

    for keyword in TITLE_KEYWORDS:
        if contains_phrase(title_text, keyword):
            score += 18
            reasons.append(f"titre: {keyword}")

    for keyword in BODY_KEYWORDS:
        if contains_phrase(body_text, keyword):
            score += 7
            if len(reasons) < 7:
                reasons.append(f"contenu: {keyword}")

    for keyword in NEGATIVE_KEYWORDS:
        if contains_phrase(title_text, keyword):
            score -= 45
            reasons.append(f"a verifier/eviter: {keyword}")
        elif contains_phrase(body_text, keyword):
            score -= 15
            if len(reasons) < 7:
                reasons.append(f"signal faible negatif: {keyword}")

    if "alternance" in title_text or "apprentissage" in body_text:
        score += 5
    if raw.get("contract", {}).get("remote") in {"remote", "hybrid"}:
        score += 4

    return score, reasons[:8]


def normalize_job(raw: dict[str, Any]) -> Job:
    identifier = raw.get("identifier") or {}
    offer = raw.get("offer") or {}
    workplace = raw.get("workplace") or {}
    apply = raw.get("apply") or {}
    contract = raw.get("contract") or {}
    publication = offer.get("publication") or {}
    location = workplace.get("location") or {}

    partner = first_non_empty(identifier.get("partner_label"))
    partner_job_id = first_non_empty(identifier.get("partner_job_id"), identifier.get("id"))
    url = first_non_empty(apply.get("url"))
    uid = f"{partner}:{partner_job_id or url}"

    score, reasons = score_job(raw)

    return Job(
        uid=uid,
        title=first_non_empty(offer.get("title")),
        company=first_non_empty(workplace.get("name"), workplace.get("brand"), workplace.get("legal_name"), "Entreprise inconnue"),
        location=first_non_empty(location.get("address")),
        url=url,
        partner=partner,
        created_at=first_non_empty(publication.get("creation")),
        contract=", ".join(contract.get("type") or []),
        remote=first_non_empty(contract.get("remote")),
        rome_codes=", ".join(offer.get("rome_codes") or []),
        score=score,
        reasons=reasons,
        description=shorten(first_non_empty(offer.get("description")), 420),
    )


def collect_jobs() -> list[Job]:
    raw_jobs: list[dict[str, Any]] = []
    errors: list[str] = []

    for params in build_searches():
        try:
            raw_jobs.extend(fetch_lba_jobs(params))
        except ConfigError:
            raise
        except Exception as exc:  # noqa: BLE001 - on veut continuer les autres requetes.
            errors.append(f"{params}: {exc}")

    if errors and not raw_jobs:
        raise RuntimeError("\n".join(errors))

    deduped: dict[str, Job] = {}
    min_score = env_int("MIN_SCORE", 18)
    for raw in raw_jobs:
        job = normalize_job(raw)
        if not job.url:
            continue
        if job.score < min_score:
            continue
        previous = deduped.get(job.uid)
        if previous is None or job.score > previous.score:
            deduped[job.uid] = job

    return prioritize_jobs(list(deduped.values()))


def prioritize_jobs(jobs: list[Job]) -> list[Job]:
    return sorted(
        jobs,
        key=lambda job: (is_priority_company(job.company), job.score, job.created_at),
        reverse=True,
    )


def load_seen() -> set[str]:
    seen: set[str] = set()
    for path in [LEGACY_SEEN_FILE, seen_file()]:
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        seen.update(payload.get("seen", []))
    return seen


def save_seen(seen: set[str]) -> None:
    output_dir().mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "seen": sorted(seen),
    }
    seen_file().write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def markdown_report(jobs: list[Job], title: str, empty_message: str | None = None) -> str:
    lines = [f"# {title}", ""]
    if not jobs:
        lines.append(empty_message or "Aucune nouvelle offre correspondant aux filtres.")
        lines.append("")
        append_external_links_markdown(lines)
        return "\n".join(lines) + "\n"

    for index, job in enumerate(jobs, start=1):
        lines.extend(
            [
                f"## {index}. {job.title}",
                "",
                f"- Entreprise: {job.company}",
                f"- Priorite entreprise: {'oui' if is_priority_company(job.company) else 'non'}",
                f"- Score: {job.score}",
                f"- Source: {job.partner}",
                f"- Lieu: {job.location or 'Non precise'}",
                f"- Contrat: {job.contract or 'Alternance'}",
                f"- Remote: {job.remote or 'Non precise'}",
                f"- ROME: {job.rome_codes or 'Non precise'}",
                f"- Creee le: {job.created_at or 'Non precise'}",
                f"- Pourquoi: {', '.join(job.reasons) if job.reasons else 'match mots-cles'}",
                f"- Postuler: {job.url}",
                "",
                job.description,
                "",
            ]
        )
    append_external_links_markdown(lines)
    return "\n".join(lines)


def html_report(jobs: list[Job], title: str) -> str:
    if not jobs:
        body = "<p>Aucune nouvelle offre correspondant aux filtres.</p>"
    else:
        cards = []
        for job in jobs:
            reasons = ", ".join(html.escape(reason) for reason in job.reasons) or "match mots-cles"
            cards.append(
                f"""
                <article style="border:1px solid #ddd;padding:14px;margin:0 0 14px 0;border-radius:8px">
                  <h2 style="margin:0 0 8px 0;font-size:18px">{html.escape(job.title)}</h2>
                  <p style="margin:0 0 8px 0"><strong>{html.escape(job.company)}</strong> - score {job.score}</p>
                  <p style="margin:0 0 8px 0">{html.escape(job.location or "Lieu non precise")}</p>
                  <p style="margin:0 0 8px 0">Source: {html.escape(job.partner)} | Contrat: {html.escape(job.contract or "Alternance")}</p>
                  <p style="margin:0 0 8px 0">Pourquoi: {reasons}</p>
                  <p style="margin:0 0 10px 0;color:#444">{html.escape(job.description)}</p>
                  <p style="margin:0"><a href="{html.escape(job.url)}">Voir l'offre / postuler</a></p>
                </article>
                """
            )
        body = "\n".join(cards)
    return f"<html><body><h1>{html.escape(title)}</h1>{body}{external_links_html()}</body></html>"


def write_report(jobs: list[Job], title: str | None = None, empty_message: str | None = None) -> Path:
    output_dir().mkdir(parents=True, exist_ok=True)
    archive_dir().mkdir(exist_ok=True)
    now = dt.datetime.now().strftime("%Y-%m-%d_%H%M")
    path = archive_dir() / f"offres_{now}.md"
    report_title = title or f"Nouvelles offres alternance Cloud/Data/DevOps - {now}"
    content = markdown_report(jobs, report_title, empty_message)
    path.write_text(content, encoding="utf-8")
    (output_dir() / LATEST_REPORT_NAME).write_text(content, encoding="utf-8")
    return path


def write_status(message: str) -> Path:
    output_dir().mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    path = output_dir() / STATUS_REPORT_NAME
    path.write_text(f"# Statut veille alternance\n\n{now} - {message}\n", encoding="utf-8")
    return path


def smtp_configured() -> bool:
    required = ["SMTP_HOST", "EMAIL_TO"]
    return all(os.getenv(key, "").strip() for key in required)


def discord_webhooks() -> list[str]:
    placeholders = {"", "COLLE_TON_WEBHOOK_DISCORD_ICI"}
    urls = env_list("DISCORD_WEBHOOK_URLS")
    if not urls:
        single_url = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
        urls = [single_url] if single_url else []
    return [url for url in urls if url.strip() not in placeholders]


def discord_configured() -> bool:
    return bool(discord_webhooks())


def job_to_discord_embed(job: Job) -> dict[str, Any]:
    reasons = ", ".join(job.reasons) if job.reasons else "match mots-cles"
    fields = [
        {"name": "Entreprise", "value": job.company or "Non precise", "inline": True},
        {"name": "Score", "value": str(job.score), "inline": True},
        {"name": "Source", "value": job.partner or "Non precise", "inline": True},
        {"name": "Lieu", "value": shorten(job.location or "Non precise", 120), "inline": False},
        {"name": "Pourquoi", "value": shorten(reasons, 160), "inline": False},
    ]
    return {
        "title": shorten(job.title, 180),
        "url": job.url,
        "description": shorten(job.description, 260),
        "color": 0x1F8B4C,
        "fields": fields,
    }


def send_discord(jobs: list[Job]) -> bool:
    webhooks = discord_webhooks()
    if not webhooks:
        if env_bool("REQUIRE_DISCORD", False):
            raise ConfigError("DISCORD_WEBHOOK_URL est requis pour le pipeline cloud.")
        print("Discord non envoye: DISCORD_WEBHOOK_URL ou DISCORD_WEBHOOK_URLS n'est pas configure.")
        return False

    mention = os.getenv("DISCORD_MENTION", "").strip()
    username = os.getenv("DISCORD_USERNAME", "Veille Alternance").strip() or "Veille Alternance"
    max_jobs = env_int("DISCORD_MAX_OFFERS", len(jobs))
    batch_size = min(10, max(1, env_int("DISCORD_BATCH_SIZE", 5)))
    jobs_to_send = jobs[:max_jobs]

    for webhook_url in webhooks:
        for start in range(0, len(jobs_to_send), batch_size):
            batch = jobs_to_send[start : start + batch_size]
            payload = {
                "username": username,
                "content": f"{mention} {len(batch)} nouvelle(s) offre(s) alternance trouvee(s).".strip(),
                "embeds": [job_to_discord_embed(job) for job in batch],
            }
            request = Request(
                webhook_url,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "alternance-watch/1.0 (+script personnel)",
                },
                method="POST",
            )
            try:
                with urlopen(request, timeout=40) as response:
                    response.read()
            except HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                raise RuntimeError(f"Erreur webhook Discord {exc.code}: {body[:500]}") from exc
            except URLError as exc:
                raise RuntimeError(f"Impossible de contacter Discord: {exc}") from exc
    return True


def send_email(jobs: list[Job], report_path: Path | None = None) -> bool:
    if not smtp_configured():
        print("Email non envoye: SMTP_HOST et EMAIL_TO ne sont pas configures dans .env.")
        return False

    host = os.environ["SMTP_HOST"].strip()
    port = env_int("SMTP_PORT", 587)
    username = os.getenv("SMTP_USER", "").strip()
    password = os.getenv("SMTP_PASSWORD", "").strip()
    email_from = os.getenv("EMAIL_FROM", username).strip()
    recipients = env_list("EMAIL_TO")

    if not email_from:
        raise ConfigError("EMAIL_FROM ou SMTP_USER doit etre renseigne.")
    if username and not password:
        raise ConfigError("SMTP_PASSWORD est requis quand SMTP_USER est renseigne.")

    count = len(jobs)
    title = f"{count} nouvelle(s) offre(s) alternance Cloud/Data/DevOps"
    text_body = markdown_report(jobs, title)
    if report_path:
        text_body += f"\nRapport local: {report_path}\n"

    message = EmailMessage()
    message["Subject"] = title
    message["From"] = email_from
    message["To"] = ", ".join(recipients)
    message.set_content(text_body)
    message.add_alternative(html_report(jobs, title), subtype="html")

    context = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=context, timeout=40) as server:
            if username:
                server.login(username, password)
            server.send_message(message)
    else:
        with smtplib.SMTP(host, port, timeout=40) as server:
            server.starttls(context=context)
            if username:
                server.login(username, password)
            server.send_message(message)
    return True


def send_test_email() -> bool:
    fake = Job(
        uid="test",
        title="Test alternance DevOps Cloud",
        company="CGI",
        location="Paris / hybride",
        url="https://example.com",
        partner="test",
        created_at=dt.datetime.now().isoformat(),
        contract="Apprentissage",
        remote="hybrid",
        rome_codes="M1801",
        score=99,
        reasons=["test configuration email"],
        description="Ceci est un email de test du script de veille alternance.",
    )
    return send_email([fake])


def send_test_discord() -> bool:
    fake = Job(
        uid="test-discord",
        title="Test alternance DevOps Cloud",
        company="CGI",
        location="Paris / hybride",
        url="https://example.com",
        partner="test",
        created_at=dt.datetime.now().isoformat(),
        contract="Apprentissage",
        remote="hybrid",
        rome_codes="M1801",
        score=99,
        reasons=["test configuration Discord"],
        description="Ceci est un message de test du webhook Discord.",
    )
    return send_discord([fake])


def self_test() -> None:
    raw = {
        "identifier": {"partner_label": "France Travail", "partner_job_id": "123", "id": None},
        "workplace": {
            "name": "CGI",
            "brand": None,
            "legal_name": "CGI FRANCE",
            "location": {"address": "Paris"},
            "description": "Equipe cloud Azure et Kubernetes",
        },
        "apply": {"url": "https://example.com/apply"},
        "contract": {"type": ["Apprentissage"], "remote": "hybrid"},
        "offer": {
            "title": "Alternance DevOps Cloud",
            "description": "Python, Linux, Docker, Terraform, pipelines CI/CD",
            "desired_skills": ["Python", "SQL"],
            "to_be_acquired_skills": ["Kubernetes", "Azure"],
            "rome_codes": ["M1801"],
            "publication": {"creation": "2026-05-22T08:00:00Z"},
        },
    }
    job = normalize_job(raw)
    assert job.score >= 80, job
    assert "CGI" in job.company
    assert job.uid == "France Travail:123"
    priority_low_score = Job(
        uid="priority",
        title="Alternance infrastructure",
        company="CGI",
        location="Paris",
        url="https://example.com/priority",
        partner="test",
        created_at="2026-05-20T08:00:00Z",
        contract="Apprentissage",
        remote="",
        rome_codes="M1801",
        score=30,
        reasons=["entreprise prioritaire: CGI"],
        description="Offre prioritaire par entreprise.",
    )
    regular_high_score = Job(
        uid="regular",
        title="Alternance cloud data",
        company="Entreprise non prioritaire",
        location="Paris",
        url="https://example.com/regular",
        partner="test",
        created_at="2026-05-22T08:00:00Z",
        contract="Apprentissage",
        remote="",
        rome_codes="M1801",
        score=140,
        reasons=["titre: cloud"],
        description="Offre tres scoree mais hors entreprises ciblees.",
    )
    assert prioritize_jobs([regular_high_score, priority_low_score])[0].uid == "priority"
    print("Self-test OK.")


def print_config_status() -> None:
    load_dotenv(ROOT / ".env")
    checks = [
        ("LBA_API_TOKEN", bool(os.getenv("LBA_API_TOKEN", "").strip()), "obligatoire pour appeler l'API"),
        ("DATABASE_URL", bool(os.getenv("DATABASE_URL", "").strip()), "obligatoire pour le cloud, SQLite en local sinon"),
        ("DISCORD_WEBHOOK_URL(S)", discord_configured(), "obligatoire pour recevoir les liens dans Discord"),
        ("OUTPUT_DIR", bool(str(output_dir()).strip()), "dossier des rapports locaux"),
    ]

    print("Configuration Alternance Watcher")
    print("--------------------------------")
    for name, ok, note in checks:
        status = "OK" if ok else "MANQUANT"
        print(f"{status:8} {name} - {note}")

    if not os.getenv("DATABASE_URL", "").strip():
        print("\nCloud: ajoute DATABASE_URL en secret GitHub pour activer Supabase/PostgreSQL.")
    if not discord_configured():
        print("Discord: ajoute DISCORD_WEBHOOK_URL en secret GitHub et dans .env pour les tests locaux.")


def print_offer_rows(rows: list[Any]) -> None:
    if not rows:
        print("Aucune offre en base.")
        return
    for row in rows:
        print(
            f"- [{row['application_status']}] score {row['score']} | "
            f"{row['company']} | {row['title']} | uid={row['uid']}\n  {row['url']}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Recoit automatiquement les nouvelles offres d'alternance Cloud/Data/DevOps.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """
            Exemples:
              python3 offres_alternance.py --no-email
              python3 offres_alternance.py --test-email
              python3 offres_alternance.py --max 15
            """
        ),
    )
    parser.add_argument("--no-email", action="store_true", help="Genere seulement le rapport local.")
    parser.add_argument("--no-discord", action="store_true", help="N'envoie pas de notification Discord.")
    parser.add_argument("--dry-run", action="store_true", help="N'enregistre pas les offres comme deja vues.")
    parser.add_argument("--links-only", action="store_true", help="Genere seulement les liens JobTeaser/WTTJ/Indeed/carrieres.")
    parser.add_argument("--reset-seen", action="store_true", help="Oublie les offres deja vues.")
    parser.add_argument("--test-email", action="store_true", help="Envoie un email de test puis quitte.")
    parser.add_argument("--test-discord", action="store_true", help="Envoie un message Discord de test puis quitte.")
    parser.add_argument("--self-test", action="store_true", help="Teste le scoring sans appeler l'API.")
    parser.add_argument("--check-config", action="store_true", help="Verifie la configuration sans afficher les secrets.")
    parser.add_argument("--output-dir", help="Dossier ou ecrire les fichiers d'offres.")
    parser.add_argument("--list-offers", action="store_true", help="Liste les offres sauvegardees.")
    parser.add_argument("--status", default="", help="Filtre ou nouveau statut candidature.")
    parser.add_argument("--set-status", default="", help="UID de l'offre a mettre a jour.")
    parser.add_argument("--notes", default="", help="Note a ajouter avec --set-status.")
    parser.add_argument("--export-csv", action="store_true", help="Exporte le suivi en CSV.")
    parser.add_argument("--max", type=int, default=25, help="Nombre maximum de nouvelles offres dans l'email.")
    return parser.parse_args()


def main() -> int:
    load_dotenv(ROOT / ".env")
    args = parse_args()
    if args.output_dir:
        os.environ["OUTPUT_DIR"] = args.output_dir

    DATA_DIR.mkdir(exist_ok=True)

    if args.self_test:
        self_test()
        return 0

    if args.check_config:
        print_config_status()
        return 0

    store = JobStore.open()
    store.init_schema()

    if args.test_email:
        if send_test_email():
            print("Email de test envoye.")
        store.close()
        return 0

    if args.test_discord:
        if send_test_discord():
            print("Message Discord de test envoye.")
        store.close()
        return 0

    if args.list_offers:
        print_offer_rows(store.recent_offers(args.max, args.status))
        store.close()
        return 0

    if args.set_status:
        store.update_application_status(args.set_status, args.status or "to_apply", args.notes)
        print(f"Statut mis a jour pour {args.set_status}: {args.status or 'to_apply'}")
        store.close()
        return 0

    if args.export_csv:
        path = store.export_csv(output_dir() / "suivi_candidatures.csv")
        print(f"Export CSV cree: {path}")
        store.close()
        return 0

    if args.links_only:
        now = dt.datetime.now().strftime("%Y-%m-%d_%H%M")
        report_path = write_report(
            [],
            f"Recherches plateformes alternance sans LinkedIn - {now}",
            "Rapport de liens pour chercher manuellement hors LinkedIn.",
        )
        print(f"Rapport de liens genere: {report_path}")
        store.close()
        return 0

    if args.reset_seen:
        store.reset_notifications()
        print("Historique des offres vues reinitialise.")

    run_id = store.start_run()
    jobs: list[Job] = []
    fresh_jobs: list[Job] = []
    try:
        jobs = collect_jobs()
        if args.dry_run:
            fresh_jobs = prioritize_jobs(store.unnotified_jobs(jobs))[: args.max]
        else:
            fresh_jobs = prioritize_jobs(store.upsert_jobs(jobs))[: args.max]

        notified_count = 0
        if fresh_jobs:
            report_path = write_report(fresh_jobs)
            channels = ["file"]
            print(f"{len(fresh_jobs)} nouvelle(s) offre(s) trouvee(s). Rapport: {report_path}")
            if not args.no_email and send_email(fresh_jobs, report_path):
                channels.append("email")
            if not args.no_discord and send_discord(fresh_jobs):
                channels.append("discord")
            if not args.dry_run:
                store.mark_notified(fresh_jobs, channels)
            notified_count = len(fresh_jobs)
        else:
            status_path = write_status("Aucune nouvelle offre non recue.")
            print(f"Aucune nouvelle offre. Statut: {status_path}")

        store.finish_run(run_id, "success", len(jobs), len(fresh_jobs), notified_count)
    except Exception as exc:
        store.rollback()
        store.finish_run(run_id, "error", len(jobs), len(fresh_jobs), 0, str(exc))
        raise
    finally:
        store.close()

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ConfigError as exc:
        print(f"Configuration incomplete: {exc}", file=sys.stderr)
        raise SystemExit(2)
    except KeyboardInterrupt:
        print("Arrete.")
        raise SystemExit(130)
