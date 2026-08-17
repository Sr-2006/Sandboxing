package com.autosre.orderservice;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.web.servlet.MockMvc;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
public class OrderControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @Test
    @DisplayName("Place order endpoint returns 200 OK when authenticated with internal token and user header")
    void testPlaceOrderSuccess() throws Exception {
        mockMvc.perform(post("/api/orders")
                        .header("X-Internal-Service-Token", "test-internal-token")
                        .header("X-User-Id", "john_doe"))
                .andExpect(status().isOk())
                .andExpect(content().string("Order successfully placed"));
    }

    @Test
    @DisplayName("Place order endpoint returns 401 UNAUTHORIZED when internal token is missing")
    void testPlaceOrderMissingToken() throws Exception {
        mockMvc.perform(post("/api/orders")
                        .header("X-User-Id", "john_doe"))
                .andExpect(status().isUnauthorized());
    }

    @Test
    @DisplayName("Place order endpoint returns 401 UNAUTHORIZED when X-User-Id is missing")
    void testPlaceOrderMissingUserId() throws Exception {
        mockMvc.perform(post("/api/orders")
                        .header("X-Internal-Service-Token", "test-internal-token"))
                .andExpect(status().isUnauthorized());
    }

    @Test
    @DisplayName("Chaos error endpoint returns 500 INTERNAL_SERVER_ERROR when authenticated")
    void testSimulateError() throws Exception {
        mockMvc.perform(get("/api/orders/chaos/error")
                        .header("X-Internal-Service-Token", "test-internal-token")
                        .header("X-User-Id", "john_doe"))
                .andExpect(status().isInternalServerError())
                .andExpect(content().string("Simulated Database Crash"));
    }
}
