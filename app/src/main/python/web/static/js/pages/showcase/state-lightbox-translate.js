/**
 * state-lightbox-translate.js — Showcase ESM（172-T5）
 *
 * 燈箱標題翻譯鈕：翻譯 → 寫回 NFO／DB（POST /api/showcase/video/title）→ toast「復原」。
 * mergeState 分片（plan-172 CD-172-7）：不定義 init()（FE-ALPINE-05）、頂層 key 一律 lbTr／_lbTr 前綴。
 * 時序（CD-172-8）：鎖 _lbTrInFlight[path] 在任何 await 之前設起、涵蓋翻譯＋寫回兩段 fetch；
 * await 之後只改「按下當下捕獲的那個 video 物件」，切片不影響結果落點。
 */

import { translateFailureToastKey } from '@/shared/translate-provider.js';

const LB_TR_UNDO_TOAST_MS = 6000;

export function stateLightboxTranslate() {
    return {
        // path → true；與 _pickInFlight 同形（per-path 鎖，切片不清）
        _lbTrInFlight: {},

        // 翻譯開關：只讀 showcase.html 注入的 {enabled}（沿用 state-base 的 typeof 守衛）
        get lbTranslateEnabled() {
            return typeof window !== 'undefined' && window.__SHOWCASE_TRANSLATE__?.enabled === true;
        },

        // 主標題固定提供翻譯入口；有原文時翻譯原文，沒有時翻譯目前標題。
        lbTrShowOnTitle() {
            return this.lbTranslateEnabled && !!this.currentLightboxVideo?.title;
        },

        lbTrIsBusy() {
            return !!this._lbTrInFlight[this.currentLightboxVideo?.path];
        },

        async lbTranslate() {
            const video = this.currentLightboxVideo;
            if (!video || !video.path) return;
            const path = video.path;
            if (this._lbTrInFlight[path]) return;
            this._lbTrInFlight[path] = true;
            const snapshot = { title: video.title || '', original_title: video.original_title || '' };
            try {
                let trData;
                try {
                    const trResp = await fetch('/api/translate', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            text: video.original_title || video.title || '',
                            mode: 'translate',
                            force: true,
                            actors: (video.actresses || '').split(',').map((a) => a.trim()).filter(Boolean),
                            number: video.number || '',
                        }),
                    });
                    if (!trResp.ok) throw new Error(`HTTP ${trResp.status}`);
                    trData = await trResp.json();
                } catch (e) {
                    this.showToast(window.t(translateFailureToastKey(undefined)), 'error');
                    return;
                }
                if (trData.skipped === true) {
                    this.showToast(window.t('showcase.lightbox.translate_skipped'), 'info');
                    return;
                }
                if (trData.success !== true || typeof trData.result !== 'string' || !trData.result) {
                    this.showToast(window.t(translateFailureToastKey(trData.reason)), 'error');
                    return;
                }
                const translated = trData.result;
                let data;
                try {
                    const resp = await fetch('/api/showcase/video/title', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ file_path: path, title: translated }),
                    });
                    try {
                        data = await resp.json();
                    } catch (parseError) {
                        throw new Error(`HTTP ${resp.status}: invalid JSON`);
                    }
                    if (!resp.ok) {
                        throw new Error(`HTTP ${resp.status}: ${data?.message || data?.error || 'request failed'}`);
                    }
                } catch (e) {
                    console.error('[title-writeback] request failed', { path, error: e });
                    this.showToast(e.message || window.t('showcase.lightbox.translate_write_failed'), 'error');
                    return;
                }
                if (data.success === true) {
                    this._lbTrApply(video, data);
                    const toastKey = data.nfo_created
                        ? 'showcase.lightbox.translate_done_nfo_created'
                        : 'showcase.lightbox.translate_done';
                    this.showToast(window.t(toastKey), 'success', LB_TR_UNDO_TOAST_MS, {
                        label: window.t('showcase.lightbox.translate_undo'),
                        onClick: () => this._lbTrUndo(video, snapshot),
                    });
                } else {
                    const key = data.error === 'no_nfo' ? 'translate_no_nfo' : 'translate_write_failed';
                    console.error('[title-writeback] API rejected', { path, data });
                    const message = data.error === 'no_nfo'
                        ? window.t(`showcase.lightbox.${key}`)
                        : (data.message || window.t(`showcase.lightbox.${key}`));
                    this.showToast(message, 'error');
                }
            } finally {
                delete this._lbTrInFlight[path];
            }
        },

        // 後端回的三欄原樣覆蓋到捕獲的 video 物件（不自己算）
        _lbTrApply(video, data) {
            video.title = data.title;
            video.original_title = data.original_title;
            video.needs_translate = data.needs_translate;
            video.can_translate = data.can_translate;
        },

        // 復原：只用按下當下的 snapshot 與當時捕獲的那一片；不佔 _lbTrInFlight（plan 已接受的併發 residual）
        async _lbTrUndo(video, snapshot) {
            const path = video.path;
            try {
                const resp = await fetch('/api/showcase/video/title', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        file_path: path,
                        title: snapshot.title,
                        original_title: snapshot.original_title,
                    }),
                });
                if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
                const data = await resp.json();
                if (data.success !== true) throw new Error(data.error || 'API failed');
                this._lbTrApply(video, data);
                this.showToast(window.t('showcase.lightbox.translate_undone'), 'success');
            } catch (e) {
                this.showToast(window.t('showcase.lightbox.translate_write_failed'), 'error');
            }
        },
    };
}
