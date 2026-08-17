package com.autosre.paymentservice;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/payments")
public class PaymentController {

    @PostMapping("/process")
    public ResponseEntity<String> processPayment(@RequestHeader(value = "X-User-Id", required = false) String userId) {
        if (userId == null || userId.trim().isEmpty()) {
            return ResponseEntity.status(HttpStatus.UNAUTHORIZED).body("Unauthorized: Missing X-User-Id header");
        }
        return ResponseEntity.ok("Payment processed successfully");
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
