/**
 * AvatarFly — insights 頭像飛入焦點格（document-relative ghost 補間）
 *
 * 只負責補間 top/left/width/height 與呼叫 opts.onComplete。
 * 不判斷有沒有照片、不決定樣式、不管理 _activeAvatarGhost——那些是呼叫端責任。
 *
 * 使用方式：
 *   window.AvatarFly.playFlyToFocus(ghost, targetDocRect, opts)
 */

function playFlyToFocus(ghost, targetDocRect, opts) {
    opts = opts || {};
    var done = function () {
        if (typeof opts.onComplete === 'function') opts.onComplete();
    };
    if (!ghost || !targetDocRect) {
        done();
        return null;
    }
    if (typeof gsap === 'undefined') {
        done();
        return null;
    }

    gsap.killTweensOf(ghost);
    var endTop = targetDocRect.top;
    var endLeft = targetDocRect.left;
    var endW = targetDocRect.width;
    var endH = targetDocRect.height;
    return gsap.to(ghost, {
        top: endTop,
        left: endLeft,
        width: endW,
        height: endH,
        duration: 0.4,
        ease: 'fluent',
        onComplete: function () {
            // 收尾對齊到精確終值，消掉補間最後一幀的亞像素殘差
            gsap.set(ghost, {
                top: endTop,
                left: endLeft,
                width: endW,
                height: endH,
            });
            done();
        },
    });
}

var AvatarFly = {
    playFlyToFocus: playFlyToFocus,
};

window.AvatarFly = AvatarFly;
export { AvatarFly };
