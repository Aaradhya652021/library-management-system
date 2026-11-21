"""Tests for the lazy recommendation service."""
import pytest

from recommender import get_recommender


@pytest.fixture(scope="module")
def rec():
    recommender = get_recommender()
    if not recommender.ok:
        pytest.skip(f"recommender unavailable: {recommender.error}")
    return recommender


def test_model_loads(rec):
    assert rec.ok
    assert len(rec.catalog) == 9697
    assert len(rec.genre_names) == 27
    assert rec.X_items.shape[0] == 9697
    assert rec.svd.shape == (30, 9697)


def test_fantasy_profile_returns_fantasy(rec):
    fantasy = [
        idx for idx, genre in enumerate(rec.catalog["_genre"]) if genre == "Fantasy"
    ][:8]
    assert fantasy
    ratings = {idx: 5 for idx in fantasy}
    results = rec.recommend_for_user(ratings, k=10)
    assert len(results) == 10
    categories = [item["category"] for item in results]
    assert sum(1 for category in categories if category == "Fantasy") >= 6


def test_excluded_books_never_appear(rec):
    liked = [
        idx for idx, genre in enumerate(rec.catalog["_genre"]) if genre == "Mystery & Thriller"
    ][:5]
    ratings = {idx: 5 for idx in liked}
    results = rec.recommend_for_user(ratings, k=10)
    returned = {item["ml_idx"] for item in results}
    assert not returned.intersection(liked)

    extra_excluded = {int(item["ml_idx"]) for item in results[:3]}
    results_2 = rec.recommend_for_user(ratings, k=10, exclude=extra_excluded)
    assert not {item["ml_idx"] for item in results_2}.intersection(extra_excluded)


def test_cold_start_returns_k(rec):
    results = rec.recommend_for_user({}, k=12)
    assert len(results) == 12
    assert all(item["reason"] == "Popular with readers" for item in results)
    assert len({item["ml_idx"] for item in results}) == 12


def test_kmeans_assignment_in_range(rec):
    for profile in ({"Fantasy": 6}, {"Romance": 3, "Classics": 1}, [0] * 27):
        cluster = rec.user_segment(profile)
        assert cluster is not None
        assert 0 <= cluster <= 9
