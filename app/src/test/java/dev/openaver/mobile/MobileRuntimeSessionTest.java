package dev.openaver.mobile;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import org.junit.After;
import org.junit.Test;

public final class MobileRuntimeSessionTest {
    @After
    public void tearDown() {
        MobileRuntimeSession.clear();
    }

    @Test
    public void tracksReadyStateAndClearsCredentials() {
        MobileRuntimeSession.clear();
        assertFalse(MobileRuntimeSession.isReady());

        MobileRuntimeSession.markReady(
                8765,
                "secret-token",
                "openaver_loopback",
                "/data/local/files",
                "arm64-v8a",
                null,
                null
        );

        assertTrue(MobileRuntimeSession.isReady());
        assertEquals(8765, MobileRuntimeSession.getPort());
        assertEquals("secret-token", MobileRuntimeSession.getAuthToken());
        assertEquals("openaver_loopback", MobileRuntimeSession.getAuthCookieName());
        assertEquals("/data/local/files", MobileRuntimeSession.getDataDir());
        assertEquals("arm64-v8a", MobileRuntimeSession.getAbi());

        MobileRuntimeSession.clear();
        assertFalse(MobileRuntimeSession.isReady());
        assertEquals("", MobileRuntimeSession.getAuthToken());
        assertNull(MobileRuntimeSession.getCfTransport());
    }

    @Test
    public void requiresNonEmptyTokenToBeReady() {
        MobileRuntimeSession.markReady(8765, "", "cookie", "/data", "arm64-v8a", null, null);
        assertFalse(MobileRuntimeSession.isReady());
        assertEquals("openaver_main", MobileRuntimeSession.FLUTTER_ENGINE_ID);
    }
}
