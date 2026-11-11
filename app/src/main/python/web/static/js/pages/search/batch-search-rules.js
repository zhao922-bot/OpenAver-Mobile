/**
 * Pure rules for the search batch workflow.
 */

export function isFileSearching(activePaths, path) {
    return Array.isArray(activePaths) && activePaths.includes(path);
}

export function isDetailEmpty(file) {
    return !file || !file.number
        || !(file.searchResults && file.searchResults.length > 0);
}

export function shouldAutoJump({ armed, anchorPath, currentPath }) {
    return armed && currentPath === anchorPath;
}
