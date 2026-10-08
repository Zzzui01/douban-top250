# -*- coding: utf-8 -*-
"""Pandas 清洗测试：类型转换、脏数据剔除、派生列与落盘。"""

from __future__ import annotations

import json

import pytest

from douban_top250.clean import (
    CleanReport,
    clean_dataframe,
    clean_movies,
    decade_of,
    load_raw_frame,
    movies_to_frame,
    rating_band,
    save_clean,
    split_values,
)
from douban_top250.config import CLEAN_CSV_NAME, CLEAN_JSON_NAME
from douban_top250.models import MOVIE_FIELDS, Movie

pandas = pytest.importorskip("pandas")


# --------------------------------------------------------------------------- #
# 工具函数
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "value,expected",
    [
        ("剧情 爱情", ["剧情", "爱情"]),
        ("中国大陆 中国香港", ["中国大陆", "中国香港"]),
        ("1985 / 中国大陆", ["中国大陆"]),
        ("1964(中国大陆) / 1978(中国大陆) / 中国大陆", ["中国大陆"]),
        ("剧情、爱情|喜剧", ["剧情", "爱情", "喜剧"]),
        (["剧情", "剧情", " 爱情 "], ["剧情", "爱情"]),
        ("", []),
        (None, []),
    ],
)
def test_split_values(value, expected):
    assert split_values(value) == expected


def test_decade_and_rating_band():
    assert decade_of(1994) == "1990 年代"
    assert decade_of(2003) == "2000 年代"
    assert decade_of(0) == "未知年代"
    assert rating_band(9.7) == "9.5 及以上"
    assert rating_band(9.0) == "9.0 - 9.4"
    assert rating_band(8.5) == "8.5 - 8.9"
    assert rating_band(8.0) == "8.5 以下"


# --------------------------------------------------------------------------- #
# 帧构建与清洗
# --------------------------------------------------------------------------- #
def test_movies_to_frame_has_expected_columns(sample_movies):
    frame = movies_to_frame(sample_movies)

    assert list(frame.columns) == list(MOVIE_FIELDS)
    assert len(frame) == 3
    assert frame.loc[0, "title"] == "肖申克的救赎"


def test_movies_to_frame_handles_empty_input():
    frame = movies_to_frame([])

    assert len(frame) == 0
    assert list(frame.columns) == list(MOVIE_FIELDS)


def test_clean_dataframe_drops_dirty_rows():
    frame = pandas.DataFrame(
        [
            {"rank": 1, "title": "正常", "rating": 9.1, "votes": 100, "year": 1994},
            {"rank": 1, "title": "重复排名", "rating": 9.0, "votes": 90, "year": 1995},
            {"rank": 0, "title": "排名异常", "rating": 8.8, "votes": 80, "year": 1996},
            {"rank": 4, "title": "   ", "rating": 8.7, "votes": 70, "year": 1997},
        ]
    )

    cleaned, report = clean_dataframe(frame)

    assert report.total_in == 4
    assert report.total_out == 1
    assert report.dropped_duplicates == 1
    assert report.dropped_invalid_rank == 1
    assert report.dropped_missing_title == 1
    assert report.dropped == 3
    assert cleaned.loc[0, "title"] == "正常"


def test_clean_dataframe_fills_types_and_derives_columns(sample_movies):
    frame = movies_to_frame(sample_movies)
    frame.loc[0, "rating"] = None
    frame.loc[0, "votes"] = None
    frame.loc[0, "year"] = None

    cleaned, report = clean_dataframe(frame)

    assert report.filled_rating == 1
    assert report.filled_votes == 1
    assert report.filled_year == 1
    assert cleaned["rating"].dtype == float
    assert str(cleaned["votes"].dtype) == "int64"
    assert cleaned.loc[0, "decade"] == "未知年代"
    assert cleaned.loc[0, "rating_band"] == "8.5 以下"      # 评分缺失按 0 处理
    assert cleaned.loc[1, "decade"] == "1990 年代"
    assert cleaned.loc[1, "genre_count"] == 3               # 剧情 爱情 同性
    assert cleaned.loc[1, "country_count"] == 2             # 中国大陆 中国香港
    assert cleaned.loc[1, "votes_wan"] == pytest.approx(221.0)
    assert bool(cleaned.loc[1, "has_quote"]) is True
    assert bool(cleaned.loc[2, "has_quote"]) is False       # 无名之辈没有短评


def test_clean_dataframe_on_empty_frame():
    cleaned, report = clean_dataframe(pandas.DataFrame(columns=list(MOVIE_FIELDS)))

    assert len(cleaned) == 0
    assert report.total_out == 0


def test_clean_movies_end_to_end(sample_movies):
    cleaned, report = clean_movies(sample_movies)

    assert report.total_in == report.total_out == 3
    assert list(cleaned["rank"]) == [1, 2, 3]


def test_clean_report_describe_and_dict():
    report = CleanReport(total_in=10, total_out=8, dropped_duplicates=2, filled_rating=1)
    report.notes.append("示例备注")

    assert report.dropped == 2
    assert report.as_dict()["dropped"] == 2
    text = report.describe()
    assert "输入记录：10" in text
    assert "输出记录：8" in text
    assert "示例备注" in text


# --------------------------------------------------------------------------- #
# 落盘
# --------------------------------------------------------------------------- #
def test_save_clean_writes_csv_and_json(tmp_path, sample_movies):
    cleaned, report = clean_movies(sample_movies)

    paths = save_clean(cleaned, tmp_path, report)

    assert paths["csv"].name == CLEAN_CSV_NAME
    assert paths["json"].name == CLEAN_JSON_NAME
    assert paths["csv"].read_bytes().startswith(b"\xef\xbb\xbf")

    payload = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert payload["total"] == 3
    assert payload["report"]["total_in"] == 3
    assert payload["movies"][0]["decade"] == "1990 年代"
    assert "cleaned_at" in payload


def test_load_raw_frame_from_json(tmp_path, sample_movies):
    from douban_top250.storage import save_json

    path = save_json(sample_movies, tmp_path / "raw.json")

    frame = load_raw_frame(path)

    assert len(frame) == 3
    assert list(frame.columns) == list(MOVIE_FIELDS)


def test_clean_result_can_be_read_back_as_movies(tmp_path, sample_movies):
    """清洗结果必须仍能被 Movie.from_row 消费（CLI 与 Excel 都依赖这一点）。"""
    cleaned, report = clean_movies(sample_movies)
    paths = save_clean(cleaned, tmp_path, report)

    payload = json.loads(paths["json"].read_text(encoding="utf-8"))
    movies = [Movie.from_row(row) for row in payload["movies"]]

    assert movies[0].title == "肖申克的救赎"
    assert movies[1].votes == 2210000
