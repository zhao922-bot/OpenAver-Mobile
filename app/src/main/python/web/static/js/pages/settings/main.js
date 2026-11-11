import { stateConfig }       from '@/settings/state-config.js?v=18005-1';
import { stateProviders }    from '@/settings/state-providers.js';
import { stateUI }           from '@/settings/state-ui.js';
import { stateSourceProbe }  from '@/settings/state-source-probe.js';
import { customSources }     from '@/settings/state-custom-sources.js';
import { stateDatabase }     from '@/settings/state-database.js';
import { aiServicesCard }    from '@/settings/ai-services-card.js';
import { aiSimilarPanel }    from '@/settings/ai-similar-panel.js';
import { aiFacesPanel }      from '@/settings/ai-faces-panel.js';
import { browseDirState }    from '@/shared/state-browse-dir.js';
import { toastState }        from '@/shared/state-toast.js';
import { mergeState }        from '@/shared/merge-state.js';

document.addEventListener('alpine:init', () => {
    Alpine.data('settings', () => mergeState(
        stateConfig(),
        stateProviders(),
        stateUI(),
        stateSourceProbe(),
        browseDirState(),
        toastState(),
        stateDatabase(),
    ));
    // 165-T9: 自訂來源是獨立元件（不進 mergeState）
    Alpine.data('customSources', customSources);
    Alpine.data('aiServicesCard', aiServicesCard);
    Alpine.data('aiSimilarPanel', aiSimilarPanel);
    Alpine.data('aiFacesPanel', aiFacesPanel);
});
