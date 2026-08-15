package com.ecommerce.auth.util;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

public class JwtUtilTest {

    private JwtUtil jwtUtil;
    private final String secret = "9a4f2c8d3b7a1e5f8c3d6b2a1f4e7d9c8b7a6f5e4d3c2b1a0f9e8d7c6b5a4f3e";

    @BeforeEach
    void setUp() {
        jwtUtil = new JwtUtil();
        jwtUtil.setJwtSecret(secret);
        jwtUtil.setJwtExpirationMs(3600000); // 1 hour
    }

    @Test
    @DisplayName("Generate and Validate Valid JWT Token")
    void testMintAndValidateToken() {
        String token = jwtUtil.generateToken("john_doe");
        assertNotNull(token);
        assertTrue(jwtUtil.validateToken(token));
        assertEquals("john_doe", jwtUtil.extractUsername(token));
    }

    @Test
    @DisplayName("Expired Token Fails Validation")
    void testExpiredTokenValidation() throws InterruptedException {
        // Mint a token with 10ms expiry
        String expiredToken = jwtUtil.generateCustomToken("expired_user", 10);
        Thread.sleep(50);
        assertFalse(jwtUtil.validateToken(expiredToken));
    }

    @Test
    @DisplayName("Tampered Token Fails Validation")
    void testTamperedTokenValidation() {
        String token = jwtUtil.generateToken("alice");
        String tampered = token.substring(0, token.length() - 5) + "abcde";
        assertFalse(jwtUtil.validateToken(tampered));
    }
}
