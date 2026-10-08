# -*- coding: utf-8 -*-
"""翻页编排：预热 -> 逐页抓取 -> 分批长休息 -> 去重排序。"""

from __future__ import annotations

import random
import time
from typing import Callable, List, Optional, Sequence

from .config import BASE_URL, DEFAULT_COOLDOWN, DEFAULT_COOLDOWN_EVERY, MAX_PAGES, PAGE_SIZE
from .fetch import Fetcher
from .logging_setup import get_logger
from .models import Movie
from .parse import parse_page

logger = get_logger(__name__)

PageCallback = Callable[[int, int, List[Movie]], None]


def dedupe_movies(movies: List[Movie]) -> List[Movie]:
    """按排名去重并按排名升序排序（抓取中断重跑时可能拿到重复条目）。"""
    unique = {}
    for movie in movies:
        unique.setdefault(movie.rank, movie)
    return [unique[rank] for rank in sorted(unique)]


def page_start(page: int, page_size: int = PAGE_SIZE) -> int:
    """页码（从 1 开始）对应的 start 参数。"""
    return max(0, page - 1) * page_size


def page_ranks(page: int, page_size: int = PAGE_SIZE) -> List[int]:
    """某一页覆盖的排名区间。"""
    base = page_start(page, page_size)
    return list(range(base + 1, base + page_size + 1))


def missing_pages(movies: Optional[List[Movie]] = None, pages: int = MAX_PAGES,
                  page_size: int = PAGE_SIZE) -> List[int]:
    """本地数据还没覆盖到的页码（该页 25 个排名有一个缺失就算缺失）。

    断点续传的核心：只补抓缺的页，别人为地把 10 页翻一遍。
    """
    have = {int(movie.rank) for movie in (movies or [])}
    pages = max(1, min(int(pages), MAX_PAGES))
    missing = [page for page in range(1, pages + 1)
               if any(rank not in have for rank in page_ranks(page, page_size))]
    return missing


def resolve_page_order(pages: int = MAX_PAGES, order: Optional[Sequence[int]] = None,
                       shuffle: bool = False, seed: Optional[int] = None,
                       page_size: int = PAGE_SIZE) -> List[int]:
    """算出这次真正要抓的页码列表。

    :param order: 显式指定页码（例如断点续传只补缺页），None 表示 1..pages
    :param shuffle: 打乱顺序——0,25,50… 这种严格递增的 start 序列本身就是爬虫指纹
    :param seed: 打乱用的随机种子（仅为可复现的测试/复跑）
    """
    pages = max(1, min(int(pages), MAX_PAGES))
    if order is None:
        result = list(range(1, pages + 1))
    else:
        result = []
        for item in order:
            page = int(item)
            if 1 <= page <= pages and page not in result:
                result.append(page)
    if shuffle:
        random.Random(seed).shuffle(result)
    return result


def crawl_top250(
    fetcher: Optional[Fetcher] = None,
    pages: int = MAX_PAGES,
    on_page: Optional[PageCallback] = None,
    cooldown_every: int = DEFAULT_COOLDOWN_EVERY,
    cooldown: tuple = DEFAULT_COOLDOWN,
    order: Optional[Sequence[int]] = None,
    shuffle: bool = False,
    seed: Optional[int] = None,
    **fetcher_kwargs,
) -> List[Movie]:
    """抓取 Top250，返回全部电影列表。

    :param pages: 抓取页数，1-10
    :param on_page: 每页结束后的回调 (页码, 总页数, 本页数据)
    :param cooldown_every: 每抓 N 页插入一次长休息，0 表示不休息
    :param cooldown: 长休息的随机秒数范围
    :param order: 只抓这些页码（断点续传补缺页）；None 表示抓 1..pages
    :param shuffle: 打乱页码顺序，避免 0/25/50… 的机械翻页特征
    :param seed: shuffle 的随机种子

    连续翻页是最明显的爬虫特征，所以默认每 4 页强制休息 25-45 秒：
    全量 250 条会多花 1-2 分钟，但能显著降低触发 IP 限流的概率。
    """
    fetcher = fetcher or Fetcher(**fetcher_kwargs)
    page_order = resolve_page_order(pages, order=order, shuffle=shuffle, seed=seed)
    total = len(page_order)
    movies: List[Movie] = []

    fetcher.warm_up()

    if not page_order:
        logger.info("没有需要抓取的页面（本地数据已覆盖），跳过翻页")
        return movies

    for position, page in enumerate(page_order, start=1):
        start = page_start(page)
        logger.info("[%d/%d] 抓取第 %d 页 (start=%d) ...", position, total, page, start)
        html = fetcher.get(BASE_URL, params={"start": start, "filter": ""})
        page_movies = parse_page(html, start=start)

        if not page_movies:
            logger.warning("本页未解析到任何条目（start=%d），可能是页面结构变化或被拦截", start)
        movies.extend(page_movies)
        logger.info("已解析 %d 条，累计 %d 条", len(page_movies), len(movies))

        if on_page is not None:
            on_page(page, total, page_movies)

        # 分批休息：模拟人工翻页节奏，避免连续 10 次列表页请求
        if cooldown_every and position % cooldown_every == 0 and position < total:
            wait = random.uniform(cooldown[0], cooldown[1])
            logger.info("已连续抓取 %d 页，休息 %.1fs ...", cooldown_every, wait)
            time.sleep(wait)

    fetcher.persist_cookies()
    return movies


__all__ = ["crawl_top250", "dedupe_movies", "missing_pages", "resolve_page_order",
           "page_start", "page_ranks"]
