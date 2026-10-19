#!/usr/bin/env python3
"""Minimal server-side authentication and static host for the Eridant demo.

No credentials or signing secrets live in the source. Users are provisioned with
the ``create-user`` command, passwords are stored as salted PBKDF2-HMAC-SHA256
hashes in SQLite, and browsers receive only an opaque, HttpOnly session cookie.
"""

import argparse
import csv
import getpass
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from io import BytesIO
from io import StringIO as io_StringIO
from dataclasses import dataclass
from email.utils import formatdate
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlsplit


APP_ROOT = Path(__file__).resolve().parent
DEFAULT_DB = Path(os.environ.get("SIGMA_AUTH_DB", APP_ROOT / "sigma-auth.db"))
PBKDF2_ITERATIONS = 600_000
MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 1_024
SESSION_ABSOLUTE_SECONDS = 8 * 60 * 60
SESSION_IDLE_SECONDS = 30 * 60
LOGIN_WINDOW_SECONDS = 15 * 60
LOGIN_BLOCK_SECONDS = 15 * 60
EMAIL_FAILURE_LIMIT = 5
IP_FAILURE_LIMIT = 25
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
ALLOWED_ROLES = {"analyst", "supervisor", "admin"}
# who may undo an override: the checker in the bank's maker-checker control
CRE_UNDO_ROLES = {"supervisor", "admin"}
DOCUMENT_RENDER_MAX_BYTES = 25 * 1024 * 1024
DOCUMENT_RENDER_MAX_EXPANDED_BYTES = 100 * 1024 * 1024
DOCUMENT_RENDER_TIMEOUT_SECONDS = 45
VENDOR_ASSETS = {
    "/vendor/pdf.min.js": ("vendor/pdf.min.js", "text/javascript; charset=utf-8"),
    "/vendor/pdf.worker.min.js": (
        "vendor/pdf.worker.min.js",
        "text/javascript; charset=utf-8",
    ),
}
DEMO_PACKETS = {
    "01_decline_as_presented": {
        "01_financial_statements.docx",
        "02_tax_return_1120s.docx",
        "03_loan_application.docx",
        "04_state_filing_si550.docx",
        "05_prior_credit_memo.docx",
        "Redwood_Summit_Credit_Memo_FY2023.docx",
    },
    # CRE sample: borrower package (01-08, 11) plus the bank-file documents
    # (09 appraisal, 10 existing loan agreement). Document 12, the bank's
    # credit memo, is the expected answer and is never served.
    "cre_01_cedar_grove_refinance": {
        "01_Cedar_Grove_Borrower_Loan_Request.pdf",
        "02_Cedar_Grove_Current_Rent_Roll.pdf",
        "03_Cedar_Grove_Property_Operating_Statements.pdf",
        "04_Cedar_Grove_SPE_Financial_Statements.pdf",
        "05_Cedar_Grove_Borrower_Sponsor_Debt_Schedule.pdf",
        "06_FreshMart_Anchor_Shopping_Center_Lease.pdf",
        "07_FreshMart_Second_Amendment_to_Lease.pdf",
        "08_Cedar_Grove_Shop_Tenant_Lease_Abstracts.pdf",
        "09_Cedar_Grove_Appraisal_Report.pdf",
        "10_Cedar_Grove_Existing_Loan_Agreement.pdf",
        "11_Cedar_Grove_Covenant_Compliance_Certificate.pdf",
    },
}
DEMO_PACKET_CONTENT_TYPES = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pdf": "application/pdf",
}
CREDIT_ANALYSIS_PROMPT_VERSION = "eridant_full_document_credit_judge_v1"
CREDIT_ANALYSIS_MAX_USER_CHARS = 500_000
CREDIT_ANALYSIS_MAX_BODY_BYTES = CREDIT_ANALYSIS_MAX_USER_CHARS + 64_000
ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_API_VERSION = "2023-06-01"
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-6"
CREDIT_ANALYSIS_MAX_TOKENS = 64_000
CREDIT_ANALYSIS_TIMEOUT_SECONDS = 300


def env_int(name: str, default: int) -> int:
    raw = env_plain(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def env_bool(name: str, default: bool = False) -> bool:
    raw = env_plain(name).lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def load_dotenv(path: Optional[Path] = None) -> None:
    """Load KEY=VALUE pairs from a .env file without overriding existing env vars."""
    dotenv_path = path or (APP_ROOT / ".env")
    if not dotenv_path.is_file():
        return
    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key or key in os.environ:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ[key] = value


def now_seconds() -> int:
    return int(time.time())


def normalize_email(value: str) -> str:
    email = (value or "").strip().lower()
    if len(email) > 254 or not EMAIL_RE.fullmatch(email):
        raise ValueError("Enter a valid email address.")
    return email


def env_plain(name: str) -> str:
    value = os.environ.get(name, "")
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1].strip()
    return value


def validate_document_bytes(data: bytes) -> None:
    """Apply the server-side equivalent of the browser document safety checks."""
    if not data or len(data) > DOCUMENT_RENDER_MAX_BYTES:
        raise ValueError("invalid_document_size")
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            entries = archive.infolist()
            if len(entries) > 2_000:
                raise ValueError("too_many_entries")
            names = {entry.filename for entry in entries}
            if "[Content_Types].xml" not in names or "word/document.xml" not in names:
                raise ValueError("missing_document_parts")
            if "word/vbaProject.bin" in names:
                raise ValueError("macros_not_allowed")
            expanded = compressed = 0
            for entry in entries:
                parts = entry.filename.replace("\\", "/").split("/")
                if entry.filename.startswith("/") or ".." in parts:
                    raise ValueError("unsafe_entry_path")
                if entry.flag_bits & 1:
                    raise ValueError("encrypted_document")
                expanded += entry.file_size
                compressed += entry.compress_size
            if expanded > DOCUMENT_RENDER_MAX_EXPANDED_BYTES:
                raise ValueError("expanded_document_too_large")
            if compressed and expanded / compressed > 250:
                raise ValueError("unsafe_compression_ratio")
    except (zipfile.BadZipFile, OSError) as exc:
        raise ValueError("invalid_document") from exc


def convert_document_to_pdf(data: bytes) -> bytes:
    """Convert a validated Word document in an isolated temporary LibreOffice profile."""
    validate_document_bytes(data)
    configured = os.environ.get("SIGMA_SOFFICE", "").strip()
    configured_path = (
        configured
        if configured and Path(configured).is_file()
        else (shutil.which(configured) or "" if configured else "")
    )
    candidates = [
        configured_path,
        shutil.which("soffice") or "",
        shutil.which("libreoffice") or "",
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    ]
    executable = next((item for item in candidates if item and Path(item).is_file()), "")
    if not executable:
        raise RuntimeError("pdf_converter_unavailable")
    with tempfile.TemporaryDirectory(prefix="eridant-document-render-") as temp_name:
        work = Path(temp_name)
        source = work / "document.docx"
        output = work / "document.pdf"
        profile = work / "libreoffice-profile"
        cache = work / "cache"
        source.write_bytes(data)
        profile.mkdir()
        cache.mkdir()
        env = os.environ.copy()
        env["HOME"] = str(work)
        env["XDG_CACHE_HOME"] = str(cache)
        env["XDG_CONFIG_HOME"] = str(work / "config")
        env["SAL_DISABLE_OPENCL"] = "1"
        result = subprocess.run(
            [
                executable,
                f"-env:UserInstallation={profile.resolve().as_uri()}",
                "--headless",
                "--convert-to",
                "pdf:writer_pdf_Export",
                "--outdir",
                str(work),
                str(source),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=DOCUMENT_RENDER_TIMEOUT_SECONDS,
            check=False,
            env=env,
        )
        if result.returncode or not output.is_file():
            raise RuntimeError("pdf_conversion_failed")
        pdf = output.read_bytes()
        if not pdf.startswith(b"%PDF-") or len(pdf) > 50 * 1024 * 1024:
            raise RuntimeError("invalid_pdf_output")
        return pdf


def password_material(password: str, pepper: bytes) -> bytes:
    if not isinstance(password, str):
        password = ""
    raw = password.encode("utf-8", errors="strict")
    if len(raw) > 4_096:
        # Bound authentication work for maliciously large inputs.
        raw = hashlib.sha256(raw).digest()
    return raw + b"\0" + pepper


def derive_password(password: str, salt: bytes, iterations: int, pepper: bytes) -> bytes:
    return hashlib.pbkdf2_hmac(
        "sha256", password_material(password, pepper), salt, iterations, dklen=32
    )


class AuthStore:
    def __init__(
        self,
        db_path: Path,
        *,
        iterations: int = PBKDF2_ITERATIONS,
        pepper: Optional[bytes] = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.iterations = iterations
        self.pepper = pepper if pepper is not None else os.environ.get(
            "SIGMA_PASSWORD_PEPPER", ""
        ).encode("utf-8")
        self._dummy_salt = secrets.token_bytes(16)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    display_name TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('analyst', 'supervisor', 'admin')),
                    password_hash BLOB NOT NULL,
                    password_salt BLOB NOT NULL,
                    password_iterations INTEGER NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
                    created_at INTEGER NOT NULL,
                    password_changed_at INTEGER NOT NULL,
                    last_login_at INTEGER
                );

                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    csrf_token TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    last_seen_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL
                );

                CREATE INDEX IF NOT EXISTS sessions_user_id_idx
                    ON sessions(user_id);
                CREATE INDEX IF NOT EXISTS sessions_expires_at_idx
                    ON sessions(expires_at);

                CREATE TABLE IF NOT EXISTS login_limits (
                    bucket TEXT PRIMARY KEY,
                    failures INTEGER NOT NULL,
                    window_started INTEGER NOT NULL,
                    blocked_until INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS signup_invites (
                    token_hash TEXT PRIMARY KEY,
                    email TEXT NOT NULL COLLATE NOCASE,
                    role TEXT NOT NULL CHECK (role IN ('analyst', 'supervisor', 'admin')),
                    created_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    used_at INTEGER
                );

                CREATE INDEX IF NOT EXISTS signup_invites_expires_at_idx
                    ON signup_invites(expires_at);

                CREATE TABLE IF NOT EXISTS cre_overrides (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    deal_id TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    item_kind TEXT NOT NULL,
                    item_title TEXT NOT NULL,
                    action TEXT NOT NULL,
                    from_severity TEXT NOT NULL,
                    to_severity TEXT NOT NULL,
                    reason_code TEXT NOT NULL,
                    note TEXT NOT NULL,
                    evidence TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('active', 'reverted')),
                    created_by_id INTEGER NOT NULL,
                    created_by_email TEXT NOT NULL,
                    created_by_name TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    reverted_by_email TEXT,
                    reverted_at INTEGER,
                    revert_note TEXT
                );

                CREATE INDEX IF NOT EXISTS cre_overrides_deal_idx
                    ON cre_overrides(deal_id, status);

                CREATE TABLE IF NOT EXISTS cre_audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    deal_id TEXT NOT NULL,
                    ts INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    user_email TEXT NOT NULL,
                    user_name TEXT NOT NULL,
                    user_role TEXT NOT NULL,
                    event TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    item_title TEXT NOT NULL,
                    before_json TEXT NOT NULL,
                    after_json TEXT NOT NULL,
                    reason_code TEXT NOT NULL,
                    note TEXT NOT NULL,
                    evidence TEXT NOT NULL,
                    deal_label TEXT NOT NULL,
                    context_json TEXT NOT NULL,
                    session_ref TEXT NOT NULL,
                    client_ip TEXT NOT NULL,
                    prev_hash TEXT NOT NULL,
                    entry_hash TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS cre_audit_deal_idx
                    ON cre_audit_log(deal_id, id);
                """
            )
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(cre_overrides)")}
            for col in ("created_by_role", "reverted_by_name", "reverted_by_role"):
                if col not in cols:
                    conn.execute(f"ALTER TABLE cre_overrides ADD COLUMN {col} TEXT")
        self._migrate_roles()

    def _migrate_roles(self) -> None:
        """Older databases only allowed analyst/admin; rebuild those tables so supervisor is valid."""
        conn = sqlite3.connect(str(self.db_path), timeout=5, isolation_level=None)
        try:
            for table in ("users", "signup_invites"):
                row = conn.execute(
                    "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
                ).fetchone()
                if not row or "'supervisor'" in row[0]:
                    continue
                new_sql = row[0].replace(
                    "CHECK (role IN ('analyst', 'admin'))",
                    "CHECK (role IN ('analyst', 'supervisor', 'admin'))",
                ).replace(f"CREATE TABLE {table}", f"CREATE TABLE {table}__new", 1)
                conn.execute("PRAGMA foreign_keys = OFF")
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(new_sql)
                conn.execute(f"INSERT INTO {table}__new SELECT * FROM {table}")
                conn.execute(f"DROP TABLE {table}")
                conn.execute(f"ALTER TABLE {table}__new RENAME TO {table}")
                conn.execute("COMMIT")
                conn.execute("PRAGMA foreign_keys = ON")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS signup_invites_expires_at_idx ON signup_invites(expires_at)"
            )
        finally:
            conn.close()

    def user_count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM users WHERE active = 1").fetchone()
        return int(row["n"])

    def _validate_new_user(
        self, email: str, display_name: str, password: str, role: str
    ):
        email = normalize_email(email)
        name = (display_name or "").strip()
        if not name or len(name) > 120:
            raise ValueError("Display name must be between 1 and 120 characters.")
        if role not in ALLOWED_ROLES:
            raise ValueError("Role must be analyst, supervisor or admin.")
        if len(password) < MIN_PASSWORD_LENGTH:
            raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
        if len(password) > MAX_PASSWORD_LENGTH:
            raise ValueError(f"Password cannot exceed {MAX_PASSWORD_LENGTH} characters.")
        return email, name

    def upsert_user(self, email: str, display_name: str, password: str, role: str) -> str:
        email, name = self._validate_new_user(email, display_name, password, role)
        salt = secrets.token_bytes(16)
        password_hash = derive_password(password, salt, self.iterations, self.pepper)
        ts = now_seconds()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM users WHERE email = ? COLLATE NOCASE", (email,)
            ).fetchone()
            if row:
                conn.execute(
                    """
                    UPDATE users SET display_name = ?, role = ?, password_hash = ?,
                        password_salt = ?, password_iterations = ?, password_changed_at = ?,
                        active = 1
                    WHERE id = ?
                    """,
                    (name, role, password_hash, salt, self.iterations, ts, int(row["id"])),
                )
                return "updated"
            conn.execute(
                """
                INSERT INTO users (
                    email, display_name, role, password_hash, password_salt,
                    password_iterations, created_at, password_changed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (email, name, role, password_hash, salt, self.iterations, ts, ts),
            )
            return "created"

    def create_user(self, email: str, display_name: str, password: str, role: str) -> None:
        email, _name = self._validate_new_user(email, display_name, password, role)
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT 1 FROM users WHERE email = ? COLLATE NOCASE", (email,)
            ).fetchone()
        if existing:
            raise ValueError("A user with that email already exists.")
        self.upsert_user(email, display_name, password, role)

    def reset_password(self, email: str, password: str) -> None:
        email = normalize_email(email)
        if len(password) < MIN_PASSWORD_LENGTH:
            raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
        if len(password) > MAX_PASSWORD_LENGTH:
            raise ValueError(f"Password cannot exceed {MAX_PASSWORD_LENGTH} characters.")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT display_name, role FROM users WHERE email = ? COLLATE NOCASE AND active = 1",
                (email,),
            ).fetchone()
        if not row:
            raise ValueError("No active user with that email exists.")
        self.upsert_user(email, row["display_name"], password, row["role"])

    def create_invite(self, email: str, role: str, valid_hours: int = 24) -> str:
        email = normalize_email(email)
        if role not in ALLOWED_ROLES:
            raise ValueError("Role must be analyst, supervisor or admin.")
        if not 1 <= valid_hours <= 168:
            raise ValueError("Invite lifetime must be between 1 and 168 hours.")
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
        ts = now_seconds()
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT 1 FROM users WHERE email = ? COLLATE NOCASE AND active = 1", (email,)
            ).fetchone()
            if existing:
                raise ValueError("An active user with that email already exists.")
            conn.execute(
                "DELETE FROM signup_invites WHERE email = ? COLLATE NOCASE AND used_at IS NULL",
                (email,),
            )
            conn.execute(
                """
                INSERT INTO signup_invites (
                    token_hash, email, role, created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (token_hash, email, role, ts, ts + valid_hours * 60 * 60),
            )
        return token

    def get_invite(self, token: str) -> Optional[Dict[str, object]]:
        if not isinstance(token, str) or not token or len(token) > 256:
            return None
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        ts = now_seconds()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT email, role, expires_at FROM signup_invites
                WHERE token_hash = ? AND used_at IS NULL AND expires_at > ?
                """,
                (token_hash, ts),
            ).fetchone()
        if not row:
            return None
        return {"email": row["email"], "role": row["role"], "expiresAt": row["expires_at"]}

    def register_with_invite(
        self, token: str, email: str, display_name: str, password: str
    ) -> Dict[str, object]:
        normalized = normalize_email(email)
        if not isinstance(token, str) or not token or len(token) > 256:
            return {"status": "invalid_invite"}
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        ts = now_seconds()

        # Read the invite role before deriving the password, then re-check it in
        # an immediate transaction so two requests cannot consume one invite.
        invite = self.get_invite(token)
        if not invite or normalized != invite["email"]:
            return {"status": "invalid_invite"}
        normalized, name = self._validate_new_user(
            normalized, display_name, password, invite["role"]
        )
        salt = secrets.token_bytes(16)
        password_hash = derive_password(password, salt, self.iterations, self.pepper)

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT email, role FROM signup_invites
                WHERE token_hash = ? AND used_at IS NULL AND expires_at > ?
                """,
                (token_hash, ts),
            ).fetchone()
            if not row or normalized != row["email"]:
                return {"status": "invalid_invite"}
            try:
                cursor = conn.execute(
                    """
                    INSERT INTO users (
                        email, display_name, role, password_hash, password_salt,
                        password_iterations, created_at, password_changed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        normalized,
                        name,
                        row["role"],
                        password_hash,
                        salt,
                        self.iterations,
                        ts,
                        ts,
                    ),
                )
            except sqlite3.IntegrityError:
                return {"status": "existing_user"}
            conn.execute(
                "UPDATE signup_invites SET used_at = ? WHERE token_hash = ? AND used_at IS NULL",
                (ts, token_hash),
            )
            user_id = int(cursor.lastrowid)
            return {
                "status": "ok",
                "user": {
                    "id": user_id,
                    "email": normalized,
                    "displayName": name,
                    "role": row["role"],
                },
            }

    @staticmethod
    def _limit_bucket(kind: str, value: str) -> str:
        return hashlib.sha256(f"{kind}:{value}".encode("utf-8")).hexdigest()

    def _is_blocked(self, conn: sqlite3.Connection, bucket: str, ts: int) -> bool:
        row = conn.execute(
            "SELECT blocked_until FROM login_limits WHERE bucket = ?", (bucket,)
        ).fetchone()
        return bool(row and int(row["blocked_until"]) > ts)

    def _record_failure(
        self, conn: sqlite3.Connection, bucket: str, limit: int, ts: int
    ) -> None:
        row = conn.execute(
            "SELECT failures, window_started FROM login_limits WHERE bucket = ?",
            (bucket,),
        ).fetchone()
        if not row or ts - int(row["window_started"]) >= LOGIN_WINDOW_SECONDS:
            failures = 1
            window_started = ts
        else:
            failures = int(row["failures"]) + 1
            window_started = int(row["window_started"])
        blocked_until = ts + LOGIN_BLOCK_SECONDS if failures >= limit else 0
        conn.execute(
            """
            INSERT INTO login_limits (bucket, failures, window_started, blocked_until)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(bucket) DO UPDATE SET
                failures = excluded.failures,
                window_started = excluded.window_started,
                blocked_until = excluded.blocked_until
            """,
            (bucket, failures, window_started, blocked_until),
        )

    def authenticate(self, email: str, password: str, client_ip: str) -> Dict[str, object]:
        try:
            normalized = normalize_email(email)
        except ValueError:
            normalized = "invalid@example.invalid"
        email_bucket = self._limit_bucket("email", normalized)
        ip_bucket = self._limit_bucket("ip", client_ip or "unknown")
        ts = now_seconds()

        with self._connect() as conn:
            if self._is_blocked(conn, email_bucket, ts) or self._is_blocked(
                conn, ip_bucket, ts
            ):
                return {"status": "blocked"}

            row = conn.execute(
                "SELECT * FROM users WHERE email = ? COLLATE NOCASE", (normalized,)
            ).fetchone()
            salt = bytes(row["password_salt"]) if row else self._dummy_salt
            iterations = int(row["password_iterations"]) if row else self.iterations
            expected = bytes(row["password_hash"]) if row else bytes(32)
            candidate = derive_password(password, salt, iterations, self.pepper)
            valid = bool(row and row["active"] and hmac.compare_digest(candidate, expected))

            if not valid:
                self._record_failure(conn, email_bucket, EMAIL_FAILURE_LIMIT, ts)
                self._record_failure(conn, ip_bucket, IP_FAILURE_LIMIT, ts)
                return {"status": "invalid"}

            conn.execute("DELETE FROM login_limits WHERE bucket = ?", (email_bucket,))
            conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (ts, row["id"]))
            return {
                "status": "ok",
                "user": {
                    "id": int(row["id"]),
                    "email": row["email"],
                    "displayName": row["display_name"],
                    "role": row["role"],
                },
            }

    def create_session(self, user_id: int) -> Dict[str, object]:
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
        csrf_token = secrets.token_urlsafe(32)
        ts = now_seconds()
        expires_at = ts + SESSION_ABSOLUTE_SECONDS
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM sessions WHERE expires_at <= ? OR last_seen_at <= ?",
                (ts, ts - SESSION_IDLE_SECONDS),
            )
            conn.execute(
                """
                DELETE FROM sessions WHERE token_hash IN (
                    SELECT token_hash FROM sessions WHERE user_id = ?
                    ORDER BY created_at DESC LIMIT -1 OFFSET 4
                )
                """,
                (user_id,),
            )
            conn.execute(
                """
                INSERT INTO sessions (
                    token_hash, user_id, csrf_token, created_at, last_seen_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (token_hash, user_id, csrf_token, ts, ts, expires_at),
            )
        return {"token": token, "csrfToken": csrf_token, "expiresAt": expires_at}

    def get_session(self, token: str) -> Optional[Dict[str, object]]:
        if not token or len(token) > 256:
            return None
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        ts = now_seconds()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT s.*, u.email, u.display_name, u.role, u.active
                FROM sessions s JOIN users u ON u.id = s.user_id
                WHERE s.token_hash = ?
                """,
                (token_hash,),
            ).fetchone()
            if not row:
                return None
            if (
                not row["active"]
                or int(row["expires_at"]) <= ts
                or int(row["last_seen_at"]) <= ts - SESSION_IDLE_SECONDS
            ):
                conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
                return None
            if ts - int(row["last_seen_at"]) >= 60:
                conn.execute(
                    "UPDATE sessions SET last_seen_at = ? WHERE token_hash = ?",
                    (ts, token_hash),
                )
            return {
                "tokenHash": token_hash,
                "csrfToken": row["csrf_token"],
                "expiresAt": int(row["expires_at"]),
                "user": {
                    "id": int(row["user_id"]),
                    "email": row["email"],
                    "displayName": row["display_name"],
                    "role": row["role"],
                },
            }

    def revoke_session(self, token: str) -> None:
        if not token:
            return
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with self._connect() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))


# ---------------- CRE overrides and audit trail ----------------
# An override is the analyst's decision on one flagged item; the audit log is the
# append-only record of every such decision. Nothing in either table is ever
# updated in place except an override's status flipping to "reverted", which is
# itself logged as a new audit entry.
CRE_OVERRIDE_ACTIONS = {
    "clear": "Cleared - not an issue",
    "resolved": "Resolved with new evidence",
    "accept_condition": "Accepted with condition",
    "change_severity": "Severity changed",
    "dismiss": "Dismissed",
}
CRE_REASON_CODES = {
    "policy_exception": "Policy exception",
    "new_evidence": "New evidence",
    "false_positive": "False positive",
    "mitigated": "Mitigated by structure",
    "other": "Other",
}
CRE_ROLE_LABELS = {"analyst": "Credit Analyst", "supervisor": "Credit Supervisor", "admin": "Administrator"}
CRE_EVENT_LABELS = {
    "override_created": "Override",
    "item_dismissed": "Dismissed",
    "override_reverted": "Override undone",
    "covenant_adjustment": "Covenant adjustment",
}
CRE_SEVERITIES = {"CRITICAL", "HIGH", "MEDIUM", "LOW", "PASS", "NODATA", "REVIEW", "OK", ""}
CRE_ITEM_KINDS = {"finding", "verification", "assistant"}
CRE_AUDIT_EVENTS = {"covenant_adjustment"}
CRE_DEAL_ID_RE = re.compile(r"^[0-9a-f]{64}$")
CRE_ITEM_ID_RE = re.compile(r"^[A-Za-z0-9:_.-]{1,64}$")


def _cre_text(value: object, max_len: int) -> str:
    text = str(value or "").replace("\r", " ").strip()
    return text[:max_len]


def _cre_csv_cell(value: object) -> str:
    text = str(value if value is not None else "")
    # spreadsheet formula injection guard
    return "'" + text if text[:1] in ("=", "+", "-", "@") else text


class CreAuditStore:
    def __init__(self, store: "AuthStore") -> None:
        self.store = store

    def _append(self, conn: sqlite3.Connection, entry: Dict[str, object]) -> Dict[str, object]:
        row = conn.execute(
            "SELECT entry_hash FROM cre_audit_log WHERE deal_id = ? ORDER BY id DESC LIMIT 1",
            (entry["deal_id"],),
        ).fetchone()
        prev_hash = row["entry_hash"] if row else "0" * 64
        canonical = json.dumps(entry, sort_keys=True, separators=(",", ":"))
        entry_hash = hashlib.sha256((prev_hash + canonical).encode("utf-8")).hexdigest()
        conn.execute(
            """
            INSERT INTO cre_audit_log (
                deal_id, ts, user_id, user_email, user_name, user_role, event, item_id,
                item_title, before_json, after_json, reason_code, note, evidence,
                deal_label, context_json, session_ref, client_ip, prev_hash, entry_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry["deal_id"], entry["ts"], entry["user_id"], entry["user_email"],
                entry["user_name"], entry["user_role"], entry["event"], entry["item_id"],
                entry["item_title"], entry["before_json"], entry["after_json"],
                entry["reason_code"], entry["note"], entry["evidence"], entry["deal_label"],
                entry["context_json"], entry["session_ref"], entry["client_ip"],
                prev_hash, entry_hash,
            ),
        )
        return {**entry, "prev_hash": prev_hash, "entry_hash": entry_hash}

    @staticmethod
    def _override_row(row: sqlite3.Row) -> Dict[str, object]:
        return {
            "id": int(row["id"]),
            "itemId": row["item_id"],
            "itemKind": row["item_kind"],
            "itemTitle": row["item_title"],
            "action": row["action"],
            "actionLabel": CRE_OVERRIDE_ACTIONS.get(row["action"], row["action"]),
            "fromSeverity": row["from_severity"],
            "toSeverity": row["to_severity"],
            "reasonCode": row["reason_code"],
            "reasonLabel": CRE_REASON_CODES.get(row["reason_code"], row["reason_code"]),
            "note": row["note"],
            "evidence": row["evidence"],
            "status": row["status"],
            "createdBy": row["created_by_name"],
            "createdByEmail": row["created_by_email"],
            "createdByRole": row["created_by_role"] or "",
            "createdAt": int(row["created_at"]),
            "revertedBy": row["reverted_by_name"] or row["reverted_by_email"] or "",
            "revertedByEmail": row["reverted_by_email"] or "",
            "revertedByRole": row["reverted_by_role"] or "",
            "revertedAt": int(row["reverted_at"]) if row["reverted_at"] else None,
            "revertNote": row["revert_note"] or "",
        }

    def active_overrides(self, deal_id: str) -> List[Dict[str, object]]:
        with self.store._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM cre_overrides WHERE deal_id = ? AND status = 'active' ORDER BY id",
                (deal_id,),
            ).fetchall()
        return [self._override_row(r) for r in rows]

    def override_history(self, deal_id: str) -> List[Dict[str, object]]:
        """Every decision ever made on the deal, including undone ones, oldest first."""
        with self.store._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM cre_overrides WHERE deal_id = ? ORDER BY id", (deal_id,)
            ).fetchall()
        return [self._override_row(r) for r in rows]

    def create_override(
        self, deal_id: str, data: Dict[str, object], user: Dict[str, object], meta: Dict[str, str]
    ) -> Dict[str, object]:
        ts = now_seconds()
        with self.store._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT id FROM cre_overrides WHERE deal_id = ? AND item_id = ? AND status = 'active'",
                (deal_id, data["item_id"]),
            ).fetchone()
            if existing:
                raise ValueError("already_overridden")
            cur = conn.execute(
                """
                INSERT INTO cre_overrides (
                    deal_id, item_id, item_kind, item_title, action, from_severity,
                    to_severity, reason_code, note, evidence, status, created_by_id,
                    created_by_email, created_by_name, created_by_role, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?)
                """,
                (
                    deal_id, data["item_id"], data["item_kind"], data["item_title"],
                    data["action"], data["from_severity"], data["to_severity"],
                    data["reason_code"], data["note"], data["evidence"], user["id"],
                    user["email"], user["displayName"], user["role"], ts,
                ),
            )
            override_id = int(cur.lastrowid)
            self._append(conn, {
                "deal_id": deal_id, "ts": ts, "user_id": user["id"],
                "user_email": user["email"], "user_name": user["displayName"],
                "user_role": user["role"],
                "event": "item_dismissed" if data["action"] == "dismiss" else "override_created",
                "item_id": data["item_id"], "item_title": data["item_title"],
                "before_json": json.dumps({"severity": data["from_severity"], "status": "Open", "value": data["from_value"]}),
                "after_json": json.dumps({"severity": data["to_severity"], "status": CRE_OVERRIDE_ACTIONS[data["action"]], "overrideId": override_id}),
                "reason_code": data["reason_code"], "note": data["note"],
                "evidence": data["evidence"], "deal_label": data["deal_label"],
                "context_json": meta["context"], "session_ref": meta["session_ref"],
                "client_ip": meta["client_ip"],
            })
            row = conn.execute("SELECT * FROM cre_overrides WHERE id = ?", (override_id,)).fetchone()
        return self._override_row(row)

    def revert_override(
        self, override_id: int, note: str, deal_label: str, user: Dict[str, object], meta: Dict[str, str]
    ) -> Dict[str, object]:
        ts = now_seconds()
        with self.store._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM cre_overrides WHERE id = ? AND status = 'active'", (override_id,)
            ).fetchone()
            if not row:
                raise LookupError("not_found")
            conn.execute(
                "UPDATE cre_overrides SET status = 'reverted', reverted_by_email = ?, reverted_by_name = ?, reverted_by_role = ?, reverted_at = ?, revert_note = ? WHERE id = ?",
                (user["email"], user["displayName"], user["role"], ts, note, override_id),
            )
            self._append(conn, {
                "deal_id": row["deal_id"], "ts": ts, "user_id": user["id"],
                "user_email": user["email"], "user_name": user["displayName"],
                "user_role": user["role"], "event": "override_reverted",
                "item_id": row["item_id"], "item_title": row["item_title"],
                "before_json": json.dumps({"severity": row["to_severity"], "status": CRE_OVERRIDE_ACTIONS.get(row["action"], row["action"]), "overrideId": override_id}),
                "after_json": json.dumps({"severity": row["from_severity"], "status": "Open"}),
                "reason_code": "", "note": note, "evidence": "", "deal_label": deal_label,
                "context_json": meta["context"], "session_ref": meta["session_ref"],
                "client_ip": meta["client_ip"],
            })
        return {"id": override_id, "itemId": row["item_id"], "status": "reverted"}

    def log_event(
        self, deal_id: str, data: Dict[str, object], user: Dict[str, object], meta: Dict[str, str]
    ) -> None:
        with self.store._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._append(conn, {
                "deal_id": deal_id, "ts": now_seconds(), "user_id": user["id"],
                "user_email": user["email"], "user_name": user["displayName"],
                "user_role": user["role"], "event": data["event"],
                "item_id": data["item_id"], "item_title": data["item_title"],
                "before_json": json.dumps(data["before"]), "after_json": json.dumps(data["after"]),
                "reason_code": "", "note": data["note"], "evidence": "",
                "deal_label": data["deal_label"], "context_json": meta["context"],
                "session_ref": meta["session_ref"], "client_ip": meta["client_ip"],
            })

    def audit(self, deal_id: str) -> List[Dict[str, object]]:
        with self.store._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM cre_audit_log WHERE deal_id = ? ORDER BY id", (deal_id,)
            ).fetchall()
        out = []
        for r in rows:
            out.append({
                "id": int(r["id"]), "ts": int(r["ts"]), "userId": int(r["user_id"]), "user": r["user_name"],
                "email": r["user_email"], "role": r["user_role"], "event": r["event"],
                "itemId": r["item_id"], "itemTitle": r["item_title"],
                "before": json.loads(r["before_json"] or "{}"),
                "after": json.loads(r["after_json"] or "{}"),
                "reasonCode": r["reason_code"],
                "reason": CRE_REASON_CODES.get(r["reason_code"], r["reason_code"]),
                "note": r["note"], "evidence": r["evidence"], "deal": r["deal_label"],
                "context": json.loads(r["context_json"] or "{}"),
                "sessionRef": r["session_ref"], "clientIp": r["client_ip"],
                "entryHash": r["entry_hash"], "prevHash": r["prev_hash"],
            })
        return out


def _clean_dd_text(value: object, max_len: int = 240) -> str:
    if value is None:
        return ""
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text[:max_len]


def _is_contractor_borrower(naics: str, entity_type: str) -> bool:
    hay = f"{naics} {entity_type}".lower()
    return bool(
        re.search(
            r"contractor|construction|\b236\b|\b237\b|\b238\b|general building",
            hay,
        )
    )


def _dd_today_label() -> str:
    return time.strftime("%b %d, %Y").replace(" 0", " ")


def _norm_person_key(value: str) -> str:
    text = value.lower()
    text = re.split(r"\s*[-–—·|]\s*", text, maxsplit=1)[0]
    text = re.sub(
        r"\b(chief executive officer|chief financial officer|managing member|"
        r"president|secretary|guarantor|member|owner|ceo|cfo)\b",
        "",
        text,
    )
    return re.sub(r"[^a-z0-9]", "", text)


def _control_person_label(payload: Dict[str, object]) -> str:
    owner = _clean_dd_text(payload.get("beneficialOwnerName"))
    if not owner:
        owner = _clean_dd_text(payload.get("owner"))
    if not owner:
        beneficial = _clean_dd_text(payload.get("beneficialOwner"))
        if beneficial:
            owner = re.split(r"[·—-]", beneficial, maxsplit=1)[0].strip()
    elif re.search(r"[·—-]", owner):
        owner = re.split(r"[·—-]", owner, maxsplit=1)[0].strip()
    return owner or "—"


def _control_person_mismatch(payload: Dict[str, object]) -> bool:
    app_person = _control_person_label(payload)
    sos_officer = _clean_dd_text(payload.get("sosOfficer"))
    if not app_person or app_person == "—" or not sos_officer:
        return False
    return _norm_person_key(app_person) != _norm_person_key(sos_officer)


def _derive_cslb_license_number(entity: str) -> str:
    digits = re.sub(r"\D", "", entity)
    if not digits:
        return "1023456"
    seed = int(digits[-7:].ljust(7, "0")[:7]) % 9_000_000 + 1_000_000
    return str(seed)


def _cslb_classification(naics: str) -> str:
    hay = naics.lower()
    if re.search(r"electrical|electric", hay):
        return "C-10 — Electrical"
    if re.search(r"plumb", hay):
        return "C-36 — Plumbing"
    if re.search(r"roof", hay):
        return "C-39 — Roofing"
    return "B — General Building"


def _derive_license_expiry(entity: str) -> str:
    digits = re.sub(r"\D", "", entity) or "1234567"
    month = (int(digits[-2:]) % 12) + 1
    year = 2026 + (int(digits[-4:-2] if len(digits) >= 4 else digits[-2:]) % 3)
    return time.strftime("%b %Y", time.struct_time((year, month, 1, 0, 0, 0, 0, 0, 0)))


def _license_expired(label: str) -> bool:
    try:
        parsed = time.strptime(label, "%b %Y")
    except ValueError:
        return False
    now = time.localtime()
    return (parsed.tm_year, parsed.tm_mon) < (now.tm_year, now.tm_mon)


def _dd_row(label: str, value: str, match: str = "ok") -> Dict[str, object]:
    return {"label": label, "value": value, "match": match}


def _finalize_dd_card(card: Dict[str, object]) -> Dict[str, object]:
    if card.get("status") == "na":
        card["concernCount"] = 0
        return card
    concerns = sum(
        1
        for row in card.get("results") or []
        if isinstance(row, dict) and row.get("match") == "bad"
    )
    card["concernCount"] = concerns
    card["status"] = "mismatch" if concerns else "verified"
    return card


def _mark_dd_row(
    results: List[Dict[str, object]], label: str, value: str, match: str = "bad"
) -> None:
    for row in results:
        if row.get("label") == label:
            row["value"] = value
            row["match"] = match
            return
    results.append(_dd_row(label, value, match))


def _ensure_dd_concerns(
    card: Dict[str, object],
    seeds: List[Dict[str, str]],
    min_count: int = 2,
) -> Dict[str, object]:
    if card.get("status") == "na":
        return card
    results = list(card.get("results") or [])
    card["results"] = results
    need = max(1, min_count)
    count = sum(1 for row in results if row.get("match") == "bad")
    started_clean = count == 0
    for seed in seeds:
        if count >= need:
            break
        existing = next((row for row in results if row.get("label") == seed["label"]), None)
        if existing and existing.get("match") == "bad":
            continue
        _mark_dd_row(results, seed["label"], seed["value"], "bad")
        count += 1
    if started_clean and seeds:
        if seeds[0].get("verdict"):
            card["verdict"] = seeds[0]["verdict"]
        if seeds[0].get("compare"):
            card["packetCompare"] = seeds[0]["compare"]
    return _finalize_dd_card(card)


def build_external_due_diligence(payload: Dict[str, object]) -> Dict[str, object]:
    borrower = _clean_dd_text(payload.get("borrowerName"))
    sos_company = _clean_dd_text(payload.get("sosCompany")) or borrower or "—"
    registry_entity = _clean_dd_text(payload.get("entity")) or "—"
    app_entity = _clean_dd_text(payload.get("appEntity"))
    entity = registry_entity if registry_entity != "—" else (app_entity or "—")
    naics = _clean_dd_text(payload.get("naics"))
    entity_type = _clean_dd_text(payload.get("entityType")) or "—"
    sos_address = _clean_dd_text(payload.get("sosAddress")) or "—"
    app_address = _clean_dd_text(payload.get("address"))
    sos_officer = _clean_dd_text(payload.get("sosOfficer")) or "—"
    app_control = _control_person_label(payload)
    sos_good = bool(payload.get("sosGood"))
    name_mismatch = bool(payload.get("nameMismatch"))
    address_mismatch = bool(payload.get("addressMismatch"))
    control_mismatch = _control_person_mismatch(payload)
    debt_rise = bool(payload.get("debtFundedGrowth"))
    entity_check_sev = _clean_dd_text(payload.get("entityCheckSeverity")).upper()
    entity_check_summary = _clean_dd_text(payload.get("entityCheckSummary"))
    pulled = _dd_today_label()
    registry_status = "Active · Good standing" if sos_good else "Requires review"

    def id_key(value: str) -> str:
        return re.sub(r"[^a-z0-9]", "", value.lower())

    entity_mismatch = bool(
        app_entity
        and entity
        and entity != "—"
        and id_key(app_entity) != id_key(entity)
    )
    name_match = (
        "bad"
        if (not borrower and not _clean_dd_text(payload.get("sosCompany"))) or name_mismatch
        else "ok"
    )
    entity_match = "bad" if entity == "—" or not entity or entity_mismatch else "ok"
    type_match = "bad" if not entity_type or entity_type == "—" else "ok"
    filing_match = "ok" if sos_good else "bad"
    if not app_address and (not _clean_dd_text(payload.get("sosAddress")) or sos_address == "—"):
        address_match = "bad"
    elif address_mismatch or sos_address == "—":
        address_match = "bad"
    else:
        address_match = "ok"
    if not app_control or app_control == "—" or not _clean_dd_text(payload.get("sosOfficer")):
        officer_match = "bad"
    elif control_mismatch:
        officer_match = "bad"
    else:
        officer_match = "ok"

    sos_verdict = "Registry fields align with the application"
    sos_compare = (
        "Secretary of State legal name, entity number, and principal address were "
        "compared to the credit file"
    )
    if entity_check_sev == "CRITICAL":
        sos_verdict = "Conflict · registry or CDD control issue flagged"
        sos_compare = entity_check_summary or sos_verdict
    elif name_mismatch:
        sos_verdict = "Legal name differs from the application"
        sos_compare = f'Application shows "{borrower}"; registry shows "{sos_company}"'
    elif address_mismatch:
        sos_verdict = "Principal address differs from the application"
        sos_compare = "Registry principal address does not match the loan application"
    elif control_mismatch:
        sos_verdict = "Control person differs from the application"
        sos_compare = (
            f"Registry lists {sos_officer}; application control person is {app_control}"
        )
    elif not _clean_dd_text(payload.get("sosCompany")) or entity == "—":
        sos_verdict = "Registry record not fully parsed"
        sos_compare = "Could not confirm all registry fields from the uploaded state filing"

    sos_card = _finalize_dd_card(
        {
            "area": "Business registration",
            "source": "California Secretary of State",
            "pulledAt": pulled,
            "verdict": sos_verdict,
            "packetCompare": sos_compare,
            "results": [
                _dd_row("Legal name", sos_company, name_match),
                _dd_row("Entity number", entity, entity_match),
                _dd_row("Entity type", entity_type, type_match),
                _dd_row("Filing status", registry_status, filing_match),
                _dd_row("Principal address", sos_address, address_match),
                _dd_row("Chief executive", sos_officer, officer_match),
            ],
        }
    )
    address_seed_value = (
        "Not confirmed against application"
        if sos_address == "—"
        else f"{sos_address} · suite/unit variance vs application"
    )
    sos_card = _ensure_dd_concerns(
        sos_card,
        [
            {
                "label": "Filing status",
                "value": "Active · Statement of Information overdue",
                "verdict": "Statement of Information appears overdue on the registry",
                "compare": (
                    "Registry shows good standing, but the latest Statement of "
                    "Information filing is past due"
                ),
            },
            {
                "label": "Principal address",
                "value": address_seed_value,
                "verdict": "Principal address needs confirmation against the application",
                "compare": (
                    "Registry principal address does not fully match the address "
                    "stated on the loan application"
                ),
            },
        ],
        2,
    )

    if _is_contractor_borrower(naics, entity_type):
        license_number = _derive_cslb_license_number(entity)
        classification = _cslb_classification(naics)
        license_expiry = _derive_license_expiry(entity)
        expired = _license_expired(license_expiry)
        if not expired:
            license_expiry = "Mar 2026"
            expired = True
        license_verdict = "Active · bond and workers' comp current (illustrative)"
        license_compare = (
            f"CSLB license {license_number} is active for {classification.lower()} work"
        )
        if control_mismatch:
            license_verdict = "Qualifying individual differs from application control person"
            license_compare = (
                f"License qualifier {sos_officer} does not match application "
                f"control person {app_control}"
            )
        elif name_mismatch:
            license_verdict = "License issued under registry legal name"
            license_compare = (
                f'License is issued to "{sos_company}" while the application '
                f'names "{borrower}"'
            )
        elif expired:
            license_verdict = "License expiration requires review"
            license_compare = f"CSLB shows expiration of {license_expiry}"
        license_card = _finalize_dd_card(
            {
                "area": "Contractor license",
                "source": "California CSLB",
                "pulledAt": pulled,
                "verdict": license_verdict,
                "packetCompare": license_compare,
                "results": [
                    _dd_row("License number", license_number, "ok"),
                    _dd_row("Licensee", sos_company, name_match),
                    _dd_row("Qualifying individual", sos_officer, officer_match),
                    _dd_row("Classification", classification, "ok"),
                    _dd_row("Expires", license_expiry, "bad" if expired else "ok"),
                    _dd_row(
                        "Bond / workers' comp",
                        "Current · no open disciplinary actions",
                        "ok",
                    ),
                ],
            }
        )
        license_card = _ensure_dd_concerns(
            license_card,
            [
                {
                    "label": "Expires",
                    "value": license_expiry,
                    "verdict": "License expiration requires review",
                    "compare": f"CSLB shows expiration of {license_expiry}",
                },
                {
                    "label": "Bond / workers' comp",
                    "value": "Workers' comp lapse on file · reinstated",
                    "verdict": "Workers' compensation history needs review",
                    "compare": (
                        "CSLB shows a prior workers' compensation lapse that was "
                        "later reinstated"
                    ),
                },
            ],
            2,
        )
    else:
        license_card = _finalize_dd_card(
            {
                "area": "Contractor license",
                "source": "California CSLB",
                "pulledAt": pulled,
                "status": "na",
                "verdict": "Not applicable",
                "packetCompare": "Borrower vertical does not require a contractor license",
                "results": [
                    _dd_row(
                        "Applicability",
                        "Not required for this NAICS / entity type",
                        "ok",
                    )
                ],
            }
        )

    credit_band = "Satisfactory"
    if entity_check_sev in {"HIGH", "CRITICAL"}:
        credit_band = "Fair"
    elif debt_rise:
        credit_band = "Satisfactory"

    credit_card = _finalize_dd_card(
        {
            "area": "Business credit",
            "source": "D&B · Experian · Equifax",
            "pulledAt": pulled,
            "verdict": f"{credit_band} · trade payment needs review",
            "packetCompare": "Bureau trade lines show recent slow-pay experience",
            "results": [
                _dd_row("Overall band", credit_band, "ok"),
                _dd_row("Collections", "0 open", "ok"),
                _dd_row("Liens / judgments", "1 released tax lien (2024)", "ok"),
                _dd_row("Bankruptcies", "None in 7 years", "ok"),
                _dd_row("Trade payment", "2 accounts 30+ days past due", "bad"),
            ],
        }
    )
    credit_card = _ensure_dd_concerns(
        credit_card,
        [
            {
                "label": "Trade payment",
                "value": "2 accounts 30+ days past due",
                "verdict": "Trade payment experience is mixed",
                "compare": "Bureau trade lines show recent slow-pay experience",
            },
        ],
        1,
    )

    return {
        "borrower": borrower or sos_company,
        "entity": entity,
        "prototypeNote": (
            "Demo simulation: California Secretary of State fields are compared to the uploaded "
            "state filing. CSLB and bureau responses are illustrative but keyed to this credit file's "
            "entity number, NAICS, and identity findings."
        ),
        "sources": [sos_card, license_card, credit_card],
    }


def credit_analysis_cache_key(prompt_version: str, system: str, user: str) -> str:
    payload = f"{prompt_version}\n{system}\n{user}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def parse_credit_analysis_json(text: str) -> Dict[str, object]:
    cleaned = re.sub(r"```json|```", "", text, flags=re.IGNORECASE).strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise RuntimeError("anthropic_response_truncated") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("anthropic_response_not_object")
    return parsed


def call_anthropic_messages(
    api_key: str,
    model: str,
    system: str,
    user: str,
    *,
    max_tokens: Optional[int] = None,
) -> Dict[str, object]:
    token_limit = max_tokens if max_tokens is not None else env_int(
        "ANTHROPIC_MAX_TOKENS", CREDIT_ANALYSIS_MAX_TOKENS
    )
    body = json.dumps(
        {
            "model": model,
            "max_tokens": token_limit,
            "temperature": 0,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        ANTHROPIC_MESSAGES_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_API_VERSION,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(
            request, timeout=CREDIT_ANALYSIS_TIMEOUT_SECONDS
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        raise RuntimeError(f"anthropic_http_{exc.code}:{detail}") from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", None)
        if isinstance(reason, (TimeoutError, socket.timeout)):
            raise RuntimeError("anthropic_timeout") from exc
        raise RuntimeError("anthropic_unreachable") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("anthropic_invalid_response") from exc

    blocks = payload.get("content") or []
    text = "".join(
        block.get("text", "")
        for block in blocks
        if isinstance(block, dict) and block.get("type") == "text"
    ).strip()
    if not text:
        raise RuntimeError("anthropic_empty_response")
    stop_reason = payload.get("stop_reason")
    if stop_reason == "max_tokens":
        raise RuntimeError("anthropic_response_truncated")
    return parse_credit_analysis_json(text)


def credit_analysis_user_message(code: str) -> str:
    messages = {
        "anthropic_api_key_missing": (
            "The credit review assistant is not set up yet. Your documents are fully "
            "parsed — you can still review all findings manually."
        ),
        "authentication_required": (
            "Your session has expired. Sign in again to generate an analysis."
        ),
        "request_rejected": (
            "This request could not be completed. Refresh the page and try again."
        ),
        "invalid_request": (
            "We couldn't start the analysis. Refresh the page and open the "
            "analysis workspace again."
        ),
        "credit_analysis_packet_too_large": (
            "This credit file is too large for automatic analysis. You can still "
            "review all parsed findings in the workspace."
        ),
        "anthropic_timeout": (
            "The analysis took too long and was stopped. Please wait a moment "
            "and try again — the first run can take several minutes."
        ),
        "anthropic_response_truncated": (
            "The analysis did not finish completely. Please try again."
        ),
        "anthropic_request_failed": (
            "The analysis service is temporarily unavailable. Please try again in a "
            "few minutes."
        ),
        "anthropic_unreachable": (
            "We couldn't connect to the analysis service. Check your internet "
            "connection and try again."
        ),
        "anthropic_invalid_response": (
            "The analysis did not come back in a usable form. Please try again."
        ),
        "anthropic_empty_response": (
            "The analysis service returned an empty response. Please try again."
        ),
    }
    return messages.get(
        code,
        "The credit review assistant couldn't complete a summary. Your parsed "
        "findings are still available in the workspace.",
    )


def run_credit_analysis(
    api_key: str,
    model: str,
    prompt_version: str,
    system: str,
    user: str,
    cache: Dict[str, Dict[str, object]],
) -> Tuple[Dict[str, object], bool]:
    if not api_key:
        raise RuntimeError("anthropic_api_key_missing")
    if not isinstance(system, str) or not isinstance(user, str):
        raise ValueError("invalid_credit_analysis_payload")
    if not system.strip() or not user.strip():
        raise ValueError("invalid_credit_analysis_payload")
    if len(user) > CREDIT_ANALYSIS_MAX_USER_CHARS:
        raise ValueError("credit_analysis_packet_too_large")

    cache_key = credit_analysis_cache_key(prompt_version, system, user)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached, True

    judgment = call_anthropic_messages(api_key, model, system, user)
    cache[cache_key] = judgment
    return judgment, False


@dataclass(frozen=True)
class AppConfig:
    root: Path
    public_origin: Optional[str]
    secure_cookie: bool
    anthropic_api_key: str
    anthropic_model: str
    fast_analysis: bool

    @property
    def cookie_name(self) -> str:
        return "__Host-eridant_session" if self.secure_cookie else "eridant_session"


class EridantHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, store: AuthStore, config: AppConfig):
        self.auth_store = store
        self.app_config = config
        self.credit_analysis_cache: Dict[str, Dict[str, object]] = {}
        super().__init__(address, EridantHandler)


class EridantHandler(BaseHTTPRequestHandler):
    server_version = "EridantAuth/1.0"
    sys_version = ""

    @property
    def store(self) -> AuthStore:
        return self.server.auth_store

    @property
    def config(self) -> AppConfig:
        return self.server.app_config

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write(
            "%s - - [%s] %s\n"
            % (self.client_address[0], self.log_date_time_string(), fmt % args)
        )

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("Pragma", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Vary", "Sec-Fetch-Site, Origin")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; base-uri 'none'; frame-ancestors 'none'; "
            "object-src 'none'; form-action 'self'; img-src 'self' data: blob:; "
            "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
            "connect-src 'self' https://api.anthropic.com https://api.openai.com "
            "https://api.groq.com https://openrouter.ai http://localhost:* "
            "http://127.0.0.1:*",
        )
        if self.config.secure_cookie:
            self.send_header("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        super().end_headers()

    def _json(self, status: int, payload: Dict[str, object]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            return

    def _empty(self, status: int) -> None:
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _redirect(self, location: str) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _serve_demo_packet(self, packet_id: str, filename: str) -> None:
        allowed = DEMO_PACKETS.get(packet_id)
        if not allowed or filename not in allowed:
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        if any(part in (filename, packet_id) for part in ("..", "/", "\\")):
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        path = self.config.root / "test_packets" / packet_id / filename
        try:
            body = path.read_bytes()
        except OSError:
            self._json(HTTPStatus.NOT_FOUND, {"error": "demo_packet_unavailable"})
            return
        content_type = DEMO_PACKET_CONTENT_TYPES[Path(filename).suffix.lower()]
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "private, max-age=300")
        self.end_headers()
        self.wfile.write(body)

    def _serve_html(self, filename: str) -> None:
        path = self.config.root / filename
        try:
            body = path.read_bytes()
        except OSError:
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "page_unavailable"})
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_asset(self, filename: str, content_type: str) -> None:
        path = self.config.root / filename
        try:
            body = path.read_bytes()
        except OSError:
            self._json(HTTPStatus.NOT_FOUND, {"error": "asset_unavailable"})
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self, max_bytes: int = 8_192) -> Optional[Dict[str, object]]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return None
        if length <= 0 or length > max_bytes:
            return None
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def _session_token(self) -> str:
        raw = self.headers.get("Cookie", "")
        try:
            cookie = SimpleCookie(raw)
            morsel = cookie.get(self.config.cookie_name)
            return morsel.value if morsel else ""
        except Exception:
            return ""

    def _session(self) -> Optional[Dict[str, object]]:
        return self.store.get_session(self._session_token())

    def _digest_eq(self, left: str, right: str) -> bool:
        if not left or not right or len(left) != len(right):
            return False
        return hmac.compare_digest(left, right)

    def _header_host(self, value: str) -> str:
        host = value.split(",")[0].strip()
        if not host or any(ch in host for ch in "\r\n/\\"):
            return ""
        return host

    def _allowed_origins(self) -> list[str]:
        origins: list[str] = []
        if self.config.public_origin:
            origins.append(self.config.public_origin.rstrip("/"))
        proto = self.headers.get("X-Forwarded-Proto", "").split(",")[0].strip().lower()
        if proto not in {"http", "https"}:
            proto = "https" if self.config.secure_cookie else "http"
        hosts = [
            self._header_host(self.headers.get("X-Forwarded-Host", "")),
            self._header_host(self.headers.get("Host", "")),
        ]
        for host in hosts:
            if not host:
                continue
            origins.append(f"{proto}://{host}")
            origins.append(f"https://{host}")
            origins.append(f"http://{host}")
        unique: list[str] = []
        for origin in origins:
            origin = origin.rstrip("/")
            if origin and origin not in unique:
                unique.append(origin)
        return unique

    def _same_origin_request(self) -> bool:
        if self.headers.get("Sec-Fetch-Site", "").lower() == "cross-site":
            return False
        source = self.headers.get("Origin", "").rstrip("/")
        if not source:
            referer = self.headers.get("Referer", "")
            if referer:
                parts = urlsplit(referer)
                if parts.scheme and parts.netloc:
                    source = f"{parts.scheme}://{parts.netloc}"
        allowed = self._allowed_origins()
        if source:
            return any(self._digest_eq(source, target) for target in allowed)
        return self.headers.get("Sec-Fetch-Site", "").lower() in {"same-origin", "none"}

    def _set_session_cookie(self, token: str) -> None:
        parts = [
            f"{self.config.cookie_name}={token}",
            "Path=/",
            f"Max-Age={SESSION_ABSOLUTE_SECONDS}",
            "HttpOnly",
            "SameSite=Strict",
        ]
        if self.config.secure_cookie:
            parts.append("Secure")
        self.send_header("Set-Cookie", "; ".join(parts))

    def _clear_session_cookie(self) -> None:
        parts = [
            f"{self.config.cookie_name}=",
            "Path=/",
            "Max-Age=0",
            f"Expires={formatdate(0, usegmt=True)}",
            "HttpOnly",
            "SameSite=Strict",
        ]
        if self.config.secure_cookie:
            parts.append("Secure")
        self.send_header("Set-Cookie", "; ".join(parts))

    def _issue_session(self, user: Dict[str, object]) -> None:
        session = self.store.create_session(user["id"])
        body = json.dumps({"user": user}, separators=(",", ":")).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._set_session_cookie(session["token"])
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == "/healthz":
            self._json(HTTPStatus.OK, {"status": "ok"})
            return
        if path == "/login":
            if self._session():
                self._redirect("/")
            else:
                self._serve_html("login.html")
            return
        if path == "/signup":
            if self._session():
                self._redirect("/")
            else:
                self._serve_html("signup.html")
            return
        if path == "/api/auth/me":
            session = self._session()
            if not session:
                self._json(HTTPStatus.UNAUTHORIZED, {"error": "authentication_required"})
                return
            self._json(
                HTTPStatus.OK,
                {
                    "user": session["user"],
                    "csrfToken": session["csrfToken"],
                    "expiresAt": session["expiresAt"],
                    "analysisMode": "fast" if self.config.fast_analysis else "full",
                    "anthropicModel": self.config.anthropic_model,
                },
            )
            return
        if path in VENDOR_ASSETS:
            if not self._session():
                self._redirect("/login")
                return
            filename, content_type = VENDOR_ASSETS[path]
            self._serve_asset(filename, content_type)
            return
        if path.startswith("/demo/packet/"):
            if not self._session():
                self._json(HTTPStatus.UNAUTHORIZED, {"error": "authentication_required"})
                return
            parts = [part for part in path.split("/") if part]
            # demo / packet / <packet_id> / <filename>
            if len(parts) != 4:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                return
            self._serve_demo_packet(parts[2], parts[3])
            return
        if path.startswith("/api/cre/"):
            self._cre_get(path)
            return
        if path in ("/", "/eridant-demo.html", "/erident-demo.html"):
            if not self._session():
                self._redirect("/login")
                return
            self._serve_html("eridant-demo new.html")
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        if path == "/api/auth/login":
            self._login()
            return
        if path == "/api/auth/signup-invite":
            self._signup_invite()
            return
        if path == "/api/auth/signup":
            self._signup()
            return
        if path == "/api/auth/logout":
            self._logout()
            return
        if path == "/api/render-document":
            self._render_document()
            return
        if path == "/api/external/due-diligence":
            self._external_due_diligence()
            return
        if path == "/api/credit-analysis":
            self._credit_analysis()
            return
        if path.startswith("/api/cre/"):
            self._cre_post(path)
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    # ---------------- CRE overrides and audit trail ----------------
    def _cre_meta(self, session: Dict[str, object], payload: Dict[str, object]) -> Dict[str, str]:
        ctx = payload.get("context") if isinstance(payload.get("context"), dict) else {}
        context = {
            "ruleVersion": _cre_text(ctx.get("ruleVersion"), 64),
            "promptVersion": _cre_text(ctx.get("promptVersion"), 96),
            "model": self.config.anthropic_model,
        }
        return {
            "context": json.dumps(context, sort_keys=True),
            # a reference to the login session, never the session token itself
            "session_ref": str(session.get("tokenHash", ""))[:12],
            "client_ip": str(self.client_address[0]) if self.client_address else "",
        }

    def _cre_user_session(self, write: bool) -> Optional[Dict[str, object]]:
        if write and not self._same_origin_request():
            self._json(HTTPStatus.FORBIDDEN, {"error": "request_rejected"})
            return None
        session = self._session()
        if not session:
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "authentication_required"})
            return None
        if write:
            supplied = self.headers.get("X-CSRF-Token", "")
            if not supplied or not hmac.compare_digest(supplied, session["csrfToken"]):
                self._json(HTTPStatus.FORBIDDEN, {"error": "request_rejected"})
                return None
        return session

    def _cre_get(self, path: str) -> None:
        session = self._cre_user_session(write=False)
        if not session:
            return
        parts = [p for p in path.split("/") if p]  # api / cre / deals / <id> / overrides|audit
        if len(parts) != 5 or parts[2] != "deals" or not CRE_DEAL_ID_RE.match(parts[3]):
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        deal_id, what = parts[3], parts[4]
        store = CreAuditStore(self.store)
        if what == "overrides":
            self._json(HTTPStatus.OK, {
                "overrides": store.active_overrides(deal_id),
                "history": store.override_history(deal_id),
                "canUndo": session["user"]["role"] in CRE_UNDO_ROLES,
            })
            return
        if what != "audit":
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        entries = store.audit(deal_id)
        query = parse_qs(urlsplit(self.path).query)
        fmt = (query.get("format") or [""])[0]
        # optional filters, so an export matches what the user filtered on screen
        f_role = (query.get("role") or [""])[0]
        f_user = (query.get("user") or [""])[0].lower()
        f_item = (query.get("item") or [""])[0]
        filtered = bool(f_role or f_user or f_item)
        if filtered:
            entries = [
                e for e in entries
                if (not f_role or e["role"] == f_role)
                and (not f_user or e["email"].lower() == f_user)
                and (not f_item or e["itemId"] == f_item)
            ]
        if fmt != "csv":
            self._json(HTTPStatus.OK, {"entries": entries})
            return
        buf = io_StringIO()
        writer = csv.writer(buf)
        writer.writerow([
            "User ID", "Login", "Name", "Role", "Time (UTC)", "Action", "Item", "Before", "After",
            "Reason", "Note", "Evidence", "Deal", "Rule version", "Prompt version",
            "Model", "Session", "IP", "Entry hash", "Previous hash",
        ])
        for e in entries:
            writer.writerow([_cre_csv_cell(v) for v in [
                e["userId"], e["email"], e["user"], CRE_ROLE_LABELS.get(e["role"], e["role"]),
                time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(e["ts"])),
                CRE_EVENT_LABELS.get(e["event"], e["event"]), e["itemTitle"] or e["itemId"],
                json.dumps(e["before"]), json.dumps(e["after"]), e["reason"], e["note"],
                e["evidence"], e["deal"], e["context"].get("ruleVersion", ""),
                e["context"].get("promptVersion", ""), e["context"].get("model", ""),
                e["sessionRef"], e["clientIp"], e["entryHash"], e["prevHash"],
            ]])
        body = buf.getvalue().encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        suffix = "-filtered" if filtered else ""
        self.send_header("Content-Disposition", f'attachment; filename="cre-audit-{deal_id[:12]}{suffix}.csv"')
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _cre_post(self, path: str) -> None:
        session = self._cre_user_session(write=True)
        if not session:
            return
        payload = self._read_json(16_384)
        if payload is None:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid_request"})
            return
        parts = [p for p in path.split("/") if p]
        store = CreAuditStore(self.store)
        user = session["user"]
        meta = self._cre_meta(session, payload)
        deal_label = _cre_text(payload.get("dealLabel"), 160)
        # api / cre / overrides / <id> / revert
        if len(parts) == 5 and parts[2] == "overrides" and parts[4] == "revert" and parts[3].isdigit():
            if user["role"] not in CRE_UNDO_ROLES:
                self._json(HTTPStatus.FORBIDDEN, {"error": "supervisor_required"})
                return
            note = _cre_text(payload.get("note"), 2000)
            if not note:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "note_required"})
                return
            try:
                result = store.revert_override(int(parts[3]), note, deal_label, user, meta)
            except LookupError:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                return
            self._json(HTTPStatus.OK, {"override": result})
            return
        if len(parts) != 5 or parts[2] != "deals" or not CRE_DEAL_ID_RE.match(parts[3]):
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        deal_id, what = parts[3], parts[4]
        item_id = _cre_text(payload.get("itemId"), 64)
        item_title = _cre_text(payload.get("itemTitle"), 240)
        if not CRE_ITEM_ID_RE.match(item_id) or not item_title:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid_item"})
            return
        if what == "audit":
            event = _cre_text(payload.get("event"), 40)
            if event not in CRE_AUDIT_EVENTS:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid_event"})
                return
            before = payload.get("before") if isinstance(payload.get("before"), dict) else {}
            after = payload.get("after") if isinstance(payload.get("after"), dict) else {}
            store.log_event(deal_id, {
                "event": event, "item_id": item_id, "item_title": item_title,
                "before": {k: _cre_text(v, 120) for k, v in list(before.items())[:8]},
                "after": {k: _cre_text(v, 120) for k, v in list(after.items())[:8]},
                "note": _cre_text(payload.get("note"), 500), "deal_label": deal_label,
            }, user, meta)
            self._json(HTTPStatus.OK, {"logged": True})
            return
        if what != "overrides":
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        action = _cre_text(payload.get("action"), 32)
        reason = _cre_text(payload.get("reasonCode"), 32)
        kind = _cre_text(payload.get("itemKind"), 16)
        from_sev = _cre_text(payload.get("fromSeverity"), 16).upper()
        to_sev = _cre_text(payload.get("toSeverity"), 16).upper()
        note = _cre_text(payload.get("note"), 2000)
        if (
            action not in CRE_OVERRIDE_ACTIONS or reason not in CRE_REASON_CODES
            or kind not in CRE_ITEM_KINDS or from_sev not in CRE_SEVERITIES
            or to_sev not in CRE_SEVERITIES
        ):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid_override"})
            return
        if not note:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "note_required"})
            return
        if action == "change_severity" and (not to_sev or to_sev == from_sev):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "severity_required"})
            return
        try:
            result = store.create_override(deal_id, {
                "item_id": item_id, "item_kind": kind, "item_title": item_title,
                "action": action, "from_severity": from_sev,
                "to_severity": to_sev if action == "change_severity" else "",
                "from_value": _cre_text(payload.get("fromValue"), 120),
                "reason_code": reason, "note": note,
                "evidence": _cre_text(payload.get("evidence"), 200), "deal_label": deal_label,
            }, user, meta)
        except ValueError:
            self._json(HTTPStatus.CONFLICT, {"error": "already_overridden"})
            return
        self._json(HTTPStatus.OK, {"override": result})

    def _render_document(self) -> None:
        if not self._same_origin_request():
            self._json(HTTPStatus.FORBIDDEN, {"error": "request_rejected"})
            return
        token = self._session_token()
        session = self.store.get_session(token)
        if not session:
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "authentication_required"})
            return
        supplied = self.headers.get("X-CSRF-Token", "")
        if not supplied or not hmac.compare_digest(supplied, session["csrfToken"]):
            self._json(HTTPStatus.FORBIDDEN, {"error": "request_rejected"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > DOCUMENT_RENDER_MAX_BYTES:
            self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "invalid_document_size"})
            return
        data = self.rfile.read(length)
        try:
            pdf = convert_document_to_pdf(data)
        except ValueError:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "unsafe_or_invalid_document"})
            return
        except subprocess.TimeoutExpired:
            self._json(HTTPStatus.GATEWAY_TIMEOUT, {"error": "pdf_conversion_timed_out"})
            return
        except RuntimeError as exc:
            status = (
                HTTPStatus.SERVICE_UNAVAILABLE
                if str(exc) == "pdf_converter_unavailable"
                else HTTPStatus.UNPROCESSABLE_ENTITY
            )
            self._json(status, {"error": str(exc)})
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Disposition", 'inline; filename="source-preview.pdf"')
        self.send_header("Content-Length", str(len(pdf)))
        self.end_headers()
        self.wfile.write(pdf)

    def _external_due_diligence(self) -> None:
        if not self._same_origin_request():
            self._json(HTTPStatus.FORBIDDEN, {"error": "request_rejected"})
            return
        session = self._session()
        if not session:
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "authentication_required"})
            return
        supplied = self.headers.get("X-CSRF-Token", "")
        if not supplied or not hmac.compare_digest(supplied, session["csrfToken"]):
            self._json(HTTPStatus.FORBIDDEN, {"error": "request_rejected"})
            return
        payload = self._read_json()
        if not payload:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid_request"})
            return
        self._json(HTTPStatus.OK, build_external_due_diligence(payload))

    def _credit_analysis(self) -> None:
        if not self._same_origin_request():
            self._json(
                HTTPStatus.FORBIDDEN,
                {
                    "error": "request_rejected",
                    "message": credit_analysis_user_message("request_rejected"),
                },
            )
            return
        session = self._session()
        if not session:
            self._json(
                HTTPStatus.UNAUTHORIZED,
                {
                    "error": "authentication_required",
                    "message": credit_analysis_user_message("authentication_required"),
                },
            )
            return
        supplied = self.headers.get("X-CSRF-Token", "")
        if not supplied or not hmac.compare_digest(supplied, session["csrfToken"]):
            self._json(
                HTTPStatus.FORBIDDEN,
                {
                    "error": "request_rejected",
                    "message": credit_analysis_user_message("request_rejected"),
                },
            )
            return
        payload = self._read_json(CREDIT_ANALYSIS_MAX_BODY_BYTES)
        if not payload:
            self._json(
                HTTPStatus.BAD_REQUEST,
                {
                    "error": "invalid_request",
                    "message": credit_analysis_user_message("invalid_request"),
                },
            )
            return
        prompt_version = payload.get("promptVersion")
        system = payload.get("system")
        user = payload.get("user")
        if not isinstance(prompt_version, str) or not prompt_version.strip():
            self._json(
                HTTPStatus.BAD_REQUEST,
                {
                    "error": "invalid_request",
                    "message": credit_analysis_user_message("invalid_request"),
                },
            )
            return
        self.log_message(
            "credit-analysis start (model=%s, mode=%s, prompt=%s, user_chars=%d)",
            self.config.anthropic_model,
            "fast" if self.config.fast_analysis else "full",
            prompt_version.strip(),
            len(user if isinstance(user, str) else ""),
        )
        started = time.time()
        try:
            judgment, cached = run_credit_analysis(
                self.config.anthropic_api_key,
                self.config.anthropic_model,
                prompt_version.strip(),
                system if isinstance(system, str) else "",
                user if isinstance(user, str) else "",
                self.server.credit_analysis_cache,
            )
        except ValueError as exc:
            code = str(exc)
            if code == "credit_analysis_packet_too_large":
                self._json(
                    HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                    {
                        "error": code,
                        "message": credit_analysis_user_message(code),
                    },
                )
                return
            self._json(
                HTTPStatus.BAD_REQUEST,
                {
                    "error": "invalid_request",
                    "message": credit_analysis_user_message("invalid_request"),
                },
            )
            return
        except RuntimeError as exc:
            code = str(exc)
            if code == "anthropic_api_key_missing":
                user_code = code
            elif code == "anthropic_response_truncated":
                user_code = code
            elif code == "anthropic_timeout":
                user_code = code
            elif code.startswith("anthropic_http_"):
                user_code = "anthropic_request_failed"
            elif code in {
                "anthropic_unreachable",
                "anthropic_invalid_response",
                "anthropic_empty_response",
            }:
                user_code = code
            else:
                user_code = "anthropic_request_failed"
            status = HTTPStatus.BAD_GATEWAY
            if user_code == "anthropic_api_key_missing":
                status = HTTPStatus.SERVICE_UNAVAILABLE
            elif user_code == "anthropic_timeout":
                status = HTTPStatus.GATEWAY_TIMEOUT
            self._json(
                status,
                {"error": user_code, "message": credit_analysis_user_message(user_code)},
            )
            return
        elapsed = time.time() - started
        self.log_message(
            "credit-analysis done (cached=%s, elapsed=%.1fs)",
            cached,
            elapsed,
        )
        self._json(
            HTTPStatus.OK,
            {
                "cached": cached,
                "promptVersion": prompt_version.strip(),
                "judgment": judgment,
            },
        )

    def _login(self) -> None:
        if not self._same_origin_request():
            self._json(HTTPStatus.FORBIDDEN, {"error": "request_rejected"})
            return
        payload = self._read_json()
        if not payload:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid_request"})
            return
        email = payload.get("email")
        password = payload.get("password")
        if not isinstance(email, str) or not isinstance(password, str):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid_request"})
            return
        result = self.store.authenticate(email, password, self.client_address[0])
        if result["status"] == "blocked":
            self._json(HTTPStatus.TOO_MANY_REQUESTS, {"error": "try_again_later"})
            return
        if result["status"] != "ok":
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "invalid_credentials"})
            return
        self._issue_session(result["user"])

    def _signup_invite(self) -> None:
        if not self._same_origin_request():
            self._json(HTTPStatus.FORBIDDEN, {"error": "request_rejected"})
            return
        payload = self._read_json()
        token = payload.get("invite") if payload else None
        if not isinstance(token, str):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid_request"})
            return
        invite = self.store.get_invite(token)
        if not invite:
            self._json(HTTPStatus.NOT_FOUND, {"error": "invalid_invite"})
            return
        self._json(HTTPStatus.OK, {"invite": invite})

    def _signup(self) -> None:
        if not self._same_origin_request():
            self._json(HTTPStatus.FORBIDDEN, {"error": "request_rejected"})
            return
        payload = self._read_json()
        if not payload:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid_request"})
            return
        invite = payload.get("invite")
        email = payload.get("email")
        display_name = payload.get("displayName")
        password = payload.get("password")
        if not all(isinstance(value, str) for value in (invite, email, display_name, password)):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid_request"})
            return
        try:
            result = self.store.register_with_invite(invite, email, display_name, password)
        except ValueError:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid_account_details"})
            return
        if result["status"] == "invalid_invite":
            self._json(HTTPStatus.FORBIDDEN, {"error": "invalid_invite"})
            return
        if result["status"] == "existing_user":
            self._json(HTTPStatus.CONFLICT, {"error": "account_exists"})
            return
        self._issue_session(result["user"])

    def _logout(self) -> None:
        if not self._same_origin_request():
            self._json(HTTPStatus.FORBIDDEN, {"error": "request_rejected"})
            return
        token = self._session_token()
        session = self.store.get_session(token)
        if not session:
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "authentication_required"})
            return
        supplied = self.headers.get("X-CSRF-Token", "")
        if not supplied or not hmac.compare_digest(supplied, session["csrfToken"]):
            self._json(HTTPStatus.FORBIDDEN, {"error": "request_rejected"})
            return
        self.store.revoke_session(token)
        self.send_response(HTTPStatus.NO_CONTENT)
        self._clear_session_cookie()
        self.send_header("Content-Length", "0")
        self.end_headers()


def prompt_for_password() -> str:
    first = getpass.getpass("Password: ")
    second = getpass.getpass("Confirm password: ")
    if not hmac.compare_digest(first.encode("utf-8"), second.encode("utf-8")):
        raise ValueError("Passwords do not match.")
    return first


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Eridant authenticated application server")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="run the authenticated web server")
    serve.add_argument(
        "--host",
        default=os.environ.get("HOST") or ("0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"),
    )
    serve.add_argument("--port", default=int(os.environ.get("PORT", "8000")), type=int)
    serve.add_argument("--db", default=DEFAULT_DB, type=Path)
    serve.add_argument(
        "--public-origin",
        default=os.environ.get("SIGMA_PUBLIC_ORIGIN") or os.environ.get("RENDER_EXTERNAL_URL"),
    )
    serve.add_argument(
        "--secure-cookie",
        action="store_true",
        default=os.environ.get("SIGMA_SECURE_COOKIE", "").lower() in {"1", "true", "yes"},
        help="require HTTPS cookies; use behind an HTTPS reverse proxy",
    )

    create = sub.add_parser("create-user", help="provision a user without storing plaintext credentials")
    create.add_argument("--db", default=DEFAULT_DB, type=Path)
    create.add_argument("--email", required=True)
    create.add_argument("--name", required=True)
    create.add_argument("--role", choices=sorted(ALLOWED_ROLES), default="analyst")

    reset = sub.add_parser("reset-password", help="set a new password for an existing user")
    reset.add_argument("--db", default=DEFAULT_DB, type=Path)
    reset.add_argument("--email", required=True)

    invite = sub.add_parser("create-invite", help="create a one-time sign-up invitation")
    invite.add_argument("--db", default=DEFAULT_DB, type=Path)
    invite.add_argument("--email", required=True)
    invite.add_argument("--role", choices=sorted(ALLOWED_ROLES), default="analyst")
    invite.add_argument("--hours", type=int, default=24)
    invite.add_argument(
        "--origin",
        default=os.environ.get("SIGMA_PUBLIC_ORIGIN", "http://127.0.0.1:8000"),
        help="public application origin used in the generated sign-up link",
    )
    return parser


def main() -> int:
    load_dotenv()
    args = build_parser().parse_args()
    store = AuthStore(args.db)
    if args.command == "create-user":
        try:
            password = prompt_for_password()
            store.create_user(args.email, args.name, password, args.role)
        except ValueError as exc:
            print(f"User not created: {exc}", file=sys.stderr)
            return 2
        print(f"Created {args.role} user {normalize_email(args.email)}")
        return 0

    if args.command == "reset-password":
        try:
            password = prompt_for_password()
            store.reset_password(args.email, password)
        except ValueError as exc:
            print(f"Password not changed: {exc}", file=sys.stderr)
            return 2
        print(f"Password updated for {normalize_email(args.email)}")
        return 0

    if args.command == "create-invite":
        try:
            token = store.create_invite(args.email, args.role, args.hours)
        except ValueError as exc:
            print(f"Invite not created: {exc}", file=sys.stderr)
            return 2
        origin = args.origin.rstrip("/")
        print(f"Created one-time {args.role} invitation for {normalize_email(args.email)}")
        print(f"{origin}/signup#invite={token}")
        return 0

    bootstrap_email = env_plain("SIGMA_BOOTSTRAP_EMAIL")
    bootstrap_password = env_plain("SIGMA_BOOTSTRAP_PASSWORD")
    bootstrap_name = env_plain("SIGMA_BOOTSTRAP_NAME") or "Analyst"
    bootstrap_role = env_plain("SIGMA_BOOTSTRAP_ROLE") or "analyst"
    if bootstrap_email and bootstrap_password:
        try:
            action = store.upsert_user(
                bootstrap_email, bootstrap_name, bootstrap_password, bootstrap_role
            )
            print(
                f"Bootstrap user {action}: {normalize_email(bootstrap_email)}"
            )
        except ValueError as exc:
            print(f"Bootstrap user not created: {exc}", file=sys.stderr)
            return 2
    # optional second account so a hosted demo has both an analyst and a supervisor
    sup_email = env_plain("SIGMA_BOOTSTRAP_SUPERVISOR_EMAIL")
    sup_password = env_plain("SIGMA_BOOTSTRAP_SUPERVISOR_PASSWORD")
    if sup_email and sup_password:
        try:
            action = store.upsert_user(
                sup_email, env_plain("SIGMA_BOOTSTRAP_SUPERVISOR_NAME") or "Credit Supervisor",
                sup_password, "supervisor",
            )
            print(f"Bootstrap supervisor {action}: {normalize_email(sup_email)}")
        except ValueError as exc:
            print(f"Bootstrap supervisor not created: {exc}", file=sys.stderr)
            return 2
    if store.user_count() == 0:
        print(
            "No active users exist. Run auth_server.py create-user before starting the server,"
            " or set SIGMA_BOOTSTRAP_EMAIL and SIGMA_BOOTSTRAP_PASSWORD.",
            file=sys.stderr,
        )
        return 2
    if args.secure_cookie and not args.public_origin:
        print("--secure-cookie requires --public-origin (for example https://eridant.example.com).", file=sys.stderr)
        return 2
    public_origin = args.public_origin.rstrip("/") if args.public_origin else None
    anthropic_api_key = env_plain("ANTHROPIC_API_KEY")
    anthropic_model = env_plain("ANTHROPIC_MODEL") or DEFAULT_ANTHROPIC_MODEL
    fast_analysis = env_bool("ANTHROPIC_FAST_ANALYSIS")
    max_tokens = env_int("ANTHROPIC_MAX_TOKENS", CREDIT_ANALYSIS_MAX_TOKENS)
    config = AppConfig(
        APP_ROOT,
        public_origin,
        args.secure_cookie,
        anthropic_api_key,
        anthropic_model,
        fast_analysis,
    )
    server = EridantHTTPServer((args.host, args.port), store, config)
    scheme = "https" if args.secure_cookie else "http"
    print(f"Eridant listening on {scheme}://{args.host}:{server.server_port}")
    analysis_mode = "fast (extracted fields only)" if fast_analysis else "full documents"
    print(f"Credit analysis: {anthropic_model} · {analysis_mode} · max_tokens={max_tokens}")
    if not args.secure_cookie:
        print("Local HTTP mode: the session cookie is HttpOnly + SameSite=Strict, but not Secure.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
