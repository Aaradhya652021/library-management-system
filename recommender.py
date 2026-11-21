"""Lazy, thread-safe recommendation service.

Everything is loaded from Machine_Learning/hybrid_model.joblib and
Machine_Learning/books_clean.csv.  The 0-based row in books_clean.csv is the
item index used by X_items, svd_item_factors and feedback_simulated.csv.

No full 9697 x 9697 similarity matrix is ever built: scores are computed on
demand with dot products against row-normalised (content) or column-normalised
(SVD) matrices.
"""
from __future__ import annotations

import logging
import os
import re
import threading

import joblib
import numpy as np
import pandas as pd
from scipy import sparse

logger = logging.getLogger(__name__)

# --------------------------------------------------------------- tunables ---
CONTENT_WEIGHT = 0.5
SVD_WEIGHT = 0.4
POPULARITY_WEIGHT = 0.1
# similar_books() blends the same two signals without the popularity prior.
SIMILAR_CONTENT_WEIGHT = 0.6
SIMILAR_SVD_WEIGHT = 0.4
# books_like_cluster() weights the cluster's genre profile against popularity.
CLUSTER_GENRE_WEIGHT = 0.7
CLUSTER_POPULARITY_WEIGHT = 0.3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ML_DIR = os.path.join(BASE_DIR, "Machine_Learning")
MODEL_PATH = os.path.join(ML_DIR, "hybrid_model.joblib")
CATALOG_PATH = os.path.join(ML_DIR, "books_clean.csv")

# kmeans preprocessing variant used by user_segment().
#
# Verified by rebuilding the 800 simulated users from feedback_simulated.csv
# (liked == 1, which is the same as rating >= 4 in that file) and predicting
# with each variant:
#   raw counts  -> [45, 66, 274, 101, 71, 48, 44, 52, 39, 60]  L1 diff 64
#   fractions   -> [33, 66, 306,  90, 65, 46, 43, 52, 39, 60]  L1 diff 10
#   L2-normalised -> [38, 66, 296, 92, 65, 48, 44, 52, 39, 60] L1 diff 24
# Expected sizes: [33, 65, 305, 94, 65, 46, 40, 53, 39, 60].
# Fractions are therefore the variant used below (and the centroid rows sum to
# 1.0, confirming this is how the KMeans model was fitted).
SEGMENT_NORMALISATION = "fraction"


def _scale01(values: np.ndarray) -> np.ndarray:
    """Min-max scale to [0, 1], returning zeros for a flat array."""
    values = np.asarray(values, dtype=np.float64)
    if values.size == 0:
        return values
    low = np.nanmin(values)
    high = np.nanmax(values)
    if not np.isfinite(low) or not np.isfinite(high) or high - low < 1e-12:
        return np.zeros_like(values)
    return (values - low) / (high - low)


def _normalise_isbn(value) -> str:
    """Return a digits-only ISBN, handling floats such as 9.780439e+12."""
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    if re.fullmatch(r"\d+\.0+", text):
        text = text.split(".")[0]
    elif re.fullmatch(r"[0-9.]+[eE]\+?[0-9]+", text):
        try:
            text = str(int(float(text)))
        except ValueError:
            pass
    return re.sub(r"\D", "", text)


def _isbn10_to_13(isbn10: str) -> str:
    """Convert a 10-digit ISBN to its 13-digit equivalent (best effort)."""
    if len(isbn10) != 10 or not isbn10[:9].isdigit():
        return ""
    body = "978" + isbn10[:9]
    total = 0
    for position, char in enumerate(body):
        total += int(char) * (1 if position % 2 == 0 else 3)
    check = (10 - total % 10) % 10
    return body + str(check)


def _normalise_title(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    text = str(value).lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    # Drop a leading article so "The Hobbit" and "Hobbit" still meet.
    for article in ("the ", "a ", "an "):
        if text.startswith(article):
            return text[len(article):]
    return text


def _normalise_author(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    text = str(value).lower()
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


class Recommender:
    """Loads the model once and exposes the recommendation primitives."""

    def __init__(self):
        self.ok = False
        self.error: str | None = None
        self.catalog = pd.DataFrame()
        self.X_items = None
        self.X_norm = None
        self.svd = None
        self.svd_norm = None
        self.kmeans = None
        self.genre_names: list[str] = []
        self.genre_to_idx: dict[str, int] = {}
        self.item_genre_idx = np.array([], dtype=int)
        self.popularity = np.array([], dtype=float)
        self._load()

    # ------------------------------------------------------------- loading --
    def _load(self) -> None:
        try:
            if not os.path.isfile(MODEL_PATH):
                raise FileNotFoundError(MODEL_PATH)
            if not os.path.isfile(CATALOG_PATH):
                raise FileNotFoundError(CATALOG_PATH)

            model = joblib.load(MODEL_PATH)
            catalog = pd.read_csv(CATALOG_PATH)

            X_items = model["X_items"].tocsr().astype(np.float64)
            if X_items.shape[0] != len(catalog):
                raise ValueError(
                    f"catalog rows ({len(catalog)}) != X_items rows ({X_items.shape[0]})"
                )

            row_norms = np.sqrt(np.asarray(X_items.multiply(X_items).sum(axis=1)).ravel())
            row_norms[row_norms == 0] = 1.0
            X_norm = sparse.diags(1.0 / row_norms).dot(X_items).tocsr()

            svd = np.asarray(model["svd_item_factors"], dtype=np.float64)
            col_norms = np.linalg.norm(svd, axis=0)
            col_norms[col_norms == 0] = 1.0
            svd_norm = svd / col_norms

            genre_names = list(model["genre_names"])
            genre_to_idx = {name: pos for pos, name in enumerate(genre_names)}

            catalog = catalog.reset_index(drop=True)
            catalog["_genre"] = catalog["category_grouped"].fillna("Other Non-Fiction")
            catalog["_genre"] = catalog["_genre"].where(
                catalog["_genre"].isin(genre_to_idx), "Other Non-Fiction"
            )
            item_genre_idx = catalog["_genre"].map(genre_to_idx).to_numpy(dtype=int)

            popularity_raw = pd.to_numeric(
                catalog["weighted_rating"], errors="coerce"
            )
            if popularity_raw.isna().all():
                popularity_raw = pd.to_numeric(catalog["rating"], errors="coerce")
            popularity_raw = popularity_raw.fillna(
                popularity_raw.mean() if not popularity_raw.isna().all() else 0.0
            )

            self.catalog = catalog
            self.X_items = X_items
            self.X_norm = X_norm
            self.svd = svd
            self.svd_norm = svd_norm
            self.kmeans = model["kmeans"]
            self.genre_names = genre_names
            self.genre_to_idx = genre_to_idx
            self.item_genre_idx = item_genre_idx
            self.popularity = _scale01(popularity_raw.to_numpy(dtype=float))
            self.ok = True
            logger.info(
                "Recommender loaded: %s items, %s genres, %s clusters",
                len(catalog), len(genre_names), self.kmeans.n_clusters,
            )
        except Exception as exc:  # never crash the site because of the model
            self.ok = False
            self.error = str(exc)
            logger.exception("Recommender could not load; falling back to empty lists: %s", exc)

    # ------------------------------------------------------------- helpers --
    def get_item(self, idx) -> dict | None:
        if not self.ok:
            return None
        try:
            idx = int(idx)
        except (TypeError, ValueError):
            return None
        if idx < 0 or idx >= len(self.catalog):
            return None
        row = self.catalog.iloc[idx]
        return {
            "ml_idx": idx,
            "title": _clean_text(row.get("title")),
            "author": _clean_text(row.get("primary_author")) or _clean_text(row.get("author")),
            "category": _clean_text(row.get("category_grouped")) or _clean_text(row.get("category")),
            "year": _safe_int(row.get("year")),
            "avg_rating": _safe_float(row.get("rating")),
            "weighted_rating": _safe_float(row.get("weighted_rating")),
            "isbn": _normalise_isbn(row.get("isbn13")),
        }

    def _mean_rows(self, matrix, indices) -> np.ndarray:
        indices = [int(i) for i in indices if 0 <= int(i) < matrix.shape[0]]
        if not indices:
            return np.zeros(matrix.shape[1], dtype=np.float64)
        return np.asarray(matrix[indices].mean(axis=0)).ravel()

    def _mean_svd_columns(self, indices) -> np.ndarray:
        indices = [int(i) for i in indices if 0 <= int(i) < self.svd.shape[1]]
        if not indices:
            return np.zeros(self.svd.shape[0], dtype=np.float64)
        return self.svd_norm[:, indices].mean(axis=1)

    # -------------------------------------------------------------- scores --
    def content_scores(self, liked_idx, disliked_idx) -> np.ndarray:
        """Cosine similarity to the liked mean minus half the disliked mean."""
        if not self.ok:
            return np.zeros(0)
        liked = list(liked_idx or [])
        disliked = list(disliked_idx or [])
        if not liked and not disliked:
            return np.zeros(self.X_norm.shape[0])
        liked_mean = self._mean_rows(self.X_norm, liked)
        disliked_mean = self._mean_rows(self.X_norm, disliked)
        scores = self.X_norm.dot(liked_mean)
        if disliked:
            scores = scores - 0.5 * self.X_norm.dot(disliked_mean)
        return np.asarray(scores).ravel()

    def svd_scores(self, liked_idx, disliked_idx) -> np.ndarray:
        """Item-item latent similarity using L2-normalised SVD columns."""
        if not self.ok:
            return np.zeros(0)
        liked = list(liked_idx or [])
        disliked = list(disliked_idx or [])
        if not liked and not disliked:
            return np.zeros(self.svd_norm.shape[1])
        liked_mean = self._mean_svd_columns(liked)
        disliked_mean = self._mean_svd_columns(disliked)
        scores = self.svd_norm.T.dot(liked_mean)
        if disliked:
            scores = scores - 0.5 * self.svd_norm.T.dot(disliked_mean)
        return np.asarray(scores).ravel()

    # ------------------------------------------------------------ recommend --
    def recommend_for_user(self, ratings: dict, k: int = 20, exclude=None,
                           preferred_genres=None) -> list[dict]:
        """Hybrid recommendations for a member.

        ratings: {ml_idx: 1..5}.  Liked >= 4, disliked <= 2, neutral ignored.
        """
        if not self.ok:
            return []
        exclude = set(int(i) for i in (exclude or set()))
        cleaned: dict[int, int] = {}
        for key, value in (ratings or {}).items():
            try:
                idx = int(key)
                score = int(value)
            except (TypeError, ValueError):
                continue
            if 0 <= idx < len(self.catalog) and 1 <= score <= 5:
                cleaned[idx] = score

        liked = [idx for idx, score in cleaned.items() if score >= 4]
        disliked = [idx for idx, score in cleaned.items() if score <= 2]
        blocked = set(cleaned) | exclude

        preferred = {g for g in (preferred_genres or []) if g}
        if not liked and not disliked:
            return self._cold_start(k, blocked, preferred)

        content = self.content_scores(liked, disliked)
        svd = self.svd_scores(liked, disliked)
        hybrid = (
            CONTENT_WEIGHT * _scale01(content)
            + SVD_WEIGHT * _scale01(svd)
            + POPULARITY_WEIGHT * self.popularity
        )

        if preferred:
            bonus = np.array(
                [0.03 if genre in preferred else 0.0 for genre in self.catalog["_genre"]]
            )
            hybrid = hybrid + bonus

        order = np.argsort(-hybrid)
        picked = [int(i) for i in order if int(i) not in blocked]
        picked = picked[: max(0, int(k))]
        if not picked:
            return []

        picked_scores = hybrid[picked]
        match_pct = np.clip(np.round(_scale01(picked_scores) * 100.0), 1, 100)

        results = []
        for position, idx in enumerate(picked):
            item = self.get_item(idx)
            if not item:
                continue
            item["match_pct"] = int(match_pct[position])
            item["reason"] = self._reason(idx, liked, cleaned, preferred)
            results.append(item)
        return results

    def _cold_start(self, k: int, blocked: set, preferred: set) -> list[dict]:
        if not self.ok:
            return []
        candidates = np.array(
            [i for i in range(len(self.catalog)) if i not in blocked], dtype=int
        )
        if candidates.size == 0:
            return []

        if preferred:
            mask = self.catalog["_genre"].isin(preferred).to_numpy()
            preferred_candidates = candidates[mask[candidates]]
            if preferred_candidates.size:
                candidates = preferred_candidates

        # Popularity order, diversified across category_grouped (max 2 per genre).
        order = candidates[np.argsort(-self.popularity[candidates])]
        picks: list[int] = []
        per_genre: dict[str, int] = {}
        for idx in order:
            genre = self.catalog["_genre"].iat[int(idx)]
            if per_genre.get(genre, 0) >= 2:
                continue
            picks.append(int(idx))
            per_genre[genre] = per_genre.get(genre, 0) + 1
            if len(picks) >= k:
                break
        if len(picks) < k:
            chosen = set(picks)
            for idx in order:
                if int(idx) in chosen:
                    continue
                picks.append(int(idx))
                if len(picks) >= k:
                    break

        results = []
        for idx in picks[: max(0, int(k))]:
            item = self.get_item(idx)
            if not item:
                continue
            item["match_pct"] = int(max(1, round(100 * self.popularity[idx])))
            item["reason"] = "Popular with readers"
            results.append(item)
        return results

    def _reason(self, idx: int, liked: list[int], ratings: dict[int, int],
                preferred: set) -> str:
        if liked:
            candidate = self.X_norm[idx]
            liked_matrix = self.X_norm[liked]
            similarities = np.asarray(candidate.dot(liked_matrix.T).todense()).ravel()
            if similarities.size:
                best_pos = int(np.argmax(similarities))
                best_idx = liked[best_pos]
                title = self.catalog["title"].iat[best_idx]
                stars = ratings.get(best_idx, 5)
                return f"Because you rated '{title}' {stars} stars"
        genre = self.catalog["_genre"].iat[idx]
        if genre in preferred:
            return f"Popular in {genre}"
        return "Popular with readers"

    # ------------------------------------------------------------- segments --
    def _profile_vector(self, profile) -> np.ndarray:
        size = len(self.genre_names)
        if isinstance(profile, dict):
            vector = np.zeros(size, dtype=np.float64)
            for genre, count in profile.items():
                position = self.genre_to_idx.get(genre)
                if position is not None:
                    try:
                        vector[position] += float(count)
                    except (TypeError, ValueError):
                        continue
            return vector
        vector = np.asarray(profile, dtype=np.float64).ravel()
        if vector.size != size:
            raise ValueError(f"profile must have {size} values, got {vector.size}")
        return vector

    def user_segment(self, profile) -> int | None:
        """Predict the ML cluster for a genre profile (dict or 27-vector)."""
        if not self.ok:
            return None
        try:
            vector = self._profile_vector(profile)
        except (TypeError, ValueError):
            logger.warning("Invalid segment profile", exc_info=True)
            return None
        if SEGMENT_NORMALISATION == "fraction":
            total = vector.sum()
            if total > 0:
                vector = vector / total
        elif SEGMENT_NORMALISATION == "l2":
            norm = np.linalg.norm(vector)
            if norm > 0:
                vector = vector / norm
        return int(self.kmeans.predict(vector.reshape(1, -1))[0])

    def similar_books(self, ml_idx: int, k: int = 20) -> list[dict]:
        if not self.ok:
            return []
        try:
            idx = int(ml_idx)
        except (TypeError, ValueError):
            return []
        if idx < 0 or idx >= len(self.catalog):
            return []
        content = np.asarray(self.X_norm.dot(self.X_norm[idx].T).todense()).ravel()
        svd = self.svd_norm.T.dot(self.svd_norm[:, idx])
        score = SIMILAR_CONTENT_WEIGHT * content + SIMILAR_SVD_WEIGHT * svd
        scaled = _scale01(score)
        order = np.argsort(-score)
        results = []
        for candidate in order:
            candidate = int(candidate)
            if candidate == idx:
                continue
            item = self.get_item(candidate)
            if not item:
                continue
            item["match_pct"] = int(max(1, round(scaled[candidate] * 100)))
            item["reason"] = f"Similar to '{self.catalog['title'].iat[idx]}'"
            results.append(item)
            if len(results) >= max(0, int(k)):
                break
        return results

    def books_like_cluster(self, cluster_id: int, k: int = 20) -> list[dict]:
        if not self.ok:
            return []
        try:
            cluster = int(cluster_id)
        except (TypeError, ValueError):
            return []
        try:
            centroid = np.clip(
                np.asarray(self.kmeans.cluster_centers_[cluster], dtype=float), 0, None
            )
        except (IndexError, TypeError):
            return []
        total = centroid.sum()
        if total > 0:
            centroid = centroid / total
        genre_weight = centroid[self.item_genre_idx]
        score = CLUSTER_GENRE_WEIGHT * genre_weight + CLUSTER_POPULARITY_WEIGHT * self.popularity
        scaled = _scale01(score)
        order = np.argsort(-score)
        results = []
        for idx in order[: max(0, int(k))]:
            item = self.get_item(int(idx))
            if not item:
                continue
            item["match_pct"] = int(max(1, round(scaled[int(idx)] * 100)))
            item["reason"] = self.catalog["_genre"].iat[int(idx)]
            results.append(item)
        return results

    # ------------------------------------------------------- library matching --
    def _catalog_isbn_map(self) -> dict[str, int]:
        mapping: dict[str, int] = {}
        for idx, row in self.catalog.iterrows():
            isbn = _normalise_isbn(row.get("isbn13"))
            if not isbn:
                continue
            mapping.setdefault(isbn, int(idx))
            if len(isbn) == 10:
                thirteen = _isbn10_to_13(isbn)
                if thirteen:
                    mapping.setdefault(thirteen, int(idx))
            elif len(isbn) == 13:
                mapping.setdefault(isbn[:9], int(idx))
        return mapping

    def _catalog_title_maps(self):
        by_title_author: dict[tuple[str, str], int] = {}
        by_title: dict[str, int | None] = {}
        for idx, row in self.catalog.iterrows():
            title = _normalise_title(row.get("title"))
            if not title:
                continue
            author = _normalise_author(row.get("primary_author") or row.get("author"))
            by_title_author.setdefault((title, author), int(idx))
            first_author = author.split(" ")[0] if author else ""
            if first_author:
                by_title_author.setdefault((title, first_author), int(idx))
            if title in by_title:
                by_title[title] = None  # ambiguous
            else:
                by_title[title] = int(idx)
        return by_title_author, by_title

    def match_books(self, books: list[dict]) -> list[tuple[int, int | None, str]]:
        """Return [(book_id, ml_idx|None, method)] for library book rows."""
        isbn_map = self._catalog_isbn_map()
        by_title_author, by_title = self._catalog_title_maps()
        results = []
        for book in books:
            book_id = book["book_id"]
            isbn = _normalise_isbn(book.get("isbn"))
            match = None
            method = "unmatched"
            if isbn:
                if isbn in isbn_map:
                    match = isbn_map[isbn]
                    method = "isbn"
                elif len(isbn) == 10:
                    thirteen = _isbn10_to_13(isbn)
                    if thirteen and thirteen in isbn_map:
                        match = isbn_map[thirteen]
                        method = "isbn10->13"
                elif len(isbn) == 13 and isbn[:9] in isbn_map:
                    match = isbn_map[isbn[:9]]
                    method = "isbn-prefix"
            if match is None:
                title = _normalise_title(book.get("title"))
                author = _normalise_author(book.get("author"))
                if title and (title, author) in by_title_author:
                    match = by_title_author[(title, author)]
                    method = "title+author"
                else:
                    first_author = author.split(" ")[0] if author else ""
                    if title and first_author and (title, first_author) in by_title_author:
                        match = by_title_author[(title, first_author)]
                        method = "title+author"
                    elif title and by_title.get(title) is not None:
                        match = by_title[title]
                        method = "title"
            results.append((book_id, match, method))
        return results

    def match_library_books(self, verbose: bool = False) -> dict:
        """Map every library book to a catalog index and persist books.ml_idx."""
        if not self.ok:
            logger.warning("Recommender unavailable; cannot match library books")
            return {"total": 0, "matched": 0, "unmatched": [], "detail": []}
        from db import query_all, get_connection

        books = query_all("SELECT book_id, title, author, isbn FROM books ORDER BY book_id")
        matches = self.match_books(books)
        used: set[int] = set()
        detail = []
        conn = get_connection()
        try:
            cur = conn.cursor()
            for book, (book_id, ml_idx, method) in zip(books, matches):
                if ml_idx is not None and ml_idx in used:
                    ml_idx, method = None, "duplicate-match"
                if ml_idx is not None:
                    used.add(ml_idx)
                cur.execute("UPDATE books SET ml_idx = %s WHERE book_id = %s", (ml_idx, book_id))
                detail.append(
                    {"book_id": book_id, "title": book["title"], "ml_idx": ml_idx, "method": method}
                )
            conn.commit()
        finally:
            conn.close()

        unmatched = [row["title"] for row in detail if row["ml_idx"] is None]
        result = {
            "total": len(detail),
            "matched": len(detail) - len(unmatched),
            "unmatched": unmatched,
            "detail": detail,
        }
        if verbose:
            print(f"Total library books: {result['total']}")
            print(f"Matched: {result['matched']}")
            print(f"Unmatched: {len(unmatched)}")
            for title in unmatched:
                print(f"  - {title}")
        return result

    def match_single_book(self, book_id: int) -> int | None:
        """Match one library row (used after an admin adds/edits a book)."""
        if not self.ok:
            return None
        from db import query_one, get_connection

        book = query_one(
            "SELECT book_id, title, author, isbn FROM books WHERE book_id = %s", (book_id,)
        )
        if not book:
            return None
        _book_id, ml_idx, _method = self.match_books([book])[0]
        if ml_idx is not None:
            conflict = query_one(
                "SELECT book_id FROM books WHERE ml_idx = %s AND book_id <> %s",
                (ml_idx, book_id),
            )
            if conflict:
                ml_idx = None
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("UPDATE books SET ml_idx = %s WHERE book_id = %s", (ml_idx, book_id))
            conn.commit()
        finally:
            conn.close()
        return ml_idx


def _clean_text(value) -> str:
    try:
        if value is None or pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value)


def _safe_int(value):
    try:
        if value is None or pd.isna(value):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_float(value):
    try:
        if value is None or pd.isna(value):
            return None
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


# ----------------------------------------------------------- singleton ----
_recommender: Recommender | None = None
_recommender_lock = threading.Lock()


def get_recommender() -> Recommender:
    """Return the process-wide Recommender, loading it once under a lock."""
    global _recommender
    if _recommender is None:
        with _recommender_lock:
            if _recommender is None:
                _recommender = Recommender()
    return _recommender
