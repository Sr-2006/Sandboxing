import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from phase1_processor import is_redis_noise

def test_redis_noise_lines_filtered():
    noise_samples = [
        "Ready to accept connections",
        "Background saving started by pid 14",
        "Background saving terminated with success",
        "DB loaded from disk: 0.000 seconds",
        "Server initialized",
        "Reading the remaining RDB tail...",
        "RDB memory usage when created",
        "Running mode=standalone, port 6379",
        "Configuration loaded",
        "Loading RDB produced by version 7.0.0",
        "# Server started, Redis version=7.0.0",
        "1:M 15 Aug 2026 10:00:00.000 . Loading DB",
        "1:M 15 Aug 2026 10:00:00.000 # Warning: no config file specified, using the default config. In order to specify a config file use redis-server /path/to/redis.conf"
    ]
    for sample in noise_samples:
        assert is_redis_noise("redis", "INFO", sample) is True, f"Failed to filter: {sample}"

def test_redis_legitimate_errors_passed():
    error_samples = [
        "1:M 15 Aug 2026 10:00:00.000 # Error writing to client: Connection reset",
        "1:M 15 Aug 2026 10:00:00.000 # MISCONF Redis is configured to save RDB snapshots",
        "1:M 15 Aug 2026 10:00:00.000 # Failed opening .rdb for saving: Permission denied",
        "1:M 15 Aug 2026 10:00:00.000 #  CantSaveIn background saving error",
        "1:M 15 Aug 2026 10:00:00.000 #  fatale error during load",
        "1:M 15 Aug 2026 10:00:00.000 # Out of memory allocating 1048576 bytes",
        "1:M 15 Aug 2026 10:00:00.000 #  WARNING  Overcommit memory is set to 0!"
    ]
    for sample in error_samples:
        assert is_redis_noise("redis", "ERROR", sample) is False, f"Erroneously filtered: {sample}"
