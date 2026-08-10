import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backtest.walkforward import split_windows


def test_split_windows_rolls_forward_by_test_days():
    start = dt.date(2026, 1, 1)
    end = dt.date(2026, 4, 1)  # 90 days
    windows = split_windows(start, end, train_days=30, test_days=14)

    assert len(windows) > 0
    for train_start, train_end, test_start, test_end in windows:
        assert train_end - train_start == dt.timedelta(days=30)
        assert test_end - test_start == dt.timedelta(days=14)
        assert test_start == train_end  # test immediately follows train, no gap
        assert test_end <= end

    # Each step should be offset from the previous by test_days.
    starts = [w[0] for w in windows]
    for a, b in zip(starts, starts[1:]):
        assert b - a == dt.timedelta(days=14)


def test_split_windows_empty_when_range_too_short():
    start = dt.date(2026, 1, 1)
    end = dt.date(2026, 1, 10)  # far shorter than train+test
    assert split_windows(start, end, train_days=30, test_days=14) == []
