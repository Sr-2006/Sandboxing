import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from phase1_processor import preprocess_log_header

def test_stack_trace_masking_preserves_class_names():
    sample_trace = "at com.autosre.orderservice.chaos.ChaosController.throwError(ChaosController.java:50)"
    processed = preprocess_log_header(sample_trace)
    assert "com.autosre.orderservice.chaos.ChaosController.throwError" in processed
    assert "ChaosController.java:<LINE>" in processed
    assert ":50" not in processed
