// maker-latest.js — 搜尋頁空狀態片商膠囊列（TASK-173-T11，CD-173-1／-3／-4）
// mergeState 分片，**不得定義 init()**（FE-ALPINE-05）；所有 key 含 maker（FE-ALPINE-11）。
// 整排隱藏條件只有 makerCapsules.length > 0：關閉／失敗／無人達標／全被隱藏一律化約成 []。

import { rankMakerCapsules } from '../maker-capsules.js';

export function searchStateMakerLatest() {
    return {
        makerCapsules: [],
        _makerRows: [],
        _makerHiddenKeys: [],

        async loadMakerCapsules() {
            let rows = [];
            let hidden = [];
            try {
                const res = await fetch('/api/search/maker-capsules');
                const data = await res.json();
                if (data && data.success === true && data.maker_search_enabled !== false) {
                    rows = Array.isArray(data.makers) ? data.makers : [];
                    hidden = Array.isArray(data.hidden_keys) ? data.hidden_keys : [];
                }
            } catch (e) {
                console.error('loadMakerCapsules failed:', e);
            }
            this._makerRows = rows;
            this._makerHiddenKeys = [...new Set([...this._makerHiddenKeys, ...hidden])];
            this.rebuildMakerCapsules();
        },

        rebuildMakerCapsules() {
            this.makerCapsules = rankMakerCapsules(this._makerRows, this._makerHiddenKeys, { min: 5, max: 5 });
        },

        startMakerSearch(capsule) {
            return this.doSearch('', { maker: capsule });
        },

        hideMakerCapsule(key) {
            if (!this._makerHiddenKeys.includes(key)) this._makerHiddenKeys = [...this._makerHiddenKeys, key];
            this.rebuildMakerCapsules();
        },
    };
}
