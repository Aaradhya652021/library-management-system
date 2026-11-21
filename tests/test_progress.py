"""Tests for the reading-progress report."""
from progress import get_progress, reading_level


def test_reading_level_thresholds():
    assert reading_level(0)["name"] == "Newcomer"
    assert reading_level(2)["name"] == "Newcomer"
    assert reading_level(2)["books_to_next"] == 1
    assert reading_level(3)["name"] == "Reader"
    assert reading_level(9)["name"] == "Reader"
    assert reading_level(10)["name"] == "Bookworm"
    assert reading_level(24)["name"] == "Bookworm"
    assert reading_level(25)["name"] == "Scholar"
    assert reading_level(25)["progress_pct"] == 100


def test_get_progress_shape():
    report = get_progress(1)
    expected = {
        "borrowed", "returned", "reading", "on_time_rate", "total_fines",
        "avg_rating", "rated_count", "unrated", "monthly", "genres",
        "currently_reading", "level",
    }
    assert expected.issubset(report.keys())
    assert len(report["monthly"]) == 6
    assert isinstance(report["level"], dict)
    assert "name" in report["level"]
