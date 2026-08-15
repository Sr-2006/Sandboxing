import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from phase1_processor import is_infra_noise

def test_rabbitmq_noise_lines_filtered():
    noise_samples = [
        "2026-08-15 10:00:00.000 [info] <0.44.0> Server startup complete; 4 plugins started.",
        "2026-08-15 10:00:00.000 [info] <0.44.0> Time to start RabbitMQ: 2344 ms",
        "2026-08-15 10:00:00.000 [info] <0.44.0> Starting RabbitMQ 3.13.0 on Erlang 26.2.5",
        "2026-08-15 10:00:00.000 [info] <0.44.0> Running boot step rabbit_core_metrics",
        "2026-08-15 10:00:00.000 [info] <0.44.0> node           : rabbit@rabbitmq",
        "2026-08-15 10:00:00.000 [info] <0.44.0> home dir       : /var/lib/rabbitmq",
        "2026-08-15 10:00:00.000 [info] <0.44.0> config file(s): /etc/rabbitmq/rabbitmq.conf",
        "2026-08-15 10:00:00.000 [info] <0.44.0> cookie hash    : abcd1234==",
        "2026-08-15 10:00:00.000 [info] <0.44.0> log(s)         : <stdout>",
        "2026-08-15 10:00:00.000 [info] <0.44.0> database dir   : /var/lib/rabbitmq/mnesia/rabbit@rabbitmq",
        "2026-08-15 10:00:00.000 [warning] <0.44.0> Deprecated features: default guest user configuration"
    ]
    for sample in noise_samples:
        assert is_infra_noise("rabbitmq", "INFO", sample) is True, f"Failed to filter: {sample}"

def test_rabbitmq_legitimate_errors_passed():
    error_samples = [
        "2026-08-15 10:00:00.000 [error] <0.234.0> ** Generic server <0.234.0> terminating. Exception: connection_lost",
        "2026-08-15 10:00:00.000 [error] <0.234.0> CRITICAL rabbitmq node crashed due to out of memory",
        "2026-08-15 10:00:00.000 [error] <0.234.0> disk_alarm set: free disk space 0MB below threshold",
        "2026-08-15 10:00:00.000 [error] <0.234.0> ConnectionClosed: connection.retry limit reached"
    ]
    for sample in error_samples:
        assert is_infra_noise("rabbitmq", "ERROR", sample) is False, f"Erroneously filtered: {sample}"
