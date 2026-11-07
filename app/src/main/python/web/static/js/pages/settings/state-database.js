export function stateDatabase() {
    return {
        restoringDatabase: false,

        async restoreDatabase(event) {
            const input = event.target;
            const file = input.files?.[0];
            input.value = '';
            if (!file || this.restoringDatabase) return;

            if (!window.confirm(window.t('settings.system.database_restore_confirm'))) {
                return;
            }

            const form = new FormData();
            form.append('file', file);
            this.restoringDatabase = true;
            try {
                const resp = await fetch('/api/database/import', {
                    method: 'POST',
                    body: form,
                });
                if (!resp.ok) {
                    const detail = await resp.json().catch(() => ({}));
                    throw new Error(detail.detail || `HTTP ${resp.status}`);
                }
                this.showToast(
                    window.t('settings.system.database_restore_done'),
                    'success',
                    4000
                );
                await new Promise((resolve) => setTimeout(resolve, 800));
                window.location.reload();
            } catch (error) {
                this.showToast(
                    window.t('settings.system.database_restore_failed')
                        + ': ' + error.message,
                    'error',
                    6000
                );
            } finally {
                this.restoringDatabase = false;
            }
        },
    };
}
