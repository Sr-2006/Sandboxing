package com.ecommerce.auth.chaos;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.web.servlet.MockMvc;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
@TestPropertySource(properties = {
        "chaos.enabled=true",
        "chaos.token=test-secret-token"
})
public class ChaosControllerSecurityTest {

    @Autowired
    private MockMvc mockMvc;

    @Test
    @DisplayName("Chaos endpoint without X-Chaos-Token returns 403 Forbidden")
    void testChaosWithoutTokenReturnsForbidden() throws Exception {
        mockMvc.perform(get("/chaos/slow?delayMs=1"))
                .andExpect(status().isForbidden());
    }

    @Test
    @DisplayName("Chaos endpoint with wrong X-Chaos-Token returns 403 Forbidden")
    void testChaosWithWrongTokenReturnsForbidden() throws Exception {
        mockMvc.perform(get("/chaos/slow?delayMs=1")
                        .header("X-Chaos-Token", "invalid-secret"))
                .andExpect(status().isForbidden());
    }

    @Test
    @DisplayName("Chaos endpoint with valid X-Chaos-Token succeeds")
    void testChaosWithValidTokenSucceeds() throws Exception {
        mockMvc.perform(get("/chaos/slow?delayMs=1")
                        .header("X-Chaos-Token", "test-secret-token"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("slow_response"));
    }

    @Test
    @DisplayName("Chaos clear endpoints require valid token")
    void testChaosClearRequiresToken() throws Exception {
        mockMvc.perform(get("/chaos/memory-leak/clear"))
                .andExpect(status().isForbidden());

        mockMvc.perform(get("/chaos/memory-leak/clear")
                        .header("X-Chaos-Token", "test-secret-token"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("memory_cleared"));
    }
}
