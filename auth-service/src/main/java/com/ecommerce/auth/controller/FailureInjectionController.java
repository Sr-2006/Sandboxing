package com.ecommerce.auth.controller;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Profile;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/failures/auth")
@Profile("dev")
public class FailureInjectionController {

    private static volatile long validationDelayMs = 0;

    @Value("${failure.auth.validation-delay-ms:0}")
    public void setInitialDelay(long delay) {
        validationDelayMs = delay;
    }

    public static long getValidationDelayMs() {
        return validationDelayMs;
    }

    @GetMapping
    public FailureSettingsResponse getSettings() {
        return new FailureSettingsResponse(validationDelayMs);
    }

    @PostMapping
    public FailureSettingsResponse updateSettings(@RequestBody FailureSettingsRequest request) {
        validationDelayMs = request.validationDelayMs();
        return new FailureSettingsResponse(validationDelayMs);
    }

    public record FailureSettingsRequest(long validationDelayMs) {}
    public record FailureSettingsResponse(long validationDelayMs) {}
}
