/**
 * actress-release-age.js — 女優發行當天年齡計算與別名解析純函式模組（CD-149b-4/5）。
 * 零 import、零 Alpine 依賴。
 */

export const LONG_FORM_MIN_DURATION_MINUTES = 239;

const DATE_REGEX = /^\d{4}-\d{2}-\d{2}$/;

// 顯式月份天數表 + 閏年判斷——不用 new Date()/Date.UTC() 做日曆合法性檢查
// （Date.UTC(y, ...) 對 0-99 的年份會靜默映射成 1900+y，是另一個同形狀的坑）。
const DAYS_IN_MONTH = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];

function isLeapYear(y) {
    return (y % 4 === 0 && y % 100 !== 0) || y % 400 === 0;
}

function isValidCalendarDate(y, m, d) {
    // 對齊 Python datetime 的 MINYEAR=1／MAXYEAR=9999（strptime 對超出此範圍會拋 ValueError）。
    if (y < 1 || y > 9999) return false;
    if (m < 1 || m > 12) return false;
    if (d < 1) return false;
    const maxDay = (m === 2 && isLeapYear(y)) ? 29 : DAYS_IN_MONTH[m - 1];
    return d <= maxDay;
}

/**
 * 計算指定日期 (dateISO) 時的滿歲年齡。
 * 兩個參數皆必須為完整 YYYY-MM-DD（/^\d{4}-\d{2}-\d{2}$/）且日曆上真的存在，否則回傳 null。
 */
export function computeAgeAtDate(birthISO, dateISO) {
    if (typeof birthISO !== 'string' || !DATE_REGEX.test(birthISO)) return null;
    if (typeof dateISO !== 'string' || !DATE_REGEX.test(dateISO)) return null;

    const birthParts = birthISO.split('-');
    const dateParts = dateISO.split('-');
    const birthY = parseInt(birthParts[0], 10);
    const birthM = parseInt(birthParts[1], 10);
    const birthD = parseInt(birthParts[2], 10);
    const dateY = parseInt(dateParts[0], 10);
    const dateM = parseInt(dateParts[1], 10);
    const dateD = parseInt(dateParts[2], 10);

    if (!isValidCalendarDate(birthY, birthM, birthD)) return null;
    if (!isValidCalendarDate(dateY, dateM, dateD)) return null;

    let age = dateY - birthY;
    if (dateM < birthM || (dateM === birthM && dateD < birthD)) age -= 1;
    return age;
}

/**
 * 計算影片發行時女優年齡。
 * 片長 >= 239 分鐘視為合輯長片，不顯示年齡（回傳 null）。
 */
export function computeActressAgeForVideo(params) {
    if (!params) return null;
    const { birth, releaseDate, durationMinutes } = params;
    if (durationMinutes != null && durationMinutes >= LONG_FORM_MIN_DURATION_MINUTES) return null;
    return computeAgeAtDate(birth, releaseDate);
}

/**
 * 依女優名稱與別名表查找女優並計算影片發行時年齡。
 * 別名比對一律使用小寫 key。
 */
export function resolveFavoriteActressAge(rawActressName, video, actresses, nameToGroup) {
    if (!video || !Array.isArray(actresses)) return null;
    const key = (rawActressName || '').trim().toLowerCase();
    const group = (nameToGroup && nameToGroup[key]) || [(rawActressName || '').trim()];
    const found = actresses.find(a => a && group.indexOf(a.name) !== -1);
    if (!found) return null;
    return computeActressAgeForVideo({
        birth: found.birth,
        releaseDate: video.release_date,
        durationMinutes: video.duration,
    });
}

export function computeActorAgesMap(video, actresses, nameToGroup) {
    var ages = {};
    if (!video || !video.actresses) return ages;
    var names = video.actresses.split(',').map(function (n) { return n.trim(); }).filter(Boolean);
    for (var i = 0; i < names.length; i++) {
        var age = resolveFavoriteActressAge(names[i], video, actresses, nameToGroup);
        if (age != null) ages[names[i]] = age;
    }
    return ages;
}

export function singleActorAge(video) {
    if (!video || !video.actresses) return null;
    var names = video.actresses.split(',').map(function (n) { return n.trim(); }).filter(Boolean);
    if (names.length !== 1) return null;
    var age = video._cardActorAges && video._cardActorAges[names[0]];
    return age != null ? age : null;
}
