/**
 * Lightbox plot panel: lazy NFO read, translation, writeback, and undo.
 *
 * A generation token invalidates late reads after close or video changes.
 * Translation results are applied only to the view object captured at click
 * time, so a late response can never overwrite the next video.
 */

import { translateFailureToastKey } from '@/shared/translate-provider.js';
import {
    applyPlotLoadResult,
    plotFaceButtons,
    sameAfterNormalize,
} from './lb-plot-logic.js';

const UNDO_TOAST_MS = 6000;

function emptyPlotView() {
    return {
        path: '',
        loading: false,
        error: false,
        plot: '',
        original: '',
        hasOriginal: false,
        showing: 'plot',
    };
}

export function stateLightboxPlot() {
    return {
        lbPlotOpen: false,
        _lbPlotView: emptyPlotView(),
        _lbPlotInFlight: {},
        _lbPlotGen: 0,
        _lbPlotAbort: null,

        get lbPlotTranslateEnabled() {
            return typeof window !== 'undefined'
                && window.__SHOWCASE_TRANSLATE__?.enabled === true;
        },

        get lbPlotButtons() {
            return plotFaceButtons({
                translateEnabled: this.lbPlotTranslateEnabled,
                hasOriginal: this._lbPlotView.hasOriginal,
                showing: this._lbPlotView.showing,
            });
        },

        lbPlotShowButton() {
            return this.currentLightboxVideo?.has_nfo === true
                && !!this.currentLightboxVideo?.path;
        },

        lbPlotToggle() {
            if (this.lbPlotOpen) {
                this.lbPlotClose();
                return;
            }
            this.lbPlotOpen = true;
            return this._lbPlotLoad();
        },

        lbPlotClose() {
            this._lbPlotReset();
        },

        _lbPlotReset() {
            this._lbPlotGen += 1;
            if (this._lbPlotAbort) {
                this._lbPlotAbort.abort();
                this._lbPlotAbort = null;
            }
            this.lbPlotOpen = false;
            this._lbPlotView = emptyPlotView();
        },

        async _lbPlotLoad() {
            const path = this.currentLightboxVideo?.path;
            if (!path) return;
            const gen = ++this._lbPlotGen;
            if (this._lbPlotAbort) this._lbPlotAbort.abort();
            const controller = new AbortController();
            this._lbPlotAbort = controller;
            const pendingView = emptyPlotView();
            pendingView.path = path;
            pendingView.loading = true;
            this._lbPlotView = pendingView;

            let ok = false;
            let data = null;
            try {
                const response = await fetch(
                    `/api/showcase/video/plot?file_path=${encodeURIComponent(path)}`,
                    { signal: controller.signal },
                );
                ok = response.ok;
                data = await response.json();
            } catch (error) {
                if (controller.signal.aborted) return;
                ok = false;
                data = null;
            } finally {
                if (this._lbPlotAbort === controller) {
                    this._lbPlotAbort = null;
                }
            }
            // Alpine wraps assigned objects in a reactive Proxy.  The local
            // object is therefore not identity-equal to this._lbPlotView.
            // Use the generation plus the path as the stable request key.
            if (
                gen !== this._lbPlotGen
                || !this.lbPlotOpen
                || this._lbPlotView.path !== path
            ) return;
            // `_lbPlotView` is Alpine's reactive proxy after assignment. Mutate
            // the proxy, not the raw object used to seed the request, so the
            // skeleton is replaced as soon as the response arrives.
            applyPlotLoadResult(this._lbPlotView, ok, data);
        },

        lbPlotToggleOriginal() {
            const view = this._lbPlotView;
            if (!view.hasOriginal) return;
            view.showing = view.showing === 'plot' ? 'original' : 'plot';
        },

        async lbPlotTranslate() {
            const video = this.currentLightboxVideo;
            const view = this._lbPlotView;
            if (!video?.path || view.loading || view.error || !view.plot) return;
            const path = video.path;
            const generation = this._lbPlotGen;
            if (this._lbPlotInFlight[path]) return;

            this._lbPlotInFlight[path] = true;
            const sourceText = view.showing === 'original'
                ? (view.original || '')
                : view.plot;
            const isRetranslate = view.showing === 'original';
            const snapshot = { plot: view.plot, original: view.original || '' };
            try {
                let translationData;
                try {
                    const response = await fetch('/api/translate', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            text: sourceText,
                            mode: 'translate',
                            actors: (video.actresses || '')
                                .split(',')
                                .map((actor) => actor.trim())
                                .filter(Boolean),
                            number: video.number || '',
                        }),
                    });
                    if (!response.ok) throw new Error(`HTTP ${response.status}`);
                    translationData = await response.json();
                } catch (error) {
                    this.showToast(
                        window.t(translateFailureToastKey(undefined)),
                        'error',
                    );
                    return;
                }
                if (translationData.skipped === true) {
                    this.showToast(
                        window.t('showcase.lightbox.plot_already_target'),
                        'info',
                    );
                    return;
                }
                if (
                    translationData.success !== true
                    || typeof translationData.result !== 'string'
                    || !translationData.result
                ) {
                    this.showToast(
                        window.t(translateFailureToastKey(translationData.reason)),
                        'error',
                    );
                    return;
                }
                const translated = translationData.result;
                if (sameAfterNormalize(translated, sourceText)) {
                    this.showToast(
                        window.t('showcase.lightbox.plot_already_target'),
                        'info',
                    );
                    return;
                }

                const body = { file_path: path, plot: translated };
                if (isRetranslate) body.original_plot = snapshot.original;
                let data;
                try {
                    const response = await fetch('/api/showcase/video/plot', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(body),
                    });
                    if (!response.ok) throw new Error(`HTTP ${response.status}`);
                    data = await response.json();
                } catch (error) {
                    this.showToast(
                        window.t('showcase.lightbox.plot_write_failed'),
                        'error',
                    );
                    return;
                }
                if (data.success !== true) {
                    const key = data.error === 'no_nfo'
                        ? 'plot_no_nfo'
                        : 'plot_write_failed';
                    this.showToast(window.t(`showcase.lightbox.${key}`), 'error');
                    return;
                }

                if (
                    generation === this._lbPlotGen
                    && this.lbPlotOpen
                    && this._lbPlotView.path === path
                ) {
                    this._lbPlotApply(this._lbPlotView, data);
                }
                this.showToast(
                    window.t('showcase.lightbox.plot_translate_done'),
                    'success',
                    UNDO_TOAST_MS,
                    {
                        label: window.t('showcase.lightbox.plot_translate_undo'),
                        onClick: () => this._lbPlotUndo(path, snapshot),
                    },
                );
            } finally {
                delete this._lbPlotInFlight[path];
            }
        },

        _lbPlotApply(view, data) {
            view.plot = data.plot || '';
            view.original = data.original_plot || '';
            view.hasOriginal = !!data.has_original;
            view.showing = 'plot';
            view.loading = false;
            view.error = false;
        },

        async _lbPlotUndo(path, snapshot) {
            if (this._lbPlotInFlight[path]) return;
            this._lbPlotInFlight[path] = true;
            try {
                const response = await fetch('/api/showcase/video/plot', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        file_path: path,
                        plot: snapshot.plot,
                        original_plot: snapshot.original,
                    }),
                });
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                const data = await response.json();
                if (data.success !== true) throw new Error(data.error || 'API failed');
                if (this._lbPlotView.path === path && this.lbPlotOpen) {
                    this._lbPlotApply(this._lbPlotView, data);
                }
                this.showToast(
                    window.t('showcase.lightbox.plot_translate_undone'),
                    'success',
                );
            } catch (error) {
                this.showToast(
                    window.t('showcase.lightbox.plot_write_failed'),
                    'error',
                );
            } finally {
                delete this._lbPlotInFlight[path];
            }
        },
    };
}
