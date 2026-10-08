# -*- coding: utf-8 -*-
"""存取层：CSV / JSON 的读写与格式约定。

CSV 使用 utf-8-sig（Excel 直接双击不乱码），JSON 使用 utf-8 且不转义中文。
"""

from __future__ import annotations

import csv
import json
import time
from pathlib import Path
from typing import Dict, List, Optional, Union

from .config import SOURCE
from .logging_setup import get_logger
from .models import MOVIE_FIELDS, Movie

logger = get_logger(__name__)

PathLike = Union[str, Path]


def ensure_parent(path: PathLike) -> Path:
    """确保父目录存在，返回 Path。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def save_csv(movies: List[Movie], path: PathLike) -> Path:
    """保存为 CSV（utf-8-sig）。"""
    target = ensure_parent(path)
    with open(str(target), "w", newline="", encoding="utf-8-sig") as fp:
        writer = csv.DictWriter(fp, fieldnames=list(MOVIE_FIELDS))
        writer.writeheader()
        for movie in movies:
            writer.writerow(movie.as_row())
    logger.info("已保存 CSV -> %s（%d 条）", target, len(movies))
    return target


def build_payload(movies: List[Movie], source: str = SOURCE, crawled_at: Optional[str] = None) -> Dict[str, object]:
    return {
        "source": source,
        "crawled_at": crawled_at or time.strftime("%Y-%m-%d %H:%M:%S"),
        "total": len(movies),
        "movies": [movie.as_row() for movie in movies],
    }


def save_json(
    movies: List[Movie],
    path: PathLike,
    source: str = SOURCE,
    crawled_at: Optional[str] = None,
) -> Path:
    """保存为 JSON（含来源、抓取时间与总数）。"""
    target = ensure_parent(path)
    payload = build_payload(movies, source=source, crawled_at=crawled_at)
    with open(str(target), "w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=2)
    logger.info("已保存 JSON -> %s（%d 条）", target, len(movies))
    return target


def load_json(path: PathLike) -> Dict[str, object]:
    """读取 JSON 结果文件（兼容 {"movies": [...]} 与裸列表两种结构）。"""
    with open(str(path), encoding="utf-8") as fp:
        payload = json.load(fp)
    if isinstance(payload, list):
        payload = {"source": SOURCE, "crawled_at": None, "total": len(payload), "movies": payload}
    if not isinstance(payload, dict) or "movies" not in payload:
        raise ValueError("JSON 结构不符合预期（缺少 movies 字段）：{}".format(path))
    return payload


def load_movies(path: PathLike) -> List[Movie]:
    """读取 JSON 并转为 Movie 列表。"""
    payload = load_json(path)
    movies = [Movie.from_row(row) for row in payload.get("movies") or []]
    logger.info("已从 %s 读取 %d 条记录", path, len(movies))
    return movies


def merge_movies(*groups: Optional[List[Movie]]) -> List[Movie]:
    """按排名合并多批抓取结果（同名排名后面的覆盖前面的），返回升序列表。

    用于断点续传/增量刷新：分几次只抓到部分页，也能拼出一份完整数据。
    """
    merged: Dict[int, Movie] = {}
    for group in groups:
        for movie in group or []:
            merged[int(movie.rank)] = movie
    return [merged[rank] for rank in sorted(merged)]


__all__ = [
    "save_csv",
    "save_json",
    "load_json",
    "load_movies",
    "merge_movies",
    "build_payload",
    "ensure_parent",
]
