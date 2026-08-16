package com.ecommerce.gateway.chaos;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.web.server.ResponseStatusException;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

public class ChaosControllerSecurityTest {

    private ChaosController controller;

    @BeforeEach
    void setUp() {
        controller = new ChaosController();
        ReflectionTestUtils.setField(controller, "chaosToken", "test-chaos-token");
    }

    @Test
    @DisplayName("Request without X-Chaos-Token throws 403 Forbidden")
    void testMissingTokenThrowsForbidden() {
        ResponseStatusException ex = assertThrows(ResponseStatusException.class, () -> {
            controller.slow(null, 1);
        });
        assertEquals(HttpStatus.FORBIDDEN, ex.getStatusCode());
    }

    @Test
    @DisplayName("Request with invalid X-Chaos-Token throws 403 Forbidden")
    void testInvalidTokenThrowsForbidden() {
        ResponseStatusException ex = assertThrows(ResponseStatusException.class, () -> {
            controller.slow("wrong-secret", 1);
        });
        assertEquals(HttpStatus.FORBIDDEN, ex.getStatusCode());
    }

    @Test
    @DisplayName("Request with valid X-Chaos-Token succeeds")
    void testValidTokenSucceeds() {
        ResponseEntity<?> response = controller.slow("test-chaos-token", 1);
        assertEquals(HttpStatus.OK, response.getStatusCode());
        assertNotNull(response.getBody());
        assertTrue(response.getBody() instanceof Map);
        Map<?, ?> map = (Map<?, ?>) response.getBody();
        assertEquals("slow_response", map.get("status"));
    }

    @Test
    @DisplayName("Memory leak clear requires valid token")
    void testMemoryLeakClearRequiresToken() {
        assertThrows(ResponseStatusException.class, () -> {
            controller.clearMemoryLeak(null);
        });

        ResponseEntity<?> response = controller.clearMemoryLeak("test-chaos-token");
        assertEquals(HttpStatus.OK, response.getStatusCode());
    }
}
