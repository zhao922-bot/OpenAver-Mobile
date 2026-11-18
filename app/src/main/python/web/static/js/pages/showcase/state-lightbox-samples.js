/**
 * state-lightbox-samples.js — Showcase ESM（149a-T1）
 *
 * 樣本劇照廊（Sample Gallery）：燈箱內附加的縮圖劇照集，開／關／翻頁／跳號／觸控滑。
 * 從 state-lightbox.js 拆出，逐字搬移，見 plan-149a.md CD-149a-1／CD-149a-2。
 */

import { detectSwipe } from '@/shared/swipe.js';

export function stateLightboxSamples() {
    return {
        // Sample Gallery 狀態
        sampleGalleryOpen: false,
        sampleGalleryImages: [],
        sampleGalleryIndex: 0,
        _sgTouchStartX: null,
        _sgTouchStartY: null,
        _sgAnimating: false,            // guard
        _sgGeneration: 0,               // stale callback 防護

        // ==================== Sample Gallery Methods ====================

        _scrollActiveSampleThumbIntoView() {
            const syncScroll = () => {
                const strip = document.querySelector('.sample-gallery .sg-thumbs');
                if (!strip) return;
                const btns = strip.querySelectorAll('.sg-thumb-btn');
                const active = btns[this.sampleGalleryIndex] || strip.querySelector('.sg-thumb-active');
                if (!active) return;
                const targetLeft = active.offsetLeft - (strip.clientWidth - active.clientWidth) / 2;
                strip.scrollLeft = Math.max(0, Math.round(targetLeft));
            };
            syncScroll();
            if (typeof this.$nextTick === 'function') {
                this.$nextTick(() => {
                    syncScroll();
                    if (typeof requestAnimationFrame === 'function') {
                        requestAnimationFrame(syncScroll);
                    }
                });
            }
        },

        openSampleGallery(images, startIdx) {
            if (!images || images.length === 0) return;
            this.sampleGalleryImages = images;
            this.sampleGalleryIndex = startIdx || 0;
            this._sgGeneration++;
            this.sampleGalleryOpen = true;
            this._scrollActiveSampleThumbIntoView();
        },

        closeSampleGallery() {
            this.sampleGalleryOpen = false;
            // 不影響 lightboxOpen 狀態（lightbox 維持開啟）
        },

        prevSampleGallery() {
            if (this.sampleGalleryIndex <= 0) return;
            var prevIdx = this.sampleGalleryIndex - 1;
            this._sgGeneration++;
            var gen = this._sgGeneration;
            this.sampleGalleryIndex = prevIdx;
            this._scrollActiveSampleThumbIntoView();
            // state-first，$nextTick 後播動畫
            var self = this;
            this.$nextTick(() => {
                if (self._sgGeneration !== gen) return;
                var imgEl = document.querySelector('.sg-main-img');
                if (imgEl) {
                    window.ShowcaseAnimations?.playSampleGallerySwitch?.(imgEl, 'prev', {});
                }
            });
        },

        nextSampleGallery() {
            if (this.sampleGalleryIndex >= this.sampleGalleryImages.length - 1) return;
            var nextIdx = this.sampleGalleryIndex + 1;
            this._sgGeneration++;
            var gen = this._sgGeneration;
            this.sampleGalleryIndex = nextIdx;
            this._scrollActiveSampleThumbIntoView();
            // state-first，$nextTick 後播動畫
            var self = this;
            this.$nextTick(() => {
                if (self._sgGeneration !== gen) return;
                var imgEl = document.querySelector('.sg-main-img');
                if (imgEl) {
                    window.ShowcaseAnimations?.playSampleGallerySwitch?.(imgEl, 'next', {});
                }
            });
        },

        jumpSampleGallery(idx) {
            if (idx === this.sampleGalleryIndex) return;
            var direction = idx > this.sampleGalleryIndex ? 'next' : 'prev';
            this._sgGeneration++;
            var gen = this._sgGeneration;
            this.sampleGalleryIndex = idx;
            this._scrollActiveSampleThumbIntoView();
            // state-first，$nextTick 後播動畫
            var self = this;
            this.$nextTick(() => {
                if (self._sgGeneration !== gen) return;
                var imgEl = document.querySelector('.sg-main-img');
                if (imgEl) {
                    window.ShowcaseAnimations?.playSampleGallerySwitch?.(imgEl, direction, {});
                }
            });
        },

        _sgTouchStart(e) {
            if (!e.touches || e.touches.length !== 1) {
                this._sgTouchStartX = null;
                this._sgTouchStartY = null;
                return;
            }
            this._sgTouchStartX = e.touches[0].clientX;
            this._sgTouchStartY = e.touches[0].clientY ?? null;
        },

        _sgTouchEnd(e) {
            if (this._sgTouchStartX === null) return;
            var endX = e.changedTouches && e.changedTouches.length > 0
                ? e.changedTouches[0].clientX
                : null;
            var endY = e.changedTouches && e.changedTouches.length > 0
                ? e.changedTouches[0].clientY
                : null;
            if (endX === null) {
                this._sgTouchStartX = null;
                this._sgTouchStartY = null;
                return;
            }
            var startY = this._sgTouchStartY !== null ? this._sgTouchStartY : (endY ?? 0);
            var finishY = endY !== null && endY !== undefined ? endY : startY;
            var dir = detectSwipe(this._sgTouchStartX, startY, endX, finishY, 50);
            this._sgTouchStartX = null;
            this._sgTouchStartY = null;
            if (dir === 'left') {
                this.nextSampleGallery(); // swipe left → next
            } else if (dir === 'right') {
                this.prevSampleGallery(); // swipe right → prev
            }
        },

        // ==================== End Sample Gallery Methods ====================
    };
}
