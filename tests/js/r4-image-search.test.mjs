import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
    imageSearchFailure,
    imageSearchHasPrivacyConsent,
    isSupportedImageFile,
} from '../../app/src/main/python/web/static/js/pages/search/image-search-rules.js';

test('image search accepts only supported image files', () => {
    assert.equal(isSupportedImageFile({ name: 'cover.jpg', type: 'image/jpeg' }), true);
    assert.equal(isSupportedImageFile({ name: 'frame.webp', type: '' }), true);
    assert.equal(isSupportedImageFile({ name: 'clip.gif', type: 'image/gif' }), false);
    assert.equal(isSupportedImageFile({ name: 'notes.txt', type: 'text/plain' }), false);
});

test('image search maps API failures to localized keys', () => {
    assert.deepEqual(imageSearchFailure({ error: 'rate_limited', retry_after: 7 }), {
        key: 'search.image.rate_limited',
        params: { seconds: 7 },
    });
    assert.deepEqual(imageSearchFailure({ error: 'file_too_large' }), {
        key: 'search.image.too_large',
        params: {},
    });
    assert.deepEqual(imageSearchFailure({ error: 'unsupported_image' }), {
        key: 'search.image.unsupported',
        params: {},
    });
    assert.deepEqual(imageSearchFailure({ error: 'unreachable' }), {
        key: 'search.image.unreachable',
        params: {},
    });
});

test('image search privacy consent is scoped to localStorage', () => {
    assert.equal(imageSearchHasPrivacyConsent({ getItem: () => '1' }), true);
    assert.equal(imageSearchHasPrivacyConsent({ getItem: () => null }), false);
    assert.equal(
        imageSearchHasPrivacyConsent({
            getItem: () => {
                throw new Error('blocked');
            },
        }),
        false,
    );
});
