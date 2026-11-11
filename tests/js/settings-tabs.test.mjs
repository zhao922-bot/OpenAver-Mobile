import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
    isSettingsTab,
    resolveSettingsTab,
    SETTINGS_TABS,
} from '../../app/src/main/python/web/static/js/pages/settings/settings-tabs.js';
import { resolveHelpTab } from '../../app/src/main/python/web/static/js/pages/help/help-tabs.js';

test('settings tabs prefer valid hashes and migrate legacy section ids', () => {
    assert.deepEqual(SETTINGS_TABS, ['sources', 'naming', 'gallery', 'ai', 'system']);
    assert.equal(resolveSettingsTab({ hash: '#ai', stored: 'gallery' }), 'ai');
    assert.equal(resolveSettingsTab({ hash: '#sec-gallery', stored: 'sources' }), 'gallery');
    assert.equal(resolveSettingsTab({ hash: '#sec-system' }), 'system');
    assert.equal(resolveSettingsTab({ hash: '#unknown', stored: 'naming' }), 'naming');
    assert.equal(resolveSettingsTab({}), 'sources');
    assert.equal(isSettingsTab('ai'), true);
    assert.equal(isSettingsTab('unknown'), false);
});

test('help hashes open the matching tab and retain legacy anchors', () => {
    assert.equal(resolveHelpTab('#organize'), 'organize');
    assert.equal(resolveHelpTab('#manual'), 'manual');
    assert.equal(resolveHelpTab('#mobile-help-storage'), 'library');
    assert.equal(resolveHelpTab('#mobile-help-tasks'), 'organize');
    assert.equal(resolveHelpTab('#mobile-help-trouble'), 'manual');
    assert.equal(resolveHelpTab('#unknown'), 'library');
});
