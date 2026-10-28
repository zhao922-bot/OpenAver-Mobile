/**
 * GridMotion — 跨頁面共用的網格進場／篩選 Flip 動畫
 *
 * 從 showcase/animations.js 原封搬出的頁面無關實作：
 *   - playEntry(gridEl, params)
 *   - playFlipFilter(gridEl, state, params)
 *   - captureFlipState(gridEl)
 *
 * 暴露 window.GridMotion；showcase/animations.js 以委派薄殼轉發。
 */
(function () {
    'use strict';

    /**
     * 判斷是否應跳過動畫（Reduced Motion 降級）
     * @returns {boolean}
     */
    function shouldSkip() {
        return !!(window.OpenAver?.prefersReducedMotion);
    }

    document.addEventListener('DOMContentLoaded', function () {
        if (typeof gsap !== 'undefined' && typeof Flip !== 'undefined') {
            gsap.registerPlugin(Flip);
        }
    });

    var GridMotion = {
        playEntry: function (gridEl, params) {
            params = params || {};

            // null guard
            if (!gridEl) return null;

            // GSAP guard（CDN 故障降級）
            if (typeof gsap === 'undefined') return null;

            var cards = gridEl.querySelectorAll('.av-card-preview, .actress-card');
            if (!cards.length) return null;

            // C4: 清除舊動畫
            gsap.killTweensOf(cards);

            // Reduced Motion 降級：瞬間顯示
            if (shouldSkip()) {
                gsap.set(cards, { opacity: 1, y: 0, scale: 1 });
                return null;
            }

            var dur = params.duration || OpenAver.motion.DURATION.emphasis;
            var staggerVal = params.stagger || { amount: OpenAver.motion.WALL_MOTION.ENTRY_STAGGER_AMOUNT, from: OpenAver.motion.WALL_MOTION.STAGGER_ORIGIN, grid: 'auto' };
            var ease = params.easing || 'fluent-decel';

            // Viewport 分流：fold 以下卡片瞬間顯示
            var viewportH = window.innerHeight;
            var visible = [];
            var offscreen = [];
            Array.from(cards).forEach(function (card) {
                var rect = card.getBoundingClientRect();
                // 沒有版面框的元素在畫面上看不到自己在動，而且會污染 grid:'auto' 的行列推導
                if (rect.width === 0 && rect.height === 0) {
                    offscreen.push(card);
                } else if (rect.top < viewportH) {
                    visible.push(card);
                } else {
                    offscreen.push(card);
                }
            });

            if (offscreen.length) {
                gsap.set(offscreen, { clearProps: 'transform,opacity' });
            }

            if (!visible.length) return null;

            // 設定初始狀態
            var fromVars = { opacity: 0, y: 20 };
            gsap.set(visible, fromVars);

            // C21: cascade 進場期間 hover 不可搶 transform 控制權
            visible.forEach(function (c) { c.classList.add('gsap-animating'); });

            var tl = gsap.timeline({
                id: 'showcaseEntry',
                onComplete: function () {
                    visible.forEach(function (c) { c.classList.remove('gsap-animating'); });
                    gsap.set(visible, { clearProps: 'transform,opacity' });
                },
                onInterrupt: function () {
                    visible.forEach(function (c) { c.classList.remove('gsap-animating'); });
                }
            });
            tl.to(visible, { opacity: 1, y: 0, duration: dur, ease: ease, stagger: staggerVal });

            return tl;
        },

        /**
         * B8: 篩選進出場 Flip 動畫
         * @param {Element} gridEl - .showcase-grid 容器
         * @param {Object} state - Flip 狀態快照
         * @param {Object} params - 動畫參數
         * @returns {null}
         */
        playFlipFilter: function (gridEl, state, params) {
            params = params || {};

            // null guard
            if (!gridEl || !state) return null;

            // Flip guard
            if (typeof Flip === 'undefined' || typeof gsap === 'undefined') return null;

            var cards = gridEl.querySelectorAll('.av-card-preview, .actress-card');
            if (!cards.length) return null;

            // Reduced Motion 降級：Alpine 已完成 DOM 更新，不需額外處理
            if (shouldSkip()) return null;

            // C18: 中斷進行中的 Flip 動畫
            Flip.killFlipsOf(cards);

            var dur = params.duration || OpenAver.motion.DURATION.medium;

            // Flip.from — 含 onEnter/onLeave 進出場回調
            return Flip.from(state, {
                duration: dur,
                ease: 'fluent',
                absolute: true,
                prune: true,
                simple: true,
                onEnter: function (els) {
                    // B18: 大量新卡片同時進場 → 純 fade + stagger（無 scale，降低視覺混亂）
                    if (els.length > 10) {
                        return gsap.fromTo(els,
                            { opacity: 0 },
                            { opacity: 1, duration: dur * 0.6, stagger: { amount: OpenAver.motion.WALL_MOTION.FILTER_ENTER_STAGGER_AMOUNT, from: OpenAver.motion.WALL_MOTION.STAGGER_ORIGIN, grid: 'auto' }, ease: 'fluent-decel' }
                        );
                    }
                    // 預設：scale + fade（少量卡片進場時效果好）
                    return gsap.fromTo(els,
                        { opacity: 0, scale: 0.85 },
                        { opacity: 1, scale: 1, duration: dur * 0.8, ease: 'fluent-decel' }
                    );
                },
                onLeave: function (els) {
                    return gsap.to(els, { opacity: 0, scale: 0.85, duration: dur * 0.6, ease: 'fluent-accel' });
                },
                onComplete: function () {
                    gsap.set(cards, { clearProps: 'transform' });
                    gridEl.classList.remove('flip-guard');
                }
            });
        },

        /**
         * B7/B8: 捕獲 Flip 狀態快照
         * @param {Element} gridEl - .showcase-grid 容器
         * @returns {Object|null} Flip state 物件
         */
        captureFlipState: function (gridEl) {
            // null guard
            if (!gridEl) return null;

            // Flip guard
            if (typeof Flip === 'undefined') return null;

            var cards = gridEl.querySelectorAll('.av-card-preview');
            if (!cards.length) return null;

            return Flip.getState(cards, { props: 'opacity', simple: true });
        },

    };

    window.GridMotion = GridMotion;
})();
