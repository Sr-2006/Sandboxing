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
    @DisplayName("Place order endpoint returns 200 OK")
    void testPlaceOrderSuccess() throws Exception {
        mockMvc.perform(post("/api/orders"))
                .andExpect(status().isOk())
                .andExpect(content().string("Order successfully placed"));
    }

    @Test
    @DisplayName("Chaos error endpoint returns 500 INTERNAL_SERVER_ERROR")
    void testSimulateError() throws Exception {
        mockMvc.perform(get("/api/orders/chaos/error"))
                .andExpect(status().isInternalServerError())
                .andExpect(content().string("Simulated Database Crash"));
    }
}
