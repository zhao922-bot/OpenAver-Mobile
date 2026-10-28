// 168b-T3: pure helpers for the sidebar plug (connection state) and nav interception.
// Zero imports so node:test can load it directly.

/**
 * Next connection state after one notification poll.
 * @param {'ok'|'down'} prev
 * @param {'ok'|'error'|'bad_body'|'not_ok'} outcome  error = fetch threw; bad_body = 2xx but body is not the notifications JSON (e.g. password page); not_ok = non-2xx response
 * @returns {'ok'|'down'}
 */
export function nextConnState(prev, outcome) {
  if (outcome === 'ok') return 'ok';
  if (outcome === 'error' || outcome === 'bad_body') return 'down';
  return prev;
}

/**
 * Whether a sidebar navigation click should be intercepted (shell offline page).
 * @param {{state: string, mode: string, hasOfflineBridge: boolean}} args
 * @returns {boolean}
 */
export function shouldInterceptNav({ state, mode, hasOfflineBridge }) {
  return state === 'down' && mode === 'client' && hasOfflineBridge === true;
}

if (typeof window !== 'undefined') {
  window.OpenAver = window.OpenAver || {};
  window.OpenAver.conn = { nextConnState, shouldInterceptNav };
}
