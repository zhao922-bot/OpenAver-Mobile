export const IMAGE_SEARCH_MAX_BYTES = 8 * 1024 * 1024;
export const IMAGE_SEARCH_PRIVACY_KEY = 'openaver_image_search_privacy_v1';

const SUPPORTED_MIME = new Set(['image/jpeg', 'image/png', 'image/webp']);
const SUPPORTED_EXT = new Set(['jpg', 'jpeg', 'png', 'webp']);

export function isSupportedImageFile(file) {
    if (!file) return false;
    const type = String(file.type || '').toLowerCase();
    if (SUPPORTED_MIME.has(type)) return true;
    if (type && type.startsWith('image/')) return false;
    const name = String(file.name || '').toLowerCase();
    const dot = name.lastIndexOf('.');
    return dot >= 0 && SUPPORTED_EXT.has(name.slice(dot + 1));
}

export function imageSearchFailure(data) {
    const code = data && typeof data.error === 'string'
        ? data.error
        : 'unreachable';
    if (code === 'rate_limited') {
        return {
            key: 'search.image.rate_limited',
            params: {
                seconds: Math.max(1, Math.ceil(Number(data?.retry_after) || 5)),
            },
        };
    }
    if (code === 'file_too_large') {
        return { key: 'search.image.too_large', params: {} };
    }
    if (code === 'unsupported_image') {
        return { key: 'search.image.unsupported', params: {} };
    }
    return { key: 'search.image.unreachable', params: {} };
}

export function imageSearchHasPrivacyConsent(storage) {
    try {
        return storage?.getItem(IMAGE_SEARCH_PRIVACY_KEY) === '1';
    } catch {
        return false;
    }
}
