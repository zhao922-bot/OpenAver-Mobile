/**
 * claude-model-pick.js — Claude 模型自動選取純邏輯（無 DOM、無 Alpine、無 window）
 *
 * CD-170-8: 空／等於寫死預設／不在清單 → 最新 Haiku（或 models[0]）；
 * 使用者已選且仍在清單 → 維持。
 */

export function pickClaudeModel(current, models, latestHaiku, defaultModel) {
    if (!Array.isArray(models) || models.length === 0) return current;
    if (!current || current === defaultModel || !models.includes(current)) {
        return latestHaiku || models[0];
    }
    return current;
}
