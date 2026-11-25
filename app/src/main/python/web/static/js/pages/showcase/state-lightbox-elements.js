const fields = ['cover', 'plot', 'samples', 'tags'];

async function readResults(response, onEvent) {
    const reader = response.body?.getReader();
    const interrupted = () => new Error(window.t('showcase.elements.interrupted'));
    if (!reader) throw interrupted();
    const decoder = new TextDecoder();
    let buffer = '';
    try {
        while (true) {
            const {value, done} = await reader.read();
            buffer += decoder.decode(value, {stream: !done});
            const lines = buffer.split('\n');
            buffer = done ? '' : lines.pop();
            for (const line of lines) {
                if (!line.startsWith('data:')) continue;
                const event = JSON.parse(line.slice(5));
                if (event.type === 'error') throw new Error(event.message || window.t('scanner.task.failed'));
                onEvent(event);
                if (event.type === 'done') return;
            }
            if (done) throw interrupted();
        }
    } finally {
        reader.releaseLock();
    }
}

export function stateLightboxElements() {
    let controller = null;
    let disposed = false;
    return {
        videoElementsOpen: false,
        videoElementsLoading: false,
        videoElementsRunning: false,
        videoElementsSubmitted: false,
        videoElementsPath: '',
        elementOptions: {},
        elementSelection: {},
        videoElementsStatus: '',
        videoElementResults: [],

        get selectedVideoElements() {
            return Object.fromEntries(fields.filter(field => this.elementSelection[field] &&
                this.elementOptions[field]?.some(option => option.id === this.elementSelection[field])
            ).map(field => [field, this.elementSelection[field]]));
        },

        async openVideoElements() {
            const video = this.currentLightboxVideo;
            if (!this.lightboxOpen || !video?.path || this.videoElementsOpen) return;
            this.videoElementsPath = video.path;
            this.elementOptions = {};
            this.elementSelection = {cover: '', plot: '', samples: '', tags: ''};
            this.videoElementsStatus = '';
            this.videoElementResults = [];
            this.videoElementsSubmitted = false;
            this.videoElementsOpen = true;
            this.videoElementsLoading = true;
            this.videoElementsRunning = false;
            const request = controller = new AbortController();
            this.$refs.videoElementsDialog.showModal();
            try {
                const response = await fetch('/api/gallery/backfill-elements/sources', {signal: request.signal});
                if (!response.ok) throw new Error();
                const data = await response.json();
                if (!data.success || !data.sources) throw new Error();
                if (controller !== request) return;
                this.elementOptions = Object.fromEntries(fields.map(field => [field,
                    Array.isArray(data.sources[field]) ? data.sources[field] : [],
                ]));
                if (!Object.values(this.elementOptions).some(options => options.length)) {
                    this.videoElementsStatus = window.t('scanner.sources.empty');
                }
            } catch {
                if (controller === request) this.videoElementsStatus = window.t('scanner.sources.load_failed');
            } finally {
                if (controller === request) this.videoElementsLoading = false;
            }
        },

        closeVideoElements() {
            controller?.abort();
            controller = null;
            this.videoElementsOpen = false;
            if (this.$refs.videoElementsDialog?.open) this.$refs.videoElementsDialog.close();
        },

        cancelVideoElements() {
            controller?.abort();
        },

        disposeVideoElements() {
            disposed = true;
            this.closeVideoElements();
        },

        async runVideoElements() {
            const video = this.currentLightboxVideo;
            const path = this.videoElementsPath;
            const sources = this.selectedVideoElements;
            if (!this.videoElementsOpen || this.videoElementsLoading || this.videoElementsSubmitted ||
                    !this.lightboxOpen || !path || video?.path !== path || !Object.keys(sources).length) return;
            const request = controller = new AbortController();
            this.videoElementsRunning = true;
            this.videoElementsSubmitted = true;
            this.videoElementsStatus = '';
            let accepted = false;
            try {
                const response = await fetch('/api/gallery/rescrape-elements', {
                    method: 'POST', headers: {'Content-Type': 'application/json', Accept: 'text/event-stream'},
                    body: JSON.stringify({file_path: path, sources}), signal: request.signal,
                });
                if (!response.ok) {
                    const error = await response.json().catch(() => ({}));
                    throw new Error(error.message || (typeof error.detail === 'string' && error.detail) || `HTTP ${response.status}`);
                }
                accepted = true;
                await readResults(response, event => {
                    if (controller !== request) return;
                    if (event.type === 'progress') this.videoElementsStatus = event.message || event.status || '';
                    if (event.type === 'result-item' && sources[event.element]) {
                        const message = event.success && !event.skipped ? window.t('showcase.elements.updated') :
                            event.error || event.message || window.t(event.skipped ? 'scanner.elements.skip' : 'scanner.task.failed');
                        this.videoElementResults.push({field: event.element, message});
                    }
                    if (event.type === 'done') this.videoElementsStatus = event.cancelled
                        ? window.t('scanner.task.cancelled_log')
                        : window.t('showcase.elements.summary', event.summary || {});
                });
            } catch (error) {
                if (controller === request) this.videoElementsStatus = request.signal.aborted
                    ? window.t('scanner.task.cancelled_log') : error.message;
            } finally {
                // A disconnected stream can already have committed an earlier field.
                if (!disposed && (accepted || request.signal.aborted)) {
                    const refreshed = await this.refreshVideoData(video);
                    if (refreshed && sources.plot && this.lightboxOpen && this.currentLightboxVideo?.path === path) {
                        if (this.lbPlotOpen || this._lbPlotInline) this._lbPlotLoad();
                        else this._lbPlotAutoLoad();
                    }
                    if (!refreshed && controller === request) this.videoElementsStatus += ' · ' + window.t('runtime.api.video_data_load_failed');
                }
                if (controller === request) this.videoElementsRunning = false;
            }
        },
    };
}
