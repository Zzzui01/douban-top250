# -*- coding: utf-8 -*-
"""数据模型：Movie 数据类与字段定义（CSV / JSON / Excel / 清洗共用同一份字段表）。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Dict, List

# 字段顺序即导出顺序
MOVIE_FIELDS = (
    "rank",
    "title",
    "foreign_title",
    "aliases",
    "year",
    "country",
    "genres",
    "rating",
    "votes",
    "quote",
    "staff",
    "url",
    "cover",
)

# 中文表头
FIELD_LABELS = {
    "rank": "排名",
    "title": "片名",
    "foreign_title": "外文名",
    "aliases": "别名",
    "year": "年份",
    "country": "国家/地区",
    "genres": "类型",
    "rating": "评分",
    "votes": "评价人数",
    "quote": "短评",
    "staff": "导演/主演",
    "url": "详情页链接",
    "cover": "海报链接",
}


@dataclass
class Movie:
    """单部电影的信息。"""

    rank: int = 0                 # 排名 1-250
    title: str = ""               # 中文片名
    foreign_title: str = ""       # 外文名
    aliases: str = ""             # 别名（其他译名）
    year: str = ""                # 年份
    country: str = ""             # 国家 / 地区
    genres: str = ""              # 类型
    rating: float = 0.0           # 评分
    votes: int = 0                # 评价人数
    quote: str = ""               # 短评（一句话评价）
    staff: str = ""               # 导演 / 编剧 / 主演
    url: str = ""                 # 详情页链接
    cover: str = ""               # 海报图片链接

    def as_row(self) -> Dict[str, object]:
        """按 MOVIE_FIELDS 顺序导出为 dict。"""
        data = asdict(self)
        return {key: data[key] for key in MOVIE_FIELDS}

    @classmethod
    def from_row(cls, row: Dict[str, object]) -> "Movie":
        """从 dict 构造（忽略未知字段，缺失字段用默认值）。"""
        kwargs = {key: row[key] for key in MOVIE_FIELDS if key in row and row[key] is not None}
        for key in ("rank", "votes"):
            if key in kwargs:
                try:
                    kwargs[key] = int(float(kwargs[key]))
                except (TypeError, ValueError):
                    kwargs[key] = 0
        if "rating" in kwargs:
            try:
                kwargs["rating"] = float(kwargs["rating"])
            except (TypeError, ValueError):
                kwargs["rating"] = 0.0
        return cls(**kwargs)


def rows_from_movies(movies: List[Movie]) -> List[Dict[str, object]]:
    return [movie.as_row() for movie in movies]


def movies_from_rows(rows: List[Dict[str, object]]) -> List[Movie]:
    return [Movie.from_row(row) for row in rows]


def to_native(value: object) -> object:
    """把 pandas / numpy 标量转成原生 Python 类型（NaN 转 None）。

    DataFrame 经过清洗后，数值列是 numpy.int64 / numpy.float64，布尔列是 numpy.bool_，
    直接写 JSON 会抛 TypeError，写 Excel 可能拿到不认识的类型。导出前统一转换。
    """
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        if isinstance(value, float) and value != value:   # NaN
            return None
        return value
    item = getattr(value, "item", None)                   # numpy 标量
    if callable(item):
        try:
            return item()
        except Exception:  # pragma: no cover - 极少见
            pass
    try:
        if value != value:                                # 兜底判断 NaN
            return None
    except Exception:  # pragma: no cover - 自定义对象可能不支持比较
        pass
    return str(value)
