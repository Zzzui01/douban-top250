# -*- coding: utf-8 -*-
"""控制台报表：按终端显示宽度对齐的预览表格。"""

from __future__ import annotations

import sys
import unicodedata
from typing import List, Sequence, Tuple

from .models import Movie

# (字段, 中文表头, 列宽, 对齐)
PREVIEW_COLUMNS: Sequence[Tuple[str, str, int, str]] = (
    ("rank", "排名", 4, "right"),
    ("title", "片名", 22, "left"),
    ("year", "年份", 6, "left"),
    ("rating", "评分", 6, "right"),
    ("votes", "评价人数", 10, "right"),
    ("quote", "短评", 28, "left"),
)


def display_width(text: object) -> int:
    """按终端显示宽度计算字符串宽度（中日韩字符算 2 列）。"""
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in str(text))


def pad(text: object, width: int, align: str = "left") -> str:
    text = str(text)
    space = max(0, width - display_width(text))
    return (" " * space + text) if align == "right" else (text + " " * space)


def render_table(movies: List[Movie], limit: int = 10) -> str:
    """生成预览表格文本（便于测试与重定向输出）。"""
    lines = ["=" * 100]
    lines.append(" | ".join(pad(name, width, align) for _, name, width, align in PREVIEW_COLUMNS))
    lines.append("-" * 100)
    for movie in movies[:limit]:
        lines.append(" | ".join(
            pad(getattr(movie, key), width, align) for key, _, width, align in PREVIEW_COLUMNS
        ))
    if len(movies) > limit:
        lines.append("... 共 {} 条，仅预览前 {} 条".format(len(movies), limit))
    lines.append("=" * 100)
    return "\n".join(lines)


def print_table(movies: List[Movie], limit: int = 10, stream=None) -> None:
    """打印预览表格（直接写 stdout，不经过日志格式）。"""
    stream = stream or sys.stdout
    stream.write("\n" + render_table(movies, limit=limit) + "\n\n")


__all__ = ["print_table", "render_table", "display_width", "pad", "PREVIEW_COLUMNS"]
