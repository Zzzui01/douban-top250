# -*- coding: utf-8 -*-
"""列表页解析：把 Top250 列表 HTML 转成 Movie 列表。

兼容豆瓣新旧两版页面结构：
  新版：评分容器是无 class 的 <div>，评价人数在裸 <span> 里，短评在 <p class="quote"><span>
  旧版：<div class="star"> + <span property="v:votes"> + <span class="inq">
"""

from __future__ import annotations

import re
from typing import List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .config import BASE_URL
from .logging_setup import get_logger
from .models import Movie

logger = get_logger(__name__)


def _text(node: Optional[Tag]) -> str:
    """取节点文本，节点为空返回空串。"""
    return node.get_text(strip=True) if node else ""


def clean_text(text: str) -> str:
    """合并多余空白，去掉首尾斜杠与空白（豆瓣用 &nbsp;/&nbsp; 分隔片名与别名）。"""
    text = (text or "").replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"^[\s/]+|[\s/]+$", "", text).strip()


def match_year(text: str) -> str:
    """从 "(1994)" 之类的文本中取出年份，取不到就原样返回。"""
    match = re.search(r"(19|20)\d{2}", text or "")
    return match.group(0) if match else (text or "").strip()


def _parse_votes(item: Tag, rating_node: Optional[Tag]) -> int:
    """解析评价人数，兼容新旧结构。"""
    votes_node = item.select_one('span[property="v:votes"]')
    if votes_node is not None:
        votes_text = _text(votes_node)
    else:
        # 评分所在的外层容器（新版是 rating_num 的父 div，旧版是 div.star）
        box = (rating_node.parent if rating_node is not None else None) or item.select_one("div.star")
        votes_text = box.get_text(" ", strip=True) if box is not None else item.get_text(" ", strip=True)
    match = re.search(r"([\d,]+)\s*人评价", votes_text) or re.search(r"([\d,]+)", votes_text)
    return int(match.group(1).replace(",", "")) if match else 0


def _parse_meta(item: Tag, movie: Movie) -> None:
    """解析导演/主演与「年份 / 国家 / 类型」。"""
    info_node = item.select_one("div.bd p")
    if info_node is None:
        return
    lines = [line.strip() for line in info_node.get_text("\n").split("\n") if line.strip()]
    if lines:
        movie.staff = lines[0]
    meta_line = lines[-1] if len(lines) > 1 else ""
    parts = [part.strip() for part in meta_line.split("/") if part.strip()]
    if len(parts) >= 3:
        movie.year = match_year(parts[0])
        movie.genres = parts[-1]
        movie.country = " / ".join(parts[1:-1])
    elif len(parts) == 2:
        movie.year = match_year(parts[0])
        movie.genres = parts[1]


def parse_item(item: Tag, fallback_rank: int = 0) -> Movie:
    """解析单个 <div class="item">。"""
    movie = Movie()

    rank_text = _text(item.select_one("div.pic em"))
    movie.rank = int(rank_text) if rank_text.isdigit() else fallback_rank

    link_node = item.select_one("div.hd a") or item.select_one("div.pic a")
    if link_node is not None and link_node.get("href"):
        movie.url = urljoin(BASE_URL, str(link_node["href"]))

    img_node = item.select_one("div.pic img")
    if img_node is not None:
        movie.cover = str(img_node.get("src") or "")
        movie.title = clean_text(str(img_node.get("alt") or ""))

    # 片名：第一个 span.title 是中文名，其余是外文名
    titles = [clean_text(_text(node)) for node in item.select("div.hd span.title")]
    titles = [title for title in titles if title]
    if titles:
        movie.title = titles[0]
        movie.foreign_title = " / ".join(titles[1:])
    movie.aliases = clean_text(_text(item.select_one("span.other")))

    rating_node = item.select_one("span.rating_num") or item.select_one('span[property="v:average"]')
    try:
        movie.rating = float(_text(rating_node))
    except (TypeError, ValueError):
        movie.rating = 0.0
    movie.votes = _parse_votes(item, rating_node)

    # 短评（新版 span 无 class，旧版为 span.inq）
    quote_node = item.select_one("p.quote span.inq") or item.select_one("p.quote span") or item.select_one("p.quote")
    movie.quote = clean_text(_text(quote_node))

    _parse_meta(item, movie)
    return movie


def parse_page(html: str, start: int = 0) -> List[Movie]:
    """解析一页 Top250 列表，返回该页电影列表。

    :param html: 页面 HTML
    :param start: 该页对应的 start 参数，用于在排名缺失时兜底计算
    """
    soup = BeautifulSoup(html, "html.parser")
    container = soup.select_one("ol.grid_view") or soup
    items = container.select("div.item") or soup.select("div.item")
    if not items:
        logger.warning("本页未解析到任何 div.item（start=%s），可能是页面结构变化或被拦截", start)
        return []

    movies: List[Movie] = []
    for offset, item in enumerate(items):
        movies.append(parse_item(item, fallback_rank=(start or 0) + offset + 1))
    logger.debug("解析 start=%s：命中 %d 条", start, len(movies))
    return movies


def is_anti_bot_html(html: str) -> bool:
    """判断页面内容是否是反爬拦截页。"""
    from .config import ANTI_BOT_MARKS

    return any(mark in (html or "") for mark in ANTI_BOT_MARKS)


__all__ = ["parse_page", "parse_item", "clean_text", "match_year", "is_anti_bot_html", "BASE_URL"]
