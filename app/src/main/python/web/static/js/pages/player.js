document.addEventListener('DOMContentLoaded', () => {
    const video = document.getElementById('oa-player');
    if (!video) return;
    const partsRaw = video.dataset.parts;
    if (!partsRaw) return;

    let parts;
    try {
        parts = JSON.parse(partsRaw);
    } catch {
        return;
    }
    if (!Array.isArray(parts) || parts.length < 2) return;

    const labelTemplate = video.dataset.partLabelTemplate ?? '';
    const labelEl = document.getElementById('oa-player-progress');
    let currentIndex = 0;  // FE-JS-01：0 是合法索引，下面全用 ?? / === undefined，不用 ||

    function renderLabel() {
        if (!labelEl) return;
        labelEl.textContent = labelTemplate
            .replace('{current}', String(currentIndex + 1))
            .replace('{total}', String(parts.length));
    }

    video.addEventListener('ended', () => {
        const nextIndex = currentIndex + 1;
        if (nextIndex >= parts.length) return;  // 最後一段播完，停止
        currentIndex = nextIndex;
        video.src = parts[currentIndex];
        video.load();
        const p = video.play();
        if (p && typeof p.catch === 'function') p.catch(() => {});
        renderLabel();
    });

    renderLabel();  // 初始「第 1／N 段」
});
