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
    const partsNav = document.getElementById('oa-player-parts');
    let partTokens = [];
    try {
        const parsedTokens = JSON.parse(video.dataset.partTokens ?? '[]');
        if (Array.isArray(parsedTokens)) partTokens = parsedTokens;
    } catch {
        partTokens = [];
    }
    const parsedStartIndex = Number.parseInt(video.dataset.startIndex ?? '0', 10);
    let currentIndex = (
        Number.isInteger(parsedStartIndex)
        && parsedStartIndex >= 0
        && parsedStartIndex < parts.length
    ) ? parsedStartIndex : 0;

    function partLabel(index) {
        const token = partTokens[index];
        return typeof token === 'string' && token.trim()
            ? token.trim()
            : `Part ${index + 1}`;
    }

    function renderLabel() {
        if (!labelEl) return;
        labelEl.textContent = labelTemplate
            .replace('{current}', String(currentIndex + 1))
            .replace('{total}', String(parts.length));
    }

    function renderParts() {
        if (!partsNav) return;
        if (!partsNav.childElementCount) {
            parts.forEach((_, index) => {
                const button = document.createElement('button');
                button.type = 'button';
                button.className = 'oa-player-part';
                button.textContent = partLabel(index);
                button.addEventListener('click', () => selectPart(index));
                partsNav.appendChild(button);
            });
        }
        Array.from(partsNav.children).forEach((button, index) => {
            button.setAttribute(
                'aria-current',
                index === currentIndex ? 'true' : 'false'
            );
        });
    }

    function clearErrorHints() {
        video.style.display = '';
        document.getElementById('video-error-hint-network').style.display = 'none';
        document.getElementById('video-error-hint-format').style.display = 'none';
    }

    function updateLocation() {
        try {
            const url = new URL(window.location.href);
            url.searchParams.set('part', String(currentIndex + 1));
            window.history.replaceState(null, '', url);
        } catch {
            // Playback must not depend on History API availability.
        }
    }

    function selectPart(index, { autoplay = true } = {}) {
        if (!Number.isInteger(index) || index < 0 || index >= parts.length) return;
        currentIndex = index;
        clearErrorHints();
        video.src = parts[currentIndex];
        video.load();
        if (autoplay) {
            const p = video.play();
            if (p && typeof p.catch === 'function') p.catch(() => {});
        }
        renderLabel();
        renderParts();
        updateLocation();
    }

    video.addEventListener('ended', () => {
        const nextIndex = currentIndex + 1;
        if (nextIndex >= parts.length) return;  // 最後一段播完，停止
        selectPart(nextIndex);
    });

    renderLabel();  // 初始「第 1／N 段」
    renderParts();
});
