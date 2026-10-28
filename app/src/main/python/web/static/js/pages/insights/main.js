import { libraryInsightsState } from '@/insights/state.js';

window.libraryInsightsState = libraryInsightsState;

document.addEventListener('alpine:init', () => {
    Alpine.data('libraryInsights', window.libraryInsightsState);
});
