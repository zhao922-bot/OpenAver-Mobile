"""
Auth-gate state and ticket store — single owner of `access_auth` /
`access_tickets` (TASK-114a-T1 / CD-114a-1/2/3/6/7/13).

Owns PIN storage + format validation, ticket issuance / verification / mass
revocation, the retry-lockout decision core, and an in-process
`AuthSnapshot` cache guarded by a single `threading.Lock` (CD-114a-7).
CD-114a-13-inv: ticket issuance (`attempt_pin`) and auth-settings writes
(`set_auth`) share that same lock so R5 revocation can never race a login —
a ticket minted with a since-changed PIN is either revoked with the rest of
the table, or never minted because the comparison already sees the new PIN.

This module only reads and writes its own two tables. It does not decide
who counts as "local" (`_is_loopback_host()` lives in the web layer, and
`core` must not import `web`) and it does not touch `core/database`'s
`init_db()` — CD-114a-3: the schema is self-ensured here via idempotent
`CREATE TABLE IF NOT EXISTS`, following the same pattern `get_connection()`
already uses for resetting `PRAGMA journal_mode=WAL` on every connection.
"""
from __future__ import annotations

import hmac
import re
import secrets
import sqlite3
import threading
import time
import unicodedata
from dataclasses import dataclass
from typing import Optional

from core.database.connection import get_connection, get_db_path
from core.logger import get_logger

logger = get_logger(__name__)

_ACCESS_AUTH_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS access_auth (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    enabled     INTEGER NOT NULL DEFAULT 0,
    pin         TEXT    NOT NULL DEFAULT '',
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""

_ACCESS_TICKETS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS access_tickets (
    token       TEXT PRIMARY KEY,
    kind        TEXT NOT NULL DEFAULT 'browser',
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""

# Exactly 4 ASCII alphanumerics, case-sensitive. Deliberately NOT `\w`
# (adds `_` and, under `re.UNICODE`, every Unicode letter/digit) and NOT
# `str.isalnum()` (accepts CJK ideographs, Devanagari digits, …): anything
# the owner can type on the desktop but cannot reliably reproduce on the
# phone keypad is a self-inflicted lockout on a page that shows no error.
_PIN_PATTERN = re.compile(r"[0-9A-Za-z]{4}")

_LOCKOUT_THRESHOLD = 5
_BASE_LOCKOUT_SECONDS = 60.0
_LOCKOUT_CAP_SECONDS = 3600.0


@dataclass(frozen=True, slots=True)
class AuthSnapshot:
    """Immutable point-in-time view of auth state + valid tickets.

    `frozen=True` makes "update" mean *build a new instance and swap the
    module-level reference under the lock* — never mutate-in-place — so a
    reader can never observe a half-updated object (no torn `enabled` vs
    `valid_tokens` read).
    """

    enabled: bool
    pin: str
    valid_tokens: frozenset[str]
    agent_token: Optional[str]


# ---------------------------------------------------------------------------
# Process-global state (protected by `_lock`; see module docstring)
# ---------------------------------------------------------------------------
_lock = threading.Lock()
_snapshot: Optional[AuthSnapshot] = None
_consecutive_failures: int = 0
_lockout_started_at: Optional[float] = None


def _now() -> float:
    """Monotonic clock, patchable in tests. NOT `time.time()` (CD-114a
    Opus 補充 E): wall-clock can jump backwards on NTP resync, which would
    let a lockout window vanish or balloon to decades — fail-open direction,
    unacceptable for a lockout mechanism."""
    return time.monotonic()


def _connect() -> sqlite3.Connection:
    return get_connection(get_db_path())


def _new_agent_token() -> str:
    """CD-114b-2's concrete shape. Internal helper shared by `set_auth` and
    `_backfill_agent_ticket_locked` — not a public function, no caller needs
    it directly."""
    return "oav_" + secrets.token_urlsafe(32)


def _canonical_pin(candidate: object) -> Optional[str]:
    """The canonical form to store and to compare, or `None` if `candidate`
    is not a well-formed PIN. Never raises — any non-str input simply
    yields `None` (attempt_pin's `candidate` is typed `object` because T3
    hands it a raw JSON value of unknown type).

    NFKC-folded first. A CJK IME in wide mode emits full-width characters
    ("１２３４" U+FF11…, "ａｂｃｄ" U+FF41…) that look identical to their ASCII
    twins but are different code points. Without folding, a PIN set on the
    desktop with the IME on would never match the same PIN typed on a phone
    with the IME off — and the gate page deliberately shows no error, so the
    owner would get a silent, undiagnosable lockout. Folding is applied on
    both the write path and the verify path, so the two always agree.
    """
    if not isinstance(candidate, str):
        return None
    folded = unicodedata.normalize("NFKC", candidate)
    return folded if _PIN_PATTERN.fullmatch(folded) else None


def _is_valid_pin_format(candidate: object) -> bool:
    """Format-only predicate over `_canonical_pin`."""
    return _canonical_pin(candidate) is not None


def _lockout_duration_seconds(consecutive_failures: int) -> float:
    """Lockout length for the tier `consecutive_failures` falls in: 60s at
    the 5-failure tier, ×4 per further 5-failure tier, capped at 3600s."""
    tier = max(consecutive_failures // _LOCKOUT_THRESHOLD, 1)
    return min(_BASE_LOCKOUT_SECONDS * (4 ** (tier - 1)), _LOCKOUT_CAP_SECONDS)


def _decide_lockout(
    consecutive_failures: int,
    now: float,
    lockout_started_at: Optional[float],
) -> tuple[bool, float]:
    """Pure decision core (spec §9.1 truth table). Does not read or mutate
    any module state — callers own applying the result (Opus 補充 C: who
    clears an expired `lockout_started_at` is `attempt_pin`'s job, not
    this function's)."""
    if lockout_started_at is None:
        return True, 0.0
    duration = _lockout_duration_seconds(consecutive_failures)
    remaining = duration - (now - lockout_started_at)
    if remaining <= 0:
        return True, 0.0
    return False, remaining


def _load_locked() -> AuthSnapshot:
    """Caller already holds `_lock`. The only DB read point: rebuilds the
    cache from `access_auth` + `access_tickets` and swaps it in.

    `agent_token` is derived from the same ticket rows as `valid_tokens`
    (TASK-114b-T1, CD-114b-1) — `ORDER BY rowid ASC` rather than
    `created_at`: SQLite's `CURRENT_TIMESTAMP` only has 1-second
    resolution, which is too coarse to order two tickets minted within
    the same second (e.g. this module's own concurrency barrier test).
    `rowid` is SQLite's implicit monotonically-increasing integer for a
    normal (non-`WITHOUT ROWID`) table and needs no schema change. If more
    than one `kind='agent'` row exists (the CD-114b-1 invariant says this
    should never happen, but this is defensive read code, not a place
    that should crash a hot path on an unexpected shape) the highest-rowid
    (most recently inserted) one wins — consistent with
    `set_auth()`'s "revoke all, insert one" mental model (see its
    `_revoke_all_locked()` → conditional insert sequence).
    """
    global _snapshot
    conn = _connect()
    try:
        row = conn.execute("SELECT enabled, pin FROM access_auth WHERE id = 1").fetchone()
        enabled = bool(row[0]) if row is not None else False
        pin = row[1] if row is not None else ""
        rows = conn.execute(
            "SELECT token, kind FROM access_tickets ORDER BY rowid ASC"
        ).fetchall()
    finally:
        conn.close()
    tokens = frozenset(r[0] for r in rows)
    agent_token = next((r[0] for r in reversed(rows) if r[1] == "agent"), None)
    snap = AuthSnapshot(enabled=enabled, pin=pin, valid_tokens=tokens, agent_token=agent_token)
    _snapshot = snap
    return snap


def _revoke_all_locked(conn: sqlite3.Connection) -> None:
    """Caller already holds `_lock` and owns `conn` (commit/close is the
    caller's job). R5 core action: unconditional, no parameters — this
    signature shape is what keeps `revoke_all()` from ever growing a
    "conditional revoke" option (see module DoD)."""
    conn.execute("DELETE FROM access_tickets")


def _backfill_agent_ticket_locked(conn: sqlite3.Connection) -> None:
    """Caller already holds `_lock` and owns `conn` (commit/close is the
    caller's job — same shape as `_revoke_all_locked`). Upgrade path
    0.13.7 -> 0.13.8: mint one agent ticket if auth is enabled and none
    exists yet. Must never touch browser tickets. Check-then-act, so it
    must run under `_lock` for CD-114b-12's "one lock covers every writer
    in this module" guarantee to hold for backfill too."""
    row = conn.execute("SELECT enabled FROM access_auth WHERE id = 1").fetchone()
    enabled = bool(row[0]) if row is not None else False
    if not enabled:
        return
    has_agent = conn.execute(
        "SELECT 1 FROM access_tickets WHERE kind = 'agent' LIMIT 1"
    ).fetchone()
    if has_agent is not None:
        return
    conn.execute(
        "INSERT INTO access_tickets (token, kind) VALUES (?, 'agent')",
        (_new_agent_token(),),
    )


# ---------------------------------------------------------------------------
# Public interface (9 functions — T2 / T3 / T4 import contract)
# ---------------------------------------------------------------------------


def ensure_schema() -> None:
    """Create both tables (idempotent), backfill an agent ticket for
    upgraded 0.13.7 databases (TASK-114b-T1), and warm the cache. Called
    once from startup wiring (T2).

    Backfill runs inside `with _lock:` and refreshes the cache via the
    private `_load_locked()` — NOT the public `load_snapshot()`, which
    would try to re-acquire this same non-reentrant `threading.Lock()`
    and deadlock (the module's "never call a public function while
    holding `_lock`" rule)."""
    conn = _connect()
    try:
        conn.execute(_ACCESS_AUTH_SCHEMA_SQL)
        conn.execute(_ACCESS_TICKETS_SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()
    with _lock:
        conn = _connect()
        try:
            _backfill_agent_ticket_locked(conn)
            conn.commit()
        finally:
            conn.close()
        _load_locked()


def snapshot() -> Optional[AuthSnapshot]:
    """Current cached snapshot, or `None` if never warmed (cold). Zero I/O,
    no lock — safe to call directly from an async hot path."""
    return _snapshot


def load_snapshot() -> AuthSnapshot:
    """Load from DB and refresh the cache. The only DB read entry point for
    callers outside this module (middleware cold path, T2)."""
    with _lock:
        return _load_locked()


def attempt_pin(candidate: object) -> Optional[str]:
    """CD-114a-13's atomic entry point. Synchronous — must NEVER contain
    `await` / `asyncio.sleep` (the fixed per-attempt delay is the caller's
    job, in the async endpoint, and must run *before* this is invoked via
    `asyncio.to_thread`). One `threading.Lock` acquisition covers the whole
    "decide → compare → update retry state → mint ticket + refresh cache"
    sequence so a lost-update race can never let a stale/expired lockout
    slip an attempt through.

    Returns the new ticket token on success, `None` on any failure (wrong
    PIN, malformed candidate, locked-out, or auth disabled) — callers must
    not try to distinguish those cases from the return value alone.
    """
    global _consecutive_failures, _lockout_started_at, _snapshot
    with _lock:
        snap = _snapshot if _snapshot is not None else _load_locked()
        if not snap.enabled:
            return None

        now = _now()
        allowed, _remaining = _decide_lockout(_consecutive_failures, now, _lockout_started_at)
        if not allowed:
            return None
        if _lockout_started_at is not None:
            # This tier's lockout has expired (Opus 補充 C): clear the
            # start marker but keep the failure count — resetting it would
            # freeze the escalation ladder at the first 60s tier forever.
            _lockout_started_at = None

        canonical = _canonical_pin(candidate)
        if canonical is not None:
            matched = hmac.compare_digest(canonical.encode("utf-8"), snap.pin.encode("utf-8"))
        else:
            matched = False

        if not matched:
            _consecutive_failures += 1
            if _consecutive_failures % _LOCKOUT_THRESHOLD == 0:
                _lockout_started_at = now
            return None

        token = secrets.token_urlsafe(32)
        conn = _connect()
        try:
            conn.execute(
                "INSERT INTO access_tickets (token, kind) VALUES (?, 'browser')",
                (token,),
            )
            conn.commit()
        finally:
            conn.close()
        # Only clear retry state / swap the cache once the DB write is
        # confirmed committed (independent review P2): if `conn.execute`/
        # `commit()` above raises, the exception must leave the retry
        # counter and the cache exactly as they were — clearing them first
        # would let a DB failure silently forgive a lockout without ever
        # actually minting a usable ticket.
        _consecutive_failures = 0
        _lockout_started_at = None
        _snapshot = AuthSnapshot(
            enabled=snap.enabled,
            pin=snap.pin,
            valid_tokens=snap.valid_tokens | {token},
            agent_token=snap.agent_token,
        )
        return token


def get_auth_settings(reveal: bool) -> dict:
    """`{"enabled": bool, "pin": <real value if reveal else masked>}`.
    `reveal` is the caller's call (via `_is_loopback_host()`, web layer) —
    this module does not look at where the request came from."""
    with _lock:
        snap = _snapshot if _snapshot is not None else _load_locked()
    return {"enabled": snap.enabled, "pin": snap.pin if reveal else "••••"}


def set_auth(enabled: bool, pin: str) -> None:
    """Lock-held "validate format → write DB → revoke_all → refresh cache".
    The sole R5 trigger point. Raises `ValueError` (does not write, does
    not revoke, does not touch retry state) when `enabled=True` and `pin`
    is not exactly 4 ASCII digits — a raised exception forces the caller
    (T4) to handle the no-op explicitly, unlike a `False` return value
    that's easy to ignore.

    When `enabled=False`, `pin`'s content is ignored entirely (not format
    checked, not stored) but the full write + revoke + cache-refresh still
    runs — turning auth off must invalidate every outstanding ticket
    unconditionally (R5), never conditioned on whether `pin` happens to be
    well-formed.

    On every successful write (Opus 補充 E'), the retry-lockout counters
    are also cleared. The caller PUT /api/access/settings allows local or
    authenticated requests, and any source when the password is currently
    off. The latter cannot bypass password protection because none is active.
    Clearing retry-lockout counters lets the owner immediately un-stick a
    family member instead of waiting out the escalation ladder (up to an hour).
    """
    canonical = _canonical_pin(pin)
    if enabled and canonical is None:
        raise ValueError("pin must be exactly 4 ASCII alphanumerics")
    # Store the NFKC-folded form, never the raw input: what goes in the DB
    # is what the verify path will compare against.
    stored_pin = canonical if enabled else ""

    global _snapshot, _consecutive_failures, _lockout_started_at
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO access_auth (id, enabled, pin) VALUES (1, ?, ?)",
                (1 if enabled else 0, stored_pin),
            )
            _revoke_all_locked(conn)
            # CD-114b-1: `enabled == True` iff exactly one agent ticket
            # exists. `_revoke_all_locked` just wiped every ticket
            # (browser AND any prior agent one) in this same transaction,
            # so the only place left to mint the new agent ticket that
            # keeps the invariant true is right here.
            agent_token = _new_agent_token() if enabled else None
            if agent_token is not None:
                conn.execute(
                    "INSERT INTO access_tickets (token, kind) VALUES (?, 'agent')",
                    (agent_token,),
                )
            conn.commit()
        finally:
            conn.close()
        _snapshot = AuthSnapshot(
            enabled=enabled,
            pin=stored_pin,
            valid_tokens=frozenset({agent_token}) if agent_token is not None else frozenset(),
            agent_token=agent_token,
        )
        _consecutive_failures = 0
        _lockout_started_at = None


def revoke_all() -> None:
    """Unconditional `DELETE FROM access_tickets`, then refresh the cache's
    `valid_tokens` to empty. No parameters — deliberately: a conditional
    revoke would break R5's "no exceptions" semantics."""
    global _snapshot
    with _lock:
        conn = _connect()
        try:
            _revoke_all_locked(conn)
            conn.commit()
        finally:
            conn.close()
        base = _snapshot if _snapshot is not None else _load_locked()
        # R5 covers the agent ticket too: `DELETE FROM access_tickets` above
        # already removed it from the DB, so the cache must reflect that
        # (TASK-114b-T1 DoD) — carrying `base.agent_token` forward here
        # would leave the cache pointing at a ticket that no longer exists.
        _snapshot = AuthSnapshot(
            enabled=base.enabled, pin=base.pin, valid_tokens=frozenset(), agent_token=None
        )


def verify_ticket(token: Optional[str]) -> bool:
    """Does `token` currently hold a valid ticket? Pure read of `snapshot()`
    — zero I/O, legal to call directly from the middleware hot path
    (CD-114a-11). Cold cache (`snapshot()` is `None`) fails closed: the
    cold-load responsibility belongs to the caller (T2's `load_snapshot()`
    on startup), not to this function reaching into the DB itself."""
    if not token:
        return False
    snap = snapshot()
    if snap is None:
        return False
    return token in snap.valid_tokens


def reset_state_for_tests() -> None:
    """Test-only reset seam for the process-global cache/retry state. Not
    one of the 8 public functions T2/T3/T4 are contracted to call — the
    name says so. Module-level state otherwise leaks across tests in the
    same process."""
    global _snapshot, _consecutive_failures, _lockout_started_at
    with _lock:
        _snapshot = None
        _consecutive_failures = 0
        _lockout_started_at = None
