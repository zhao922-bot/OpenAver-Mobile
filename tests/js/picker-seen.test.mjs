import { test } from 'node:test';
import assert from 'node:assert/strict';

import { MAX_SENT, addSeen, buildCandidatesUrl } from '../../app/src/main/python/web/static/js/shared/picker-seen.js';

test('seen candidates are deduplicated without dropping earlier ids', () => {
    const first = addSeen([], 'a1b2c3d4');
    const second = addSeen(first, '11223344');
    assert.deepEqual(second, ['a1b2c3d4', '11223344']);
    assert.deepEqual(addSeen(second, 'a1b2c3d4'), second);
    assert.notEqual(addSeen(second, 'a1b2c3d4'), second);
    assert.deepEqual(addSeen(second, ''), second);
});

test('candidate URL keeps the original first-open form and sends only recent exclusions', () => {
    const base = '/api/actresses/%E4%B8%89%E4%B8%8A/photo-candidates';
    assert.equal(buildCandidatesUrl('三上', 0, []), base);
    assert.equal(buildCandidatesUrl('三上', 2, []), `${base}?attempt=2`);
    assert.equal(buildCandidatesUrl('三上', 0, ['a1b2c3d4']), `${base}?exclude=a1b2c3d4`);

    const many = Array.from({ length: MAX_SENT + 3 }, (_, i) => i.toString(16).padStart(8, '0'));
    const url = buildCandidatesUrl('三上', 3, many);
    assert.ok(url.startsWith(`${base}?attempt=3&exclude=`));
    assert.equal(url.split('exclude=')[1].split(',').length, MAX_SENT);
    assert.ok(url.endsWith(many.at(-1)));
});
