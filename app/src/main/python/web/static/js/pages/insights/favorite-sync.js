// TASK-177-T3a: 分析頁收藏回應分類／快照條目／不可變合併的純函式（無 this、無 singleton、不 import）。

function isActressObject(body) {
    return !!body && typeof body === 'object' && !Array.isArray(body)
        && !!body.actress && typeof body.actress === 'object' && !Array.isArray(body.actress);
}

// 先看 status、不看 body.success（409 body 無 success）。回 'added'|'already'|'not_found'|'failed'。
export function classifyFavoriteResponse(status, body) {
    if (status === 200 && isActressObject(body)) return 'added';
    if (status === 409 && isActressObject(body)) return 'already';
    if (status === 404) return 'not_found';
    return 'failed';
}

// hasPhoto 取 photo_url（409 body 沒有 photo_downloaded）。
export function buildFavoriteEntry(actress) {
    return {
        birth: actress.birth || null,
        photoName: actress.name,
        hasPhoto: !!actress.photo_url,
        auto_focal: actress.auto_focal ?? null,
        crop_mode: actress.crop_mode ?? null,
    };
}

// 回新物件身分（ganttView 快取鍵比 favs ===）；不改傳入的 favs。
export function mergeFavorite(favs, name, entry) {
    favs = favs || {};
    return { ...favs, [name]: entry };
}
