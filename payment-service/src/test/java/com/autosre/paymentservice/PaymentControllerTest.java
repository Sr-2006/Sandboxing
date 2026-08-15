package com.autosre.paymentservice;

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
public class PaymentControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @Test
    @DisplayName("Process payment endpoint returns 200 OK")
    void testProcessPaymentSuccess() throws Exception {
        mockMvc.perform(post("/api/payments/process"))
                .andExpect(status().isOk())
                .andExpect(content().string("Payment processed successfully"));
    }

    @Test
    @DisplayName("Chaos decline endpoint returns 402 PAYMENT_REQUIRED")
    void testSimulateDecline() throws Exception {
        mockMvc.perform(get("/api/payments/chaos/decline"))
                .andExpect(status().isPaymentRequired())
                .andExpect(content().string("Simulated Card Declined"));
    }
}
