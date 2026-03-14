#!/usr/bin/env python3
"""
Unit tests for timing.py

Tests cover:
- Timer class: start(), stop(), measure(), add(), get(), total_ms, to_dict(), to_metrics()
- Context manager behavior with exceptions
- timed decorator with functions that return dict and non-dict
- Edge cases: timer not started/stopped, empty entries
"""

import pytest
import time
from unittest.mock import patch

from tools.lib.timing import Timer, TimingEntry, timed


class TestTimingEntry:
    """Tests for TimingEntry dataclass"""

    def test_timing_entry_creation(self):
        """Should create TimingEntry with required fields"""
        entry = TimingEntry(name="test", duration_ms=123.45)
        assert entry.name == "test"
        assert entry.duration_ms == 123.45
        assert entry.start_time == 0.0

    def test_timing_entry_with_start_time(self):
        """Should create TimingEntry with custom start_time"""
        entry = TimingEntry(name="test", duration_ms=123.45, start_time=100.0)
        assert entry.name == "test"
        assert entry.duration_ms == 123.45
        assert entry.start_time == 100.0


class TestTimerInit:
    """Tests for Timer initialization"""

    def test_init_empty_entries(self):
        """Timer should initialize with empty entries"""
        timer = Timer()
        assert timer._entries == []

    def test_init_start_time_is_none(self):
        """Timer should initialize with _start_time as None"""
        timer = Timer()
        assert timer._start_time is None

    def test_init_end_time_is_none(self):
        """Timer should initialize with _end_time as None"""
        timer = Timer()
        assert timer._end_time is None


class TestTimerStartStop:
    """Tests for Timer start() and stop() methods"""

    def test_start_sets_start_time(self):
        """start() should set _start_time"""
        timer = Timer()
        result = timer.start()
        assert timer._start_time is not None
        assert isinstance(timer._start_time, float)
        assert result is timer  # Should return self for chaining

    def test_stop_sets_end_time(self):
        """stop() should set _end_time"""
        timer = Timer()
        timer.start()
        result = timer.stop()
        assert timer._end_time is not None
        assert isinstance(timer._end_time, float)
        assert result is timer  # Should return self for chaining

    def test_start_stop_chaining(self):
        """start() and stop() should support method chaining"""
        timer = Timer()
        result = timer.start().stop()
        assert result is timer
        assert timer._start_time is not None
        assert timer._end_time is not None


class TestTimerTotalMs:
    """Tests for Timer.total_ms property"""

    def test_total_ms_without_start_stop(self):
        """total_ms should return 0.0 if not started/stopped"""
        timer = Timer()
        assert timer.total_ms == 0.0

    def test_total_ms_with_start_stop(self):
        """total_ms should calculate duration"""
        timer = Timer()
        timer.start()
        time.sleep(0.05)  # Sleep for 50ms
        timer.stop()
        assert timer.total_ms >= 50.0  # At least 50ms

    def test_total_ms_rounded(self):
        """total_ms should be rounded to 2 decimal places"""
        timer = Timer()
        timer.start()
        time.sleep(0.01)
        timer.stop()
        # Check it's rounded (has at most 2 decimal places)
        assert timer.total_ms == round(timer.total_ms, 2)


class TestTimerMeasure:
    """Tests for Timer.measure() context manager"""

    def test_measure_context_manager(self):
        """measure() should time the context block"""
        timer = Timer()
        with timer.measure("test_op"):
            time.sleep(0.05)  # Sleep for 50ms

        assert len(timer._entries) == 1
        entry = timer._entries[0]
        assert entry.name == "test_op"
        assert entry.duration_ms >= 50.0  # At least 50ms

    def test_measure_multiple_operations(self):
        """measure() should track multiple operations"""
        timer = Timer()
        with timer.measure("op1"):
            time.sleep(0.02)
        with timer.measure("op2"):
            time.sleep(0.03)

        assert len(timer._entries) == 2
        assert timer._entries[0].name == "op1"
        assert timer._entries[1].name == "op2"

    def test_measure_with_exception(self):
        """measure() should record timing even if exception occurs"""
        timer = Timer()
        try:
            with timer.measure("failing_op"):
                time.sleep(0.02)
                raise ValueError("Test error")
        except ValueError:
            pass

        # Entry should still be recorded
        assert len(timer._entries) == 1
        assert timer._entries[0].name == "failing_op"
        assert timer._entries[0].duration_ms >= 20.0

    def test_measure_preserves_entry_order(self):
        """Entries should be in order of execution"""
        timer = Timer()
        with timer.measure("first"):
            pass
        with timer.measure("second"):
            pass
        with timer.measure("third"):
            pass

        assert timer._entries[0].name == "first"
        assert timer._entries[1].name == "second"
        assert timer._entries[2].name == "third"


class TestTimerAdd:
    """Tests for Timer.add() method"""

    def test_add_entry(self):
        """add() should add a timing entry"""
        timer = Timer()
        result = timer.add("manual_op", 123.45)

        assert len(timer._entries) == 1
        entry = timer._entries[0]
        assert entry.name == "manual_op"
        assert entry.duration_ms == 123.45
        assert result is timer  # Should return self for chaining

    def test_add_rounds_duration(self):
        """add() should round duration to 2 decimal places"""
        timer = Timer()
        timer.add("op", 123.456789)

        assert timer._entries[0].duration_ms == 123.46

    def test_add_multiple_entries(self):
        """add() should support multiple entries"""
        timer = Timer()
        timer.add("op1", 100.0).add("op2", 200.0)

        assert len(timer._entries) == 2
        assert timer._entries[0].duration_ms == 100.0
        assert timer._entries[1].duration_ms == 200.0

    def test_add_chaining(self):
        """add() should support method chaining"""
        timer = Timer()
        result = timer.add("op1", 100.0).add("op2", 200.0).add("op3", 300.0)

        assert result is timer
        assert len(timer._entries) == 3


class TestTimerGet:
    """Tests for Timer.get() method"""

    def test_get_existing_entry(self):
        """get() should return duration for existing entry"""
        timer = Timer()
        timer.add("test_op", 123.45)

        result = timer.get("test_op")
        assert result == 123.45

    def test_get_nonexistent_entry(self):
        """get() should return None for nonexistent entry"""
        timer = Timer()
        timer.add("op1", 100.0)

        result = timer.get("op2")
        assert result is None

    def test_get_first_matching_entry(self):
        """get() should return first matching entry if duplicates exist"""
        timer = Timer()
        timer.add("op", 100.0)
        timer.add("op", 200.0)

        result = timer.get("op")
        assert result == 100.0


class TestTimerToDict:
    """Tests for Timer.to_dict() method"""

    def test_to_dict_empty(self):
        """to_dict() should return empty dict for no entries"""
        timer = Timer()
        result = timer.to_dict()
        assert result == {}

    def test_to_dict_with_entries(self):
        """to_dict() should convert entries to dict"""
        timer = Timer()
        timer.add("op1", 100.0)
        timer.add("op2", 200.0)

        result = timer.to_dict()
        assert result == {"op1_ms": 100.0, "op2_ms": 200.0}

    def test_to_dict_with_total(self):
        """to_dict() should include total_ms if timer was started/stopped"""
        timer = Timer()
        timer.start()
        time.sleep(0.01)
        timer.stop()
        timer.add("op1", 100.0)

        result = timer.to_dict()
        assert "op1_ms" in result
        assert "total_ms" in result
        assert result["op1_ms"] == 100.0

    def test_to_dict_without_total(self):
        """to_dict() should not include total_ms if timer not started/stopped"""
        timer = Timer()
        timer.add("op1", 100.0)

        result = timer.to_dict()
        assert "op1_ms" in result
        assert "total_ms" not in result


class TestTimerToMetrics:
    """Tests for Timer.to_metrics() method"""

    def test_to_metrics_empty(self):
        """to_metrics() should return structure with empty entries"""
        timer = Timer()
        result = timer.to_metrics()

        assert "timings" in result
        assert "entries" in result
        assert result["timings"] == {}
        assert result["entries"] == []

    def test_to_metrics_with_entries(self):
        """to_metrics() should include entries list"""
        timer = Timer()
        timer.add("op1", 100.0)
        timer.add("op2", 200.0)

        result = timer.to_metrics()
        assert len(result["entries"]) == 2
        assert result["entries"][0] == {"name": "op1", "duration_ms": 100.0}
        assert result["entries"][1] == {"name": "op2", "duration_ms": 200.0}

    def test_to_metrics_timings_dict(self):
        """to_metrics() should include timings dict"""
        timer = Timer()
        timer.add("op1", 100.0)

        result = timer.to_metrics()
        assert result["timings"] == {"op1_ms": 100.0}

    def test_to_metrics_with_total(self):
        """to_metrics() should include total_ms if timer was started/stopped"""
        timer = Timer()
        timer.start()
        time.sleep(0.01)
        timer.stop()

        result = timer.to_metrics()
        assert "total_ms" in result
        assert result["total_ms"] >= 0.0

    def test_to_metrics_without_total(self):
        """to_metrics() should not include total_ms if timer not started/stopped"""
        timer = Timer()
        timer.add("op1", 100.0)

        result = timer.to_metrics()
        assert "total_ms" not in result


class TestTimerEdgeCases:
    """Edge case tests for Timer"""

    def test_measure_zero_duration(self):
        """measure() should handle zero-duration operations"""
        timer = Timer()
        with timer.measure("instant_op"):
            pass  # No delay

        assert len(timer._entries) == 1
        assert timer._entries[0].duration_ms >= 0.0

    def test_get_with_empty_entries(self):
        """get() should return None for empty timer"""
        timer = Timer()
        result = timer.get("anything")
        assert result is None

    def test_total_ms_only_start(self):
        """total_ms should return 0.0 if only started but not stopped"""
        timer = Timer()
        timer.start()
        assert timer.total_ms == 0.0

    def test_total_ms_only_stop(self):
        """total_ms should return 0.0 if only stopped but not started"""
        timer = Timer()
        timer.stop()
        assert timer.total_ms == 0.0

    def test_add_negative_duration(self):
        """add() should accept negative duration (edge case)"""
        timer = Timer()
        timer.add("negative", -100.0)
        assert timer._entries[0].duration_ms == -100.0


class TestTimedDecorator:
    """Tests for timed decorator"""

    def test_timed_with_dict_return(self):
        """timed should add metrics to dict return value"""

        @timed
        def my_function():
            return {"success": True}

        result = my_function()
        assert isinstance(result, dict)
        assert "success" in result
        assert "metrics" in result
        assert isinstance(result["metrics"], dict)

    def test_timed_with_non_dict_return(self):
        """timed should not modify non-dict return value"""

        @timed
        def my_function():
            return "success"

        result = my_function()
        assert result == "success"
        assert not isinstance(result, dict)

    def test_timed_with_exception(self):
        """timed should stop timer and re-raise exception"""

        @timed
        def failing_function():
            raise ValueError("Test error")

        with pytest.raises(ValueError, match="Test error"):
            failing_function()

    def test_timed_with_arguments(self):
        """timed should pass arguments to function"""

        @timed
        def add(a, b):
            return {"result": a + b}

        result = my_function = add(2, 3)
        assert result["result"] == 5
        assert "metrics" in result

    def test_timed_with_kwargs(self):
        """timed should pass keyword arguments to function"""

        @timed
        def greet(name, greeting="Hello"):
            return {"message": f"{greeting}, {name}!"}

        result = greet("World", greeting="Hi")
        assert result["message"] == "Hi, World!"
        assert "metrics" in result

    def test_timed_preserves_function_name(self):
        """timed should preserve original function name"""

        @timed
        def my_special_function():
            pass

        assert my_special_function.__name__ == "my_special_function"

    def test_timed_with_none_return(self):
        """timed should handle None return value"""

        @timed
        def returns_none():
            return None

        result = returns_none()
        assert result is None

    def test_timed_with_empty_dict_return(self):
        """timed should add metrics to empty dict"""

        @timed
        def returns_empty_dict():
            return {}

        result = returns_empty_dict()
        assert isinstance(result, dict)
        assert "metrics" in result

    def test_timed_metrics_structure(self):
        """timed should add properly structured metrics"""

        @timed
        def my_function():
            time.sleep(0.01)
            return {"data": "test"}

        result = my_function()
        metrics = result["metrics"]
        assert "total_ms" in metrics
        assert metrics["total_ms"] >= 0.0


class TestTimedDecoratorEdgeCases:
    """Edge case tests for timed decorator"""

    def test_timed_with_list_return(self):
        """timed should not modify list return value"""

        @timed
        def returns_list():
            return [1, 2, 3]

        result = returns_list()
        assert result == [1, 2, 3]

    def test_timed_with_int_return(self):
        """timed should not modify int return value"""

        @timed
        def returns_int():
            return 42

        result = returns_int()
        assert result == 42

    def test_timed_with_exception_during_timing(self):
        """timed should stop timer even if exception occurs"""
        exception_raised = False
        timer_stopped = False

        @timed
        def failing_function():
            nonlocal exception_raised
            try:
                raise ValueError("Test error")
            except ValueError:
                exception_raised = True
                raise

        try:
            failing_function()
        except ValueError:
            timer_stopped = True

        assert exception_raised
        assert timer_stopped

    def test_timed_nested_functions(self):
        """timed should work with nested function calls"""

        @timed
        def outer():
            inner_result = inner()
            return {"outer": True, "inner": inner_result}

        @timed
        def inner():
            return {"inner": True}

        result = outer()
        assert "outer" in result
        assert "inner" in result
        assert "metrics" in result
        assert "metrics" in result["inner"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
