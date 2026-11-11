import { test } from 'node:test';
import assert from 'node:assert/strict';

import { computeBadges } from '../../app/src/main/python/web/static/js/shared/cover-badges.js';

const manifest = [
    {
        id: 'cracked',
        canonical_tag: '無碼破解',
        match_aliases: ['AI'],
        display_name: 'AI',
        display_order: 2,
        supersedes: [],
    },
    {
        id: 'ltx',
        canonical_tag: 'LTX',
        match_aliases: [],
        display_name: 'LTX',
        display_order: 2,
        supersedes: ['cracked'],
    },
];

test('LTX badge supersedes the cracked AI badge', () => {
    const badges = computeBadges(
        { tags: '無碼破解,LTX', user_tags: [] },
        manifest,
        {},
        ['cracked', 'ltx'],
    );
    assert.deepEqual(badges, [{ id: 'ltx', display_name: 'LTX' }]);
});

test('cracked remains visible when LTX is disabled or absent', () => {
    const video = { tags: '無碼破解', user_tags: [] };
    assert.deepEqual(
        computeBadges(video, manifest, {}, ['cracked']),
        [{ id: 'cracked', display_name: 'AI' }],
    );
    assert.deepEqual(
        computeBadges(video, manifest, {}, ['cracked', 'ltx']),
        [{ id: 'cracked', display_name: 'AI' }],
    );
});
