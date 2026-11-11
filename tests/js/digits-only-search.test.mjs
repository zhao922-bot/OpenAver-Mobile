import { test } from 'node:test';
import assert from 'node:assert/strict';

import { isDigitsOnlySearch } from '../../app/src/main/python/web/static/js/shared/digits-only-search.js';

test('digits-only search normalizes width and trims whitespace', () => {
    for (const value of ['199', '001', '１９９', ' 199 ', '2024']) {
        assert.equal(isDigitsOnlySearch(value), true, value);
    }
    for (const value of ['', ' ', 'SSIS-001', '19a', '199 三上', '2024-05']) {
        assert.equal(isDigitsOnlySearch(value), false, value);
    }
});
