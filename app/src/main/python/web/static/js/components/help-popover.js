/**
 * helpPopover — 「? 說明浮層」共用元件（131b-T4）
 *
 * 掛在**既有的** .popover-anchor / wrapper 元素上，不新增任何 DOM
 * （新增一層 <div> 會動到 position: relative 的定位鏈與 flex 佈局）。
 *
 * 這支是 CLAUDE.md「新前端功能：獨立元件 vs mergeState 分片」③ 的可抄樣板：
 * 觸發鈕與它自己的畫面同在一個子樹（條件 A）、外面沒有任何人需要知道它開沒開（條件 B）、
 * 不跨 x-if / x-for 邊界（條件 C）——三條全過才做成獨立元件。
 */
export function helpPopover() {
    return {
        open: false,
        toggle() { this.open = !this.open; },
        close() { this.open = false; },
    };
}

document.addEventListener('alpine:init', () => {
    Alpine.data('helpPopover', helpPopover);
});
