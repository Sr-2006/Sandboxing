package com.autosre.orderservice.chaos;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.web.client.ResourceAccessException;
import com.zaxxer.hikari.HikariDataSource;

import jakarta.annotation.PreDestroy;
import javax.sql.DataSource;
import java.sql.Connection;
import java.util.*;
import java.util.concurrent.CopyOnWriteArrayList;

@RestController
@RequestMapping("/chaos")
@ConditionalOnProperty(name = "chaos.enabled", havingValue = "true", matchIfMissing = false)
public class ChaosController {

    private static final List<byte[][]> memoryLeakList = new CopyOnWriteArrayList<>();
    private static final List<Thread> deadlockThreads = new CopyOnWriteArrayList<>();

    @Value("${chaos.token:}")
    private String chaosToken;

    @Autowired(required = false)
    private JdbcTemplate jdbcTemplate;

    @Autowired(required = false)
    private DataSource dataSource;

    private void validateToken(String headerToken) {
        if (chaosToken == null || chaosToken.trim().isEmpty()) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "Forbidden: chaos token not configured");
        }
        if (headerToken == null || !chaosToken.equals(headerToken.trim())) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "Forbidden: Invalid or missing X-Chaos-Token");
        }
    }

    @GetMapping("/slow")
    public ResponseEntity<?> slow(
            @RequestHeader(value = "X-Chaos-Token", required = false) String token,
            @RequestParam(defaultValue = "5000") long delayMs) {
        validateToken(token);
        try {
            Thread.sleep(delayMs);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
        Map<String, Object> response = new HashMap<>();
        response.put("status", "slow_response");
        response.put("delay_ms", delayMs);
        return ResponseEntity.ok(response);
    }

    @GetMapping("/throw")
    public ResponseEntity<?> throwError(
            @RequestHeader(value = "X-Chaos-Token", required = false) String token,
            @RequestParam String type) {
        validateToken(token);
        if ("null-pointer".equalsIgnoreCase(type)) {
            throw new NullPointerException("Simulated NPE from ChaosController");
        } else if ("sql-timeout".equalsIgnoreCase(type)) {
            throw new DataAccessResourceFailureException("Simulated DB timeout");
        } else if ("connection-reset".equalsIgnoreCase(type)) {
            throw new ResourceAccessException("Simulated connection reset");
        } else {
            Map<String, String> err = new HashMap<>();
            err.put("error", "Unknown error type: " + type);
            return ResponseEntity.badRequest().body(err);
        }
    }

    @GetMapping("/memory-leak")
    public ResponseEntity<?> memoryLeak(
            @RequestHeader(value = "X-Chaos-Token", required = false) String token,
            @RequestParam(defaultValue = "200") int mb) {
        validateToken(token);
        try {
            for (int i = 0; i < mb; i++) {
                byte[][] chunk = new byte[1024][1024]; // 1MB allocation
                memoryLeakList.add(chunk);
            }
        } catch (OutOfMemoryError e) {
            Map<String, Object> errResponse = new HashMap<>();
            errResponse.put("status", "oom_triggered");
            errResponse.put("allocated_mb", memoryLeakList.size());
            return ResponseEntity.status(500).body(errResponse);
        }
        Map<String, Object> response = new HashMap<>();
        response.put("status", "memory_leaked_mb");
        response.put("allocated_mb", mb);
        return ResponseEntity.ok(response);
    }

    @GetMapping("/memory-leak/clear")
    public ResponseEntity<?> clearMemoryLeak(
            @RequestHeader(value = "X-Chaos-Token", required = false) String token) {
        validateToken(token);
        memoryLeakList.clear();
        System.gc();
        Map<String, Object> response = new HashMap<>();
        response.put("status", "memory_cleared");
        return ResponseEntity.ok(response);
    }

    @GetMapping("/deadlock")
    public ResponseEntity<?> deadlock(
            @RequestHeader(value = "X-Chaos-Token", required = false) String token) {
        validateToken(token);
        Object lock1 = new Object();
        Object lock2 = new Object();

        Thread t1 = new Thread(() -> {
            synchronized (lock1) {
                try {
                    Thread.sleep(1000);
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                }
                synchronized (lock2) {
                    System.out.println("[Chaos] Deadlock thread 1 completed");
                }
            }
        }, "Chaos-Deadlock-Thread-1");

        Thread t2 = new Thread(() -> {
            synchronized (lock2) {
                try {
                    Thread.sleep(1000);
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                }
                synchronized (lock1) {
                    System.out.println("[Chaos] Deadlock thread 2 completed");
                }
            }
        }, "Chaos-Deadlock-Thread-2");

        deadlockThreads.add(t1);
        deadlockThreads.add(t2);

        t1.start();
        t2.start();

        Map<String, Object> response = new HashMap<>();
        response.put("status", "deadlock_started");
        return ResponseEntity.ok(response);
    }

    @GetMapping("/deadlock/clear")
    public ResponseEntity<?> clearDeadlock(
            @RequestHeader(value = "X-Chaos-Token", required = false) String token) {
        validateToken(token);
        for (Thread t : deadlockThreads) {
            if (t.isAlive()) {
                t.interrupt();
            }
        }
        deadlockThreads.clear();
        Map<String, Object> response = new HashMap<>();
        response.put("status", "deadlock_cleared");
        return ResponseEntity.ok(response);
    }

    @GetMapping("/sql-lock")
    public ResponseEntity<?> sqlLock(
            @RequestHeader(value = "X-Chaos-Token", required = false) String token) {
        validateToken(token);
        if (jdbcTemplate == null) {
            Map<String, Object> response = new HashMap<>();
            response.put("status", "sql_lock_skipped_no_db");
            return ResponseEntity.ok(response);
        }

        new Thread(() -> {
            try {
                jdbcTemplate.execute("SELECT pg_sleep(10)");
            } catch (Exception e) {
                System.err.println("SQL sleep failed: " + e.getMessage());
            }
        }).start();

        Map<String, Object> response = new HashMap<>();
        response.put("status", "sql_lock_acquired");
        return ResponseEntity.ok(response);
    }

    @GetMapping("/exhaust-pool")
    public ResponseEntity<?> exhaustPool(
            @RequestHeader(value = "X-Chaos-Token", required = false) String token) {
        validateToken(token);
        if (dataSource == null) {
            Map<String, Object> response = new HashMap<>();
            response.put("status", "pool_exhaustion_skipped_no_db");
            return ResponseEntity.ok(response);
        }

        new Thread(() -> {
            if (dataSource instanceof HikariDataSource) {
                HikariDataSource hikariDS = (HikariDataSource) dataSource;
                int poolSize = hikariDS.getMaximumPoolSize();
                List<Connection> connections = new ArrayList<>();
                try {
                    System.out.println("[Chaos] Exhausting Hikari pool: acquiring " + poolSize + " connections...");
                    for (int i = 0; i < poolSize; i++) {
                        connections.add(hikariDS.getConnection());
                    }
                    System.out.println("[Chaos] Hikari pool fully exhausted. Holding for 30s...");
                    Thread.sleep(30000);
                } catch (Exception e) {
                    System.err.println("Failed to exhaust pool: " + e.getMessage());
                } finally {
                    System.out.println("[Chaos] Releasing exhausted pool connections...");
                    for (Connection conn : connections) {
                        try {
                            if (conn != null && !conn.isClosed()) {
                                conn.close();
                            }
                        } catch (Exception ex) {
                            // ignore
                        }
                    }
                }
            } else {
                System.err.println("DataSource is not a HikariDataSource, cannot exhaust pool");
            }
        }).start();

        Map<String, Object> response = new HashMap<>();
        response.put("status", "pool_exhaustion_started");
        return ResponseEntity.ok(response);
    }

    @PreDestroy
    public void cleanup() {
        memoryLeakList.clear();
        for (Thread t : deadlockThreads) {
            if (t.isAlive()) {
                t.interrupt();
            }
        }
        deadlockThreads.clear();
    }
}
