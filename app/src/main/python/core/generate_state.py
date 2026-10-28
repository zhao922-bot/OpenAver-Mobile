"""In-flight generate registry — lets the settings mode-switch refuse while a
`GET /api/gallery/generate` SSE is still running (feature/90 Finding 2 guard).

Why this exists: `switch_external_manager` purges the offline sources' DB cards.
If a readonly `generate` is streaming at the same time, its background producer
thread keeps `_upsert_db`-ing the same readonly rows *after* the purge deletes
them → the "switch mode = clean" contract breaks. The generate handler registers
a unique token for its lifetime; the switch endpoint refuses while any token is
active.

Bidirectional mutex (PR #93 Codex P1): the original guard only blocked switch while
a generate was *already* registered. But a generate that *starts* during the switch's
purge/config-mutation window (after switch's entry check, before it finishes) would
register, read the still-old readonly sources, and `_upsert_db` the just-purged rows
back → cards leak despite the guard. So the switch now holds `_switch_active` for its
WHOLE window (`try_begin_switch` → `end_switch`), and generate's registration
(`try_mark_generate_active`) refuses while a switch is active. Both operations are
atomic under the same `_lock`, so neither direction can slip through.

Thread-safety: `generate()` (async handler / event loop) registers and clears;
`switch_external_manager` (sync def → threadpool) begins/ends the switch. A plain
`threading.Lock` serialises across both. Tokens are the per-request `cancel_event`
objects (unique by identity), so add/discard are idempotent and never collide.

⚠️ Known residual (documented, owner-accepted): the token is cleared in the
disconnect watcher's `finally`, which fires the instant a client disconnect is
detected — the producer thread may process *one more file* before it observes
`should_abort` at the next per-file checkpoint. So a switch fired in that sub-second
window right after a disconnect could still race a single re-insert. This is far
smaller than the original unbounded race and is not perfect serialisation by design.
"""
import threading

_lock = threading.Lock()
_active_tokens: set = set()
_switch_active = False  # True while switch_external_manager is mid-purge (PR #93 P1)
# Per-save identity tokens for in-flight PUT /api/config full saves (PR #93 P2-e / 五審).
# A SET, not a bool/counter: overlapping saves each hold their own token, so a first-ending
# save's `end_config_save(token)` only discards ITS token — it can't clear a second save's
# still-open window (the bool version let that happen → switch slipped in → race reopened).
_config_save_tokens: set = set()


def mark_generate_active(token) -> None:
    """Register a generate as in-flight (call at handler start, before producing).

    Deprecated in favour of `try_mark_generate_active` (which also honours an
    in-progress switch); kept for any caller/test that only needs registration.
    """
    with _lock:
        _active_tokens.add(token)


def try_mark_generate_active(token) -> bool:
    """Atomically register a generate UNLESS a switch is currently in progress.

    Returns False (caller must refuse to start) when `switch_external_manager` holds
    the window — prevents the producer re-inserting rows the switch is purging (P1).
    """
    with _lock:
        if _switch_active:
            return False
        _active_tokens.add(token)
        return True


def try_begin_switch():
    """Atomically begin a switch UNLESS a generate, another switch, OR a full-config
    save is in-flight.

    Returns None on success (switch owns the exclusion window until `end_switch()`;
    new generates AND full-config saves are refused meanwhile). Otherwise returns a
    refusal-reason string the caller surfaces to the frontend:
    - 'generate_in_progress' — a generate SSE is registered (original forward guard).
    - 'switch_in_progress'   — another switch already holds the window (PR #93 P2):
      without this, a 2nd overlapping switch would enter, and the 1st's `end_switch()`
      would clear `_switch_active` mid-2nd-window → a generate could slip in and
      re-upsert purged rows. Switches must serialise, not just exclude generates.
    - 'config_save_in_progress' — a `PUT /api/config` full-config save holds its write
      window (PR #93 P2-e): the switch must not begin its purge while a stale-snapshot
      full save is mid-write, or the save's `mutate_config` interleaves with the purge
      and resurrects just-deleted offline-source `gallery.directories` entries.
    """
    global _switch_active
    with _lock:
        if _active_tokens:
            return 'generate_in_progress'
        if _switch_active:
            return 'switch_in_progress'
        if _config_save_tokens:
            return 'config_save_in_progress'
        _switch_active = True
        return None


def end_switch() -> None:
    """Release the switch exclusion window (call from switch's `finally`)."""
    global _switch_active
    with _lock:
        _switch_active = False


def try_begin_config_save(token):
    """Atomically register a full-config save UNLESS a switch is in progress (PR #93 P2-e).

    `token` is a per-request identity object (mirrors `_active_tokens`); the caller keeps it
    and passes the SAME token to `end_config_save(token)` in its `finally`.

    Returns None on success (the caller's write window is open until `end_config_save(token)`;
    a switch that tries to begin meanwhile is refused with 'config_save_in_progress'). Otherwise
    returns 'switch_in_progress' — the caller must refuse the save, because a switch's purge is
    mid-flight and this save carries a pre-switch snapshot that would overwrite the just-purged
    `gallery.directories`.

    True mutual exclusion replacing the old `is_switch_in_progress()` preflight, which was
    TOCTOU: a save could pass the point-in-time check *before* a switch began, then land its
    `mutate_config` *after* the switch finished purging. Now each save holds a token in
    `_config_save_tokens` for its WHOLE write window and `try_begin_switch` refuses while ANY
    token is registered — both atomic under the same `_lock`, so switch and save never interleave.

    A token SET, not a bool (PR #93 五審 Codex): the bool version let a 2nd overlapping save enter
    (it only checked `_switch_active`), then the 1st save's `end_config_save()` cleared the shared
    flag while the 2nd was still writing → switch could slip in → the very P2-e race reopened.
    Per-token add/discard means a first-ending save can't clear a second's still-open window, and
    double-`end` of one token is a harmless no-op.

    ⚠️ Known residual (documented, owner-accepted): a save whose snapshot was captured before a
    switch that has since *fully completed* (begin→purge→end all done before the save even
    starts) is a plain lost-update, not an interleave — no mutex can catch it. It relies on the
    switch's destructive-confirm "please refresh other tabs" hint; sub-second, self-healing
    (next generate rebuilds the cards), no data loss. Generate saves may coexist with a config
    save (they don't touch `gallery.directories` writes here) → only switch is excluded.
    """
    with _lock:
        if _switch_active:
            return 'switch_in_progress'
        _config_save_tokens.add(token)
        return None


def end_config_save(token) -> None:
    """Release a full-config save window (call from update_config's `finally`).

    Discards only THIS save's token (idempotent) → overlapping saves don't clobber each
    other's window; the switch stays excluded until the LAST in-flight save ends."""
    with _lock:
        _config_save_tokens.discard(token)


def mark_generate_done(token) -> None:
    """Clear a generate token (idempotent; call from the watcher `finally` so it
    runs on BOTH normal-completion and client-disconnect paths)."""
    with _lock:
        _active_tokens.discard(token)


def is_generate_in_progress() -> bool:
    """True if any generate SSE is currently registered as in-flight."""
    with _lock:
        return bool(_active_tokens)
