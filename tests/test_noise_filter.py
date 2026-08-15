import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from phase1_processor import is_redis_noise

def test_redis_startup_noise_filtered():
    # Common Redis startup lines should be filtered out
    assert is_redis_noise("redis", "INFO", "1:M 14 Aug 2026 12:00:00.000 * Ready to accept connections") is True
    assert is_redis_noise("redis", "INFO", "1:M 14 Aug 2026 12:00:00.000 * DB loaded from disk: 0.000 seconds") is True
    assert is_redis_noise("redis", "INFO", "1:M 14 Aug 2026 12:00:00.000 * Background saving started by pid 12") is True
    assert is_redis_noise("redis", "INFO", "oO0OoO0OoO0Oo Redis is starting oO0OoO0OoO0Oo") is True

def test_redis_errors_not_filtered():
    # Redis ERROR or actual failure messages should NOT be filtered out
    assert is_redis_noise("redis", "ERROR", "RDB: 1 MB memory dump failed") is False
    assert is_redis_noise("redis", "CRITICAL", "Fatal error: Out of Memory") is False
    assert is_redis_noise("redis", "WARN", "Disk quota exceeded on /data") is False
    assert is_redis_noise("auth-service", "INFO", "Ready to accept connections") is False
