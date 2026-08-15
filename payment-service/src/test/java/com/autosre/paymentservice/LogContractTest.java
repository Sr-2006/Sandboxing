package com.autosre.paymentservice;

import ch.qos.logback.classic.Level;
import ch.qos.logback.classic.Logger;
import ch.qos.logback.classic.spi.LoggingEvent;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import net.logstash.logback.encoder.LogstashEncoder;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.slf4j.LoggerFactory;
import org.slf4j.MDC;

import java.nio.charset.StandardCharsets;

import static org.junit.jupiter.api.Assertions.*;

public class LogContractTest {

    private final ObjectMapper objectMapper = new ObjectMapper();

    @Test
    @DisplayName("LogContract: Logstash JSON output contains @timestamp, level, message, trace_id, span_id")
    void testLogstashLogContract() throws Exception {
        LogstashEncoder encoder = new LogstashEncoder();
        encoder.start();

        Logger logger = (Logger) LoggerFactory.getLogger(LogContractTest.class);
        MDC.put("trace_id", "4bf92f3577b34da6a3ce929d0e0e4736");
        MDC.put("span_id", "00f067aa0ba902b7");

        LoggingEvent event = new LoggingEvent(
                "com.autosre.paymentservice.LogContractTest",
                logger,
                Level.ERROR,
                "Payment gateway communication drop simulation",
                null,
                new Object[]{}
        );

        byte[] encodedBytes = encoder.encode(event);
        String jsonOutput = new String(encodedBytes, StandardCharsets.UTF_8);
        MDC.clear();

        assertNotNull(jsonOutput);
        JsonNode rootNode = objectMapper.readTree(jsonOutput);

        assertTrue(rootNode.has("@timestamp"), "Logstash output missing @timestamp");
        assertTrue(rootNode.has("level"), "Logstash output missing level");
        assertTrue(rootNode.has("message"), "Logstash output missing message");
        assertTrue(rootNode.has("trace_id"), "Logstash output missing trace_id");
        assertTrue(rootNode.has("span_id"), "Logstash output missing span_id");

        assertEquals("ERROR", rootNode.get("level").asText());
        assertEquals("4bf92f3577b34da6a3ce929d0e0e4736", rootNode.get("trace_id").asText());
        assertEquals("00f067aa0ba902b7", rootNode.get("span_id").asText());
    }
}
