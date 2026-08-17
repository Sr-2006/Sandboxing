package com.autosre.orderservice;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/orders")
public class OrderController {

    @PostMapping
    public ResponseEntity<String> placeOrder(@RequestHeader(value = "X-User-Id", required = false) String userId) {
        if (userId == null || userId.trim().isEmpty()) {
            return ResponseEntity.status(HttpStatus.UNAUTHORIZED).body("Unauthorized: Missing X-User-Id header");
        }
        return ResponseEntity.ok("Order successfully placed");
    }

    @GetMapping("/chaos/timeout")
    public ResponseEntity<String> simulateTimeout() {
        try {
            Thread.sleep(8000);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
        return ResponseEntity.status(HttpStatus.REQUEST_TIMEOUT).body("Simulated Timeout Failure");
    }

    @GetMapping("/chaos/error")
    public ResponseEntity<String> simulateError() {
        return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR).body("Simulated Database Crash");
    }
}
