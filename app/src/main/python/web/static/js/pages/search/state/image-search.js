import {
    IMAGE_SEARCH_MAX_BYTES,
    IMAGE_SEARCH_PRIVACY_KEY,
    imageSearchFailure,
    imageSearchHasPrivacyConsent,
    isSupportedImageFile,
} from '../image-search-rules.js';

function revokeObjectUrl(url) {
    if (url) URL.revokeObjectURL(url);
}

function loadImage(url) {
    return new Promise((resolve, reject) => {
        const image = new Image();
        image.onload = () => resolve(image);
        image.onerror = () => reject(new Error('image_decode_failed'));
        image.src = url;
    });
}

function canvasToBlob(canvas, quality) {
    return new Promise((resolve, reject) => {
        canvas.toBlob(
            (blob) => (blob ? resolve(blob) : reject(new Error('encode_failed'))),
            'image/jpeg',
            quality,
        );
    });
}

async function prepareUpload(file, previewUrl) {
    if (file.size <= IMAGE_SEARCH_MAX_BYTES) return file;
    const image = await loadImage(previewUrl);
    const width = image.naturalWidth || image.width;
    const height = image.naturalHeight || image.height;
    if (!width || !height) throw new Error('image_decode_failed');

    const edgeScale = Math.min(1, 1024 / Math.max(width, height));
    let scale = Math.min(
        edgeScale,
        Math.max(0.2, Math.sqrt(IMAGE_SEARCH_MAX_BYTES / file.size) * 0.9),
    );
    for (const quality of [0.85, 0.72, 0.58]) {
        const canvas = document.createElement('canvas');
        canvas.width = Math.max(1, Math.round(width * scale));
        canvas.height = Math.max(1, Math.round(height * scale));
        const context = canvas.getContext('2d');
        if (!context) throw new Error('encode_failed');
        context.drawImage(image, 0, 0, canvas.width, canvas.height);
        const blob = await canvasToBlob(canvas, quality);
        if (blob.size <= IMAGE_SEARCH_MAX_BYTES) {
            const stem = String(file.name || 'image').replace(/\.[^.]+$/, '');
            return new File([blob], `${stem}.jpg`, { type: 'image/jpeg' });
        }
        scale *= 0.8;
    }
    throw new Error('image_too_large');
}

export function searchStateImageSearch() {
    return {
        imgSearchPhase: 'idle',
        imgSearchResultsOpen: false,
        imgSearchCandidates: [],
        imgSearchClearHit: false,
        imgSearchError: null,
        imgSearchPreviewUrl: '',
        imgSearchPrivacyOpen: false,
        _imgSearchAbort: null,
        _imgSearchGeneration: 0,
        _imgSearchPendingFile: null,

        imgSearchPickFile() {
            if (this.imgSearchPhase === 'querying') return;
            this.$refs.imgSearchFile?.click();
        },

        imgSearchOnFilePicked(event) {
            const file = event?.target?.files?.[0];
            if (event?.target) event.target.value = '';
            if (!file) return;
            if (!isSupportedImageFile(file)) {
                this.showToast(window.t('search.image.unsupported'), 'error');
                return;
            }
            if (imageSearchHasPrivacyConsent(localStorage)) {
                this.imgSearchStart(file);
                return;
            }
            this._imgSearchPendingFile = file;
            this.imgSearchPrivacyOpen = true;
        },

        imgSearchAcceptPrivacy() {
            try {
                localStorage.setItem(IMAGE_SEARCH_PRIVACY_KEY, '1');
            } catch {
                // Storage may be unavailable; consent still applies to this run.
            }
            const file = this._imgSearchPendingFile;
            this._imgSearchPendingFile = null;
            this.imgSearchPrivacyOpen = false;
            if (file) this.imgSearchStart(file);
        },

        imgSearchDeclinePrivacy() {
            this._imgSearchPendingFile = null;
            this.imgSearchPrivacyOpen = false;
        },

        imgSearchCloseResults() {
            this._imgSearchGeneration += 1;
            if (this._imgSearchAbort) {
                this._imgSearchAbort.abort();
                this._imgSearchAbort = null;
            }
            revokeObjectUrl(this.imgSearchPreviewUrl);
            this.imgSearchPreviewUrl = '';
            this.imgSearchResultsOpen = false;
            this.imgSearchPhase = 'idle';
            this.imgSearchCandidates = [];
            this.imgSearchClearHit = false;
            this.imgSearchError = null;
        },

        imgSearchCancel() {
            this.imgSearchCloseResults();
        },

        async imgSearchStart(file) {
            if (!file || this.imgSearchPhase === 'querying') return;
            const generation = ++this._imgSearchGeneration;
            if (this._imgSearchAbort) this._imgSearchAbort.abort();
            const controller = new AbortController();
            this._imgSearchAbort = controller;

            revokeObjectUrl(this.imgSearchPreviewUrl);
            this.imgSearchPreviewUrl = URL.createObjectURL(file);
            this.imgSearchCandidates = [];
            this.imgSearchClearHit = false;
            this.imgSearchError = null;
            this.imgSearchResultsOpen = true;
            this.imgSearchPhase = 'querying';

            try {
                let uploadFile;
                try {
                    uploadFile = await prepareUpload(file, this.imgSearchPreviewUrl);
                } catch (error) {
                    if (generation !== this._imgSearchGeneration) return;
                    this.imgSearchError = {
                        key: error?.message === 'image_too_large'
                            ? 'search.image.too_large'
                            : 'search.image.unsupported',
                        params: {},
                    };
                    return;
                }
                if (generation !== this._imgSearchGeneration) return;

                const form = new FormData();
                form.append('file', uploadFile);
                let response;
                let data;
                try {
                    response = await fetch('/api/image-search', {
                        method: 'POST',
                        body: form,
                        signal: controller.signal,
                    });
                    try {
                        data = await response.json();
                    } catch {
                        data = null;
                    }
                } catch (error) {
                    if (controller.signal.aborted) return;
                    data = null;
                }
                if (generation !== this._imgSearchGeneration) return;
                if (!response?.ok || data?.success !== true) {
                    this.imgSearchError = imageSearchFailure(data);
                    return;
                }
                const candidates = Array.isArray(data.candidates)
                    ? data.candidates
                    : [];
                if (candidates.length === 0) {
                    this.imgSearchError = {
                        key: 'search.image.no_candidates',
                        params: {},
                    };
                    return;
                }
                this.imgSearchCandidates = candidates;
                this.imgSearchClearHit = data.clear_hit === true;
            } finally {
                if (generation === this._imgSearchGeneration) {
                    this.imgSearchPhase = 'idle';
                }
                if (this._imgSearchAbort === controller) {
                    this._imgSearchAbort = null;
                }
            }
        },

        imgSearchErrorText() {
            if (!this.imgSearchError?.key) return '';
            return window.t(this.imgSearchError.key, this.imgSearchError.params || {});
        },

        imgSearchCandidateMatch(candidate) {
            const match = candidate?.match || {};
            if (match.time_text) return match.time_text;
            if (match.kind === 'cover') {
                return window.t('search.image.match.cover');
            }
            return window.t('search.image.match.frame');
        },

        imgSearchCandidateSimilarity(candidate) {
            const value = Number(candidate?.similarity);
            return Number.isFinite(value) ? `${value.toFixed(1)}%` : '-';
        },

        imgSearchCandidateLibrary(candidate) {
            if (candidate?.in_library === true) {
                return window.t('search.image.in_library');
            }
            if (candidate?.in_library === false) {
                return window.t('search.image.not_in_library');
            }
            return '';
        },

        imgSearchUseCandidate(candidate) {
            if (!candidate?.searchable || !candidate?.number) return;
            const number = candidate.number;
            this.imgSearchCloseResults();
            this.searchQuery = number;
            this.doSearch(number);
        },
    };
}
