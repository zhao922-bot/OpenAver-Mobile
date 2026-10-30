/**
 * Android hardware-back bridge for the embedded WebView.
 *
 * Returns true when an in-page layer consumes the back action. The native
 * activity only falls back to WebView history when this returns false.
 */
(function () {
    'use strict';

    function dataFor(element) {
        if (!element) return null;
        try {
            if (window.Alpine && typeof window.Alpine.$data === 'function') {
                return window.Alpine.$data(element);
            }
            return Array.isArray(element._x_dataStack) ? element._x_dataStack[0] : null;
        } catch (_) {
            return null;
        }
    }

    function pageRoot() {
        var body = document.body;
        if (!body) return null;
        if (body.classList.contains('page-showcase')) return document.querySelector('.showcase-container[x-data]');
        if (body.classList.contains('page-search')) return document.querySelector('.search-container[x-data]');
        if (body.classList.contains('page-scanner')) return document.querySelector('.avlist-container[x-data]');
        if (body.classList.contains('page-settings')) return document.querySelector('#settings-components[x-data]');
        if (body.classList.contains('page-insights')) return document.querySelector('.insights-container[x-data]');
        if (body.classList.contains('page-help')) return document.querySelector('.help-container[x-data]');
        return document.querySelector('.page-layer[x-data], .page-layer [x-data]');
    }

    function closeWhen(state, isOpen, action, label) {
        if (!state || !isOpen(state)) return false;
        try {
            action(state);
        } catch (error) {
            // Keep the user on the current page if a close action fails.
            console.warn('[OpenAverMobileBack] failed to close ' + label, error);
        }
        return true;
    }

    function closeFlag(state, flag, method) {
        return closeWhen(
            state,
            function (value) { return value[flag] === true; },
            function (value) {
                if (method && typeof value[method] === 'function') value[method]();
                else value[flag] = false;
            },
            flag
        );
    }

    function closeNonNull(state, flag, method) {
        return closeWhen(
            state,
            function (value) { return value[flag] !== null && typeof value[flag] !== 'undefined'; },
            function (value) {
                if (method && typeof value[method] === 'function') value[method]();
                else value[flag] = null;
            },
            flag
        );
    }

    function elementVisible(element) {
        if (!element || element === document.body || element === document.documentElement) return false;
        var style = window.getComputedStyle(element);
        return style.display !== 'none'
            && style.visibility !== 'hidden'
            && element.getClientRects().length > 0;
    }

    function closeNativeDialog() {
        var dialogs = document.querySelectorAll('dialog[open]');
        if (!dialogs.length) return false;
        var dialog = dialogs[dialogs.length - 1];
        try {
            if (typeof dialog.close === 'function') dialog.close();
            else dialog.removeAttribute('open');
        } catch (error) {
            console.warn('[OpenAverMobileBack] failed to close dialog', error);
        }
        return true;
    }

    function closeGenericPopover() {
        var elements = document.querySelectorAll('[x-data]');
        for (var i = elements.length - 1; i >= 0; i--) {
            var element = elements[i];
            if (!elementVisible(element)) continue;
            var state = dataFor(element);
            if (!state || state.open !== true) continue;
            try {
                if (typeof state.close === 'function') state.close();
                else state.open = false;
            } catch (error) {
                console.warn('[OpenAverMobileBack] failed to close popover', error);
            }
            return true;
        }
        return false;
    }

    function closeShellLayer(shell) {
        if (!shell) return false;
        var notificationHandled = shell.notifBell && closeWhen(
            shell.notifBell,
            function (value) { return value.drawerOpen === true; },
            function () { shell.closeDrawer(); },
            'notification drawer'
        );
        return notificationHandled || closeFlag(shell, 'mobileMenuOpen', null);
    }

    function closeTutorial() {
        var tutorial = window.SpotlightTutorial;
        if (!tutorial || tutorial.isActive !== true) return false;
        try {
            tutorial.skip();
        } catch (error) {
            console.warn('[OpenAverMobileBack] failed to close tutorial', error);
        }
        return true;
    }

    function closeShowcase(page) {
        if (!page) return false;
        var ui = window.Alpine && typeof window.Alpine.store === 'function'
            ? window.Alpine.store('ui')
            : null;

        // Layer order mirrors what is visually on top: toolbar/dialog, editor,
        // media overlay, then the page's own expanded information state.
        return closeFlag(ui, 'toolbarOpen', null)
            || closeFlag(page, '_maskVisible', 'cancelMask')
            || closeFlag(page, '_pillEditor', '_cancelPillEditor')
            || closeFlag(page, '_releaseEditor', '_cancelReleaseEditor')
            || closeFlag(page, 'similarModeMobileOpen', 'closeMobilePanel')
            || closeFlag(page, 'similarModeOpen', 'closeSimilarMode')
            || closeFlag(page, 'removeActressModalOpen', 'cancelRemoveActressModal')
            || closeFlag(page, 'actressAddPanelOpen', 'closeActressAddPanel')
            || closeFlag(page, '_pickerOpen', '_cancelPicker')
            || closeFlag(page, 'rescrapeOpen', 'closeRescrape')
            || closeFlag(page, 'deleteVideoModalOpen', 'cancelDeleteVideo')
            || closeFlag(page, 'sampleGalleryOpen', 'closeSampleGallery')
            || closeFlag(page, 'lightboxOpen', 'closeLightbox')
            || closeFlag(page, 'infoVisible', null)
            || closeFlag(page, 'sortOpen', null)
            || closeFlag(page, 'modeOpen', null);
    }

    function closeSearch(page) {
        if (!page) return false;
        var overlayHandled = closeFlag(page, 'rescrapeOpen', 'closeRescrape')
            || closeFlag(page, 'browseDirOpen', 'closeBrowseDir')
            || closeFlag(page, 'duplicateModalOpen', 'closeDuplicateModal')
            || closeFlag(page, 'sampleGalleryOpen', 'closeSampleGallery')
            || closeFlag(page, 'wishlistLightboxOpen', 'closeWishlistLightbox')
            || closeFlag(page, 'lightboxOpen', 'closeLightbox');
        if (overlayHandled) return true;

        // A wishlist wall is one level below the search/file result surface.
        if (page.listMode === 'wishlist' && typeof page.switchToSearchList === 'function') {
            page.switchToSearchList();
            return true;
        }

        // Grid -> detail is the normal navigation path. Going back from a
        // detail view must return to the grid, not to the browser's previous
        // menu entry.
        if (page.displayMode === 'detail'
                && page.listMode === 'search'
                && Array.isArray(page.searchResults)
                && page.searchResults.length > 1) {
            page.displayMode = 'grid';
            if (typeof page.saveState === 'function') page.saveState();
            return true;
        }

        // The final result/error surface is one level above the empty search
        // surface. Clear it before allowing WebView history navigation.
        if ((page.pageState === 'result' || page.pageState === 'error')
                && typeof page.clearAll === 'function') {
            page.clearAll();
            return true;
        }
        return false;
    }

    function closeScanner(page) {
        if (!page) return false;
        var overlayHandled = closeFlag(page, 'dirtyCheckModalOpen', 'dirtyCheckCancel')
            || closeFlag(page, 'missingConfirmModalOpen', 'cancelLargeMissingEnrich')
            || closeFlag(page, 'nfoUpdateConfirmModalOpen', 'cancelNfoUpdate')
            || closeFlag(page, 'tagSourceConfirmModalOpen', 'cancelTagSourceUpdate')
            || closeFlag(page, 'deleteAliasGroupModalOpen', 'cancelDeleteAliasGroupModal')
            || closeFlag(page, 'deleteTagAliasGroupModalOpen', 'cancelDeleteTagAliasGroupModal')
            || closeFlag(page, 'copyFailModalOpen', 'closeCopyFailModal')
            || closeFlag(page, 'readonlyConfirmModalOpen', 'readonlyConfirmCancel')
            || closeFlag(page, 'clearCacheModalOpen', null)
            || closeFlag(page, 'browseDirOpen', 'closeBrowseDir');
        if (overlayHandled) return true;
        return closeFlag(page, 'logPanelExpanded', null);
    }

    function closeSettings(page) {
        var customSources = dataFor(document.querySelector('[x-data="customSources"]'));
        if (closeNonNull(customSources, 'customSrcRemoveId', 'customSrcCloseRemove')) return true;
        if (!page) return false;

        var pageHandled = closeFlag(page, 'dirtyCheckModalOpen', 'dirtyCheckCancel')
            || closeFlag(page, 'resetConfigModalOpen', 'cancelResetConfigModal')
            || closeFlag(page, 'thumbCacheDisableConfirmOpen', 'cancelThumbCacheDisable')
            || closeFlag(page, 'serverModeConfirmOpen', 'cancelServerModeChange')
            || closeFlag(page, 'switchModeConfirmOpen', 'cancelSwitchMode')
            || closeFlag(page, 'rewriteStrmConfirmOpen', 'cancelRewriteStrm')
            || closeFlag(page, 'browseDirOpen', 'closeBrowseDir')
            || closeFlag(page, 'showDirDropdown', null);
        return pageHandled
            || closeNonNull(customSources, 'customSrcOpenId', null);
    }

    window.OpenAverMobileBack = function () {
        // Contract: return true only when this call consumed one visible layer.
        // Native code falls back to WebView history only after this returns false.
        var shell = dataFor(document.body);
        if (closeShellLayer(shell)) return true;
        if (closeTutorial()) return true;
        if (closeNativeDialog()) return true;

        var page = dataFor(pageRoot());
        if (typeof window.__openaverMobileBackPage === 'function') {
            if (window.__openaverMobileBackPage(page)) return true;
        }

        var handled = false;
        if (document.body.classList.contains('page-showcase')) handled = closeShowcase(page);
        else if (document.body.classList.contains('page-search')) handled = closeSearch(page);
        else if (document.body.classList.contains('page-scanner')) handled = closeScanner(page);
        else if (document.body.classList.contains('page-settings')) handled = closeSettings(page);

        return handled || closeGenericPopover();
    };
})();
