import { stateScan }  from '@/scanner/state-scan.js';
import { stateBatch } from '@/scanner/state-batch.js';
import { stateAlias } from '@/scanner/state-alias.js';
import { stateTagAlias } from '@/scanner/state-tag-alias.js';
import { browseDirState } from '@/shared/state-browse-dir.js';
import { toastState } from '@/shared/state-toast.js';
import { mergeState } from '@/shared/merge-state.js';

document.addEventListener('alpine:init', () => {
    Alpine.data('scanner', () => mergeState(
        stateScan(),
        stateBatch(),
        stateAlias(),
        stateTagAlias(),
        browseDirState(),
        toastState(),
    ));
});
