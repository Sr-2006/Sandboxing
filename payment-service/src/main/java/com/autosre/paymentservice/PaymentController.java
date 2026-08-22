package com.autosre.paymentservice;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.HashMap;
import java.util.Map;
import java.util.UUID;

@RestController
@RequestMapping("/api/payments")
public class PaymentController {

    @Value("${PAYMENT_MOCK_ENABLED:false}")
    private boolean paymentMockEnabled;

    @PostMapping("/process")
    public ResponseEntity<?> processPayment(@RequestHeader(value = "X-User-Id", required = false) String userId) {
        if (userId == null || userId.trim().isEmpty()) {
            return ResponseEntity.status(HttpStatus.UNAUTHORIZED).body("Unauthorized: Missing X-User-Id header");
        }
        if (paymentMockEnabled) {
            Map<String, Object> mockResponse = new HashMap<>();
            mockResponse.put("status", "mock_success");
            mockResponse.put("transaction_id", "shadow-mock-" + UUID.randomUUID().toString());
            mockResponse.put("sandbox", true);
            mockResponse.put("user_id", userId);
            return ResponseEntity.ok(mockResponse);
        }
        return ResponseEntity.ok("Payment processed successfully");
    }

    @GetMapping("/shadow-status")
    public ResponseEntity<Map<String, Object>> paymentShadowStatus() {
        Map<String, Object> status = new HashMap<>();
        status.put("sandbox", true);
        status.put("payment_mock", paymentMockEnabled);
        status.put("external_calls_blocked", paymentMockEnabled);
        status.put("service", "payment-service");
        return ResponseEntity.ok(status);
    }

    @GetMapping("/chaos/latency")
    public ResponseEntity<String> simulateLatency() {
        try {
            Thread.sleep(5000);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
        return ResponseEntity.ok("Artificial Payment Latency");
    }

    @GetMapping("/chaos/decline")
    public ResponseEntity<String> simulateDecline() {
        return ResponseEntity.status(HttpStatus.PAYMENT_REQUIRED).body("Simulated Card Declined");
    }
}

