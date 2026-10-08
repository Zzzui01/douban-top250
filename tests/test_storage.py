# -*- coding: utf-8 -*-
"""存取层测试：CSV/JSON 往返、格式兼容与错误处理。"""

from __future__ import annotations

import csv
import json

import pytest

from douban_top250.models import MOVIE_FIELDS, Movie
from douban_top250.storage import build_payload, load_json, load_movies, save_csv, save_json


def test_save_json_round_trip(tmp_path, sample_movies, sample_payload):
    target = save_json(sample_movies, tmp_path / "out.json", source=sample_payload["source"],
                       crawled_at=sample_payload["crawled_at"])

    payload = load_json(target)
    assert payload["total"] == 3
    assert payload["source"] == sample_payload["source"]
    assert payload["crawled_at"] == "2026-01-01 00:00:00"
    assert payload["movies"][0]["title"] == "肖申克的救赎"

    # 中文不应被转义，便于人工查看
    raw = target.read_text(encoding="utf-8")
    assert "肖申克的救赎" in raw
    assert "\\u" not in raw


def test_load_movies_returns_objects(tmp_path, sample_movies):
    target = save_json(sample_movies, tmp_path / "out.json")

    movies = load_movies(target)

    assert [movie.rank for movie in movies] == [1, 2, 3]
    assert isinstance(movies[0], Movie)
    assert movies[1].genres == "剧情 爱情 同性"


def test_load_json_accepts_bare_list(tmp_path):
    path = tmp_path / "raw.json"
    path.write_text(json.dumps([{"rank": 1, "title": "测试"}], ensure_ascii=False), encoding="utf-8")

    payload = load_json(path)

    assert payload["total"] == 1
    assert payload["movies"][0]["title"] == "测试"


def test_load_json_rejects_unexpected_structure(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"foo": "bar"}), encoding="utf-8")

    with pytest.raises(ValueError):
        load_json(path)


def test_save_csv_is_excel_friendly(tmp_path, sample_movies):
    target = save_csv(sample_movies, tmp_path / "nested" / "out.csv")

    assert target.is_file()
    assert target.read_bytes().startswith(b"\xef\xbb\xbf")   # utf-8-sig BOM，Excel 直接双击不乱码
    with open(str(target), newline="", encoding="utf-8-sig") as fp:
        rows = list(csv.DictReader(fp))
    assert list(rows[0].keys()) == list(MOVIE_FIELDS)
    assert len(rows) == 3
    assert rows[0]["votes"] == "3347760"


def test_build_payload_contains_metadata(sample_movies):
    payload = build_payload(sample_movies, source="unit-test", crawled_at="2026-02-02 02:02:02")

    assert payload["source"] == "unit-test"
    assert payload["crawled_at"] == "2026-02-02 02:02:02"
    assert payload["total"] == 3
    assert len(payload["movies"]) == 3


# --------------------------------------------------------------------------- #
# 合并（断点续传）
# --------------------------------------------------------------------------- #
def test_merge_movies_prefers_later_group_and_sorts():
    from douban_top250.models import Movie
    from douban_top250.storage import merge_movies

    old = [Movie(rank=2, title="旧二号"), Movie(rank=1, title="旧一号")]
    new = [Movie(rank=2, title="新二号"), Movie(rank=3, title="新三号")]

    merged = merge_movies(old, new)

    assert [movie.rank for movie in merged] == [1, 2, 3]
    assert [movie.title for movie in merged] == ["旧一号", "新二号", "新三号"]


def test_merge_movies_tolerates_missing_groups():
    from douban_top250.models import Movie
    from douban_top250.storage import merge_movies

    assert merge_movies() == []
    assert merge_movies(None, []) == []
    assert [movie.rank for movie in merge_movies(None, [Movie(rank=5)])] == [5]
