package dev.openaver.mobile;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

import java.util.List;

public final class VideoPartParserTest {
    @Test
    public void parsesFiltersDeduplicatesAndNumbersParts() {
        String partsJson = "["
                + "{\"path\":\"file:///movies/ABC-123-cd1.mp4\",\"label\":\"cd1\"},"
                + "{\"path\":\"file:///movies/ABC-123-cd2.mkv\",\"label\":\"\"},"
                + "{\"path\":\"file:///movies/ABC-123-cd2.mkv\",\"label\":\"duplicate\"},"
                + "{\"path\":\"file:///movies/readme.txt\",\"label\":\"bad\"}"
                + "]";

        List<VideoPartParser.Part> parts = VideoPartParser.parse(
                "file:///movies/ABC-123-cd1.mp4",
                partsJson
        );

        assertEquals(2, parts.size());
        assertEquals("cd1", parts.get(0).label);
        assertEquals(1, parts.get(0).number);
        assertEquals("", parts.get(1).label);
        assertEquals(2, parts.get(1).number);
    }

    @Test
    public void fallsBackToSinglePathWhenPayloadIsInvalid() {
        List<VideoPartParser.Part> parts = VideoPartParser.parse(
                "file:///movies/ABC-123.mp4",
                "{not-json"
        );

        assertEquals(1, parts.size());
        assertEquals("file:///movies/ABC-123.mp4", parts.get(0).path);
        assertEquals(1, parts.get(0).number);
    }

    @Test
    public void rejectsNonVideoSinglePath() {
        assertTrue(VideoPartParser.parse("file:///movies/notes.txt", null).isEmpty());
    }

    @Test
    public void truncatesLongLabels() {
        String longLabel = "x".repeat(120);
        String partsJson = "["
                + "{\"path\":\"file:///movies/ABC-123-cd1.mp4\",\"label\":\"" + longLabel + "\"},"
                + "{\"path\":\"file:///movies/ABC-123-cd2.mp4\",\"label\":\"cd2\"}"
                + "]";

        List<VideoPartParser.Part> parts = VideoPartParser.parse(null, partsJson);

        assertEquals(80, parts.get(0).label.length());
    }
}
