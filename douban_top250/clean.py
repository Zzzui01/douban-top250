# -*- coding: utf-8 -*-
"""Pandas 清洗与分析层。

把抓取到的原始记录（可能有空值、类型混杂、重复排名）整理成可分析的宽表，
并派生出评分档位、年代、类型/地区列表等便于统计的列。

对外只暴露纯函数，方便在 pytest 里直接断言 DataFrame 内容。
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Union

from .config import CLEAN_CSV_NAME, CLEAN_JSON_NAME, OUTPUT_DIR
from .exceptions import CleanError
from .logging_setup import get_logger
from .models import MOVIE_FIELDS, Movie, to_native
from .storage import ensure_parent

logger = get_logger(__name__)

PathLike = Union[str, Path]

#: 评分档位（左闭右开，最后一档无上界），顺序即展示顺序
RATING_BINS = (9.5, 9.0, 8.5, 0.0)
RATING_BANDS = ("9.5 及以上", "9.0 - 9.4", "8.5 - 8.9", "8.5 以下")

#: 形如 "1964(中国大陆)" 的合拍片地区写法，取出括号内的地区名
_PAREN_TOKEN = re.compile(r"^\d{4}\s*\(([^)]+)\)$")

#: 派生列，供 Excel/报表复用
DERIVED_FIELDS = (
    "decade",
    "rating_band",
    "genre_list",
    "genre_count",
    "country_list",
    "country_count",
    "votes_wan",
    "has_quote",
)


@dataclass
class CleanReport:
    """清洗报告：记录每一步丢了多少、补了多少，便于解释数据差异。"""

    total_in: int = 0
    total_out: int = 0
    dropped_duplicates: int = 0
    dropped_invalid_rank: int = 0
    dropped_missing_title: int = 0
    filled_rating: int = 0
    filled_votes: int = 0
    filled_year: int = 0
    genres_expanded: int = 0
    countries_expanded: int = 0
    notes: List[str] = field(default_factory=list)

    @property
    def dropped(self) -> int:
        return self.dropped_duplicates + self.dropped_invalid_rank + self.dropped_missing_title

    def as_dict(self) -> Dict[str, object]:
        data = asdict(self)
        data["dropped"] = self.dropped
        return data

    def describe(self) -> str:
        lines = [
            "清洗报告",
            "  输入记录：{}".format(self.total_in),
            "  输出记录：{}".format(self.total_out),
            "  剔除合计：{}（重复 {} / 排名异常 {} / 缺标题 {}）".format(
                self.dropped, self.dropped_duplicates, self.dropped_invalid_rank, self.dropped_missing_title
            ),
            "  补默认值：评分 {} / 评价人数 {} / 年份 {}".format(
                self.filled_rating, self.filled_votes, self.filled_year
            ),
            "  多值拆分：类型 {} 条 / 地区 {} 条".format(self.genres_expanded, self.countries_expanded),
        ]
        lines.extend("  备注：{}".format(note) for note in self.notes)
        return "\n".join(lines)


# --------------------------------------------------------------------------- #
# 工具函数
# --------------------------------------------------------------------------- #
def _require_pandas():
    """延迟导入 pandas，未安装时给出可执行的安装提示。"""
    try:
        import pandas  # noqa: F401
    except ImportError as exc:  # pragma: no cover - 取决于运行环境
        raise CleanError(
            "需要 pandas 才能执行清洗，请先安装：pip install pandas\n"
            "（当前解释器：{}）".format(__import__("sys").executable)
        ) from exc
    return pandas


def movies_to_frame(movies: List[Movie]):
    """把 Movie 列表转成 DataFrame；空输入也返回带表头的空表。"""
    pandas = _require_pandas()
    rows = [movie.as_row() for movie in movies]
    frame = pandas.DataFrame(rows, columns=list(MOVIE_FIELDS))
    if frame.empty:
        logger.warning("待清洗数据为空")
    return frame


def rating_band(rating: float) -> str:
    """把评分映射到档位标签。"""
    for threshold, label in zip(RATING_BINS, RATING_BANDS):
        if rating >= threshold:
            return label
    return RATING_BANDS[-1]


def decade_of(year: int) -> str:
    """把年份映射到年代标签，如 1994 -> '1990 年代'。"""
    if not year:
        return "未知年代"
    return "{} 年代".format(year // 10 * 10)


def split_values(value: object) -> List[str]:
    """把多值字段统一拆成去重列表。

    豆瓣的写法并不统一：类型是空格分隔（"剧情 爱情"），地区既可能是空格
    （"中国大陆 中国香港"）、也可能是斜杠（"1985 / 中国大陆"），合拍片还会
    带上年份（"1964(中国大陆)"）。这里统一按空白与斜杠切分，把
    "1964(中国大陆)" 还原成 "中国大陆"，并丢弃孤立的 4 位年份，避免产生假分类。
    """
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        items = [str(item) for item in value]
    else:
        text = str(value).replace("\xa0", " ")
        for separator in ("、", "/", "|", ",", "，"):
            text = text.replace(separator, " ")
        items = text.split()

    cleaned: List[str] = []
    for item in items:
        item = item.strip()
        matched = _PAREN_TOKEN.match(item)
        if matched:
            item = matched.group(1).strip()
        elif re.fullmatch(r"(19|20)\d{2}", item):
            continue  # "1985 / 中国大陆" 里的裸年份不是有效分类
        if item and item not in cleaned:
            cleaned.append(item)
    return cleaned


# --------------------------------------------------------------------------- #
# 清洗主流程
# --------------------------------------------------------------------------- #
def clean_dataframe(frame, report: Optional[CleanReport] = None):
    """对原始 DataFrame 做类型转换、去重与派生列计算。"""
    pandas = _require_pandas()
    report = report or CleanReport()
    report.total_in = int(len(frame))

    if frame.empty:
        report.total_out = 0
        return frame.copy(), report

    df = frame.copy()

    # 0) 补齐缺失列，容忍外部传入的残缺数据
    missing_columns = [col for col in MOVIE_FIELDS if col not in df.columns]
    if missing_columns:
        for col in missing_columns:
            df[col] = None
        report.notes.append("补齐缺失列：{}".format("、".join(missing_columns)))

    # 1) 类型转换：数值列强制转数字，转不了的记为缺失
    before_missing = {"rating": int(df["rating"].isna().sum()), "votes": 0, "year": 0}
    df["rating"] = pandas.to_numeric(df["rating"], errors="coerce")
    df["votes"] = pandas.to_numeric(df["votes"], errors="coerce")
    df["year"] = pandas.to_numeric(df["year"], errors="coerce")
    df["rank"] = pandas.to_numeric(df["rank"], errors="coerce")

    # 2) 文本列去空白、统一空值为 NaN，避免出现 "nan"/"None" 字符串
    text_columns = [col for col in MOVIE_FIELDS if col not in ("rank", "rating", "votes", "year")]
    for col in text_columns:
        df[col] = (
            df[col]
            .astype("object")
            .where(df[col].notna(), None)
            .map(lambda value: str(value).strip() if value is not None else None)
        )
        df[col] = df[col].replace({"": None, "nan": None, "None": None})

    # 3) 剔除脏数据：无排名、无标题、重复排名
    invalid_rank = df["rank"].isna() | (df["rank"] <= 0)
    if int(invalid_rank.sum()):
        report.dropped_invalid_rank += int(invalid_rank.sum())
        logger.warning("剔除排名异常的记录 %d 条", int(invalid_rank.sum()))
        df = df[~invalid_rank]

    missing_title = df["title"].isna() | (df["title"].astype(str).str.strip() == "")
    if int(missing_title.sum()):
        report.dropped_missing_title += int(missing_title.sum())
        logger.warning("剔除缺少片名的记录 %d 条", int(missing_title.sum()))
        df = df[~missing_title]

    before_dedupe = len(df)
    df = df.sort_values("rank").drop_duplicates(subset=["rank"], keep="first")
    report.dropped_duplicates += int(before_dedupe - len(df))
    if report.dropped_duplicates:
        logger.warning("剔除重复排名记录 %d 条", report.dropped_duplicates)

    # 4) 缺失值补默认值并记录
    report.filled_rating = int(df["rating"].isna().sum())
    report.filled_votes = int(df["votes"].isna().sum())
    report.filled_year = int(df["year"].isna().sum())
    if report.filled_rating or report.filled_votes or report.filled_year:
        logger.info(
            "缺失值补 0：评分 %d / 评价人数 %d / 年份 %d",
            report.filled_rating, report.filled_votes, report.filled_year,
        )
    df["rating"] = df["rating"].fillna(0.0).astype(float)
    df["votes"] = df["votes"].fillna(0).astype("int64")
    df["year"] = df["year"].fillna(0).astype("int64")
    df["rank"] = df["rank"].astype("int64")

    # 5) 派生列
    df["decade"] = df["year"].map(decade_of)
    df["rating_band"] = df["rating"].map(rating_band)

    genre_lists = df["genres"].map(split_values)
    country_lists = df["country"].map(split_values)
    df["genre_list"] = genre_lists.map(lambda items: " / ".join(items))
    df["country_list"] = country_lists.map(lambda items: " / ".join(items))
    df["genre_count"] = genre_lists.map(len).astype("int64")
    df["country_count"] = country_lists.map(len).astype("int64")
    report.genres_expanded = int((df["genre_count"] > 1).sum())
    report.countries_expanded = int((df["country_count"] > 1).sum())

    df["votes_wan"] = (df["votes"] / 10000.0).round(1)
    df["has_quote"] = df["quote"].notna()

    df = df.reset_index(drop=True)
    report.total_out = int(len(df))
    report.notes.append("评分缺失按 0 处理，统计时可用 rating > 0 过滤")
    logger.info("清洗完成：%d -> %d 条", report.total_in, report.total_out)
    return df, report


def clean_movies(movies: List[Movie]):
    """Movie 列表 -> (清洗后的 DataFrame, CleanReport)。"""
    frame = movies_to_frame(movies)
    return clean_dataframe(frame)


def load_raw_frame(path: PathLike):
    """从 JSON 结果文件读取原始 DataFrame（无需联网）。"""
    pandas = _require_pandas()
    from .storage import load_json

    payload = load_json(path)
    frame = pandas.DataFrame(payload.get("movies") or [], columns=list(MOVIE_FIELDS))
    logger.info("已加载原始数据 %d 条（来源：%s）", len(frame), path)
    return frame


def save_clean(frame, outdir: PathLike = OUTPUT_DIR, report: Optional[CleanReport] = None) -> Dict[str, Path]:
    """把清洗结果写出 CSV + JSON，返回文件路径字典。"""
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    # numpy / pandas 标量先转成原生类型：JSON 才能序列化，Excel 也才能直接写入
    records = [
        {key: to_native(value) for key, value in row.items()}
        for row in frame.to_dict(orient="records")
    ]

    csv_path = ensure_parent(outdir / CLEAN_CSV_NAME)
    frame.to_csv(str(csv_path), index=False, encoding="utf-8-sig")
    logger.info("已保存清洗后 CSV -> %s（%d 条）", csv_path, len(frame))

    payload: Dict[str, object] = {
        "source": "douban_top250 清洗结果",
        "cleaned_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total": len(records),
        "movies": records,
    }
    if report is not None:
        payload["report"] = report.as_dict()

    json_path = ensure_parent(outdir / CLEAN_JSON_NAME)
    with open(str(json_path), "w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=2)
    logger.info("已保存清洗后 JSON -> %s（%d 条）", json_path, len(records))

    return {"csv": csv_path, "json": json_path}


__all__ = [
    "CleanReport",
    "RATING_BINS",
    "RATING_BANDS",
    "DERIVED_FIELDS",
    "clean_dataframe",
    "clean_movies",
    "load_raw_frame",
    "movies_to_frame",
    "save_clean",
    "decade_of",
    "rating_band",
    "split_values",
]
