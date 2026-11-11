import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
    adoptIntoBlankFile,
    makeBlankCard,
    organizeState,
    skipAutoTranslate,
} from '../../app/src/main/python/web/static/js/pages/search/blank-card-rules.js';

test('blank card is stable, editable, and organizable only with number and title', () => {
    const file = { number: 'JURA-1113', searchResults: [], blankCard: null };
    file.blankCard = makeBlankCard(file);
    assert.equal(file.blankCard._blank, true);
    assert.equal(file.blankCard.number, 'JURA-1113');
    for (const value of Object.values(file.blankCard)) {
        assert.notEqual(value, undefined);
        assert.notEqual(value, null);
    }

    assert.equal(organizeState(file), 'none');
    file.blankCard.title = '手填標題';
    assert.equal(organizeState(file), 'ready');
    file.blankCard.number = ' ';
    assert.equal(organizeState(file), 'needs_number');
});

test('advanced search result attaches by path and never overwrites real results', () => {
    const target = { path: '/a.mp4', number: '', searched: true, searchResults: [], blankCard: { _blank: true } };
    const other = { path: '/b.mp4', number: 'BBB-2', searched: true, searchResults: [], blankCard: { _blank: true } };
    const variant = { number: 'JURA-1113', title: 'result' };

    assert.equal(adoptIntoBlankFile([target, other], { filePath: target.path }, variant), true);
    assert.equal(target.searchResults[0], variant);
    assert.equal(target.number, 'JURA-1113');
    assert.equal(target.blankCard, null);
    assert.equal(other.searchResults.length, 0);

    const filled = { path: '/filled.mp4', searched: true, searchResults: [], blankCard: { _blank: true } };
    assert.equal(adoptIntoBlankFile([filled], { filePath: filled.path }, variant), true);
    assert.equal(adoptIntoBlankFile([filled], { filePath: filled.path }, variant), false);
    assert.equal(filled.searchResults.length, 1);
});

test('manual translated title skips automatic translation', () => {
    assert.equal(skipAutoTranslate({ manual_entry: true, translated_title: '中文片名' }), true);
    assert.equal(skipAutoTranslate({ manual_entry: true, translated_title: ' ' }), false);
    assert.equal(skipAutoTranslate({ manual_entry: false, translated_title: '中文片名' }), false);
});
