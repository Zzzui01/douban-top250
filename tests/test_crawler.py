# -*- coding: utf-8 -*-
"""翻页编排测试：页数夹取、回调、长休息与去重。"""

from __future__ import annotations

import pytest

from douban_top250 import crawler as crawler_module
from douban_top250.config import MAX_PAGES
from douban_top250.crawler import (
    crawl_top250,
    dedupe_movies,
    missing_pages,
    page_ranks,
    page_start,
    resolve_page_order,
)
from douban_top250.models import Movie


class FakeFetcher:
    """记录调用并循环返回预设 HTML 的抓取器替身。"""

    def __init__(self, htmls=None):
        self.htmls = list(htmls) if htmls else []
        self.calls = []
        self.warmed = 0
        self.persisted = 0

    def warm_up(self, url=None):
        self.warmed += 1

    def get(self, url, params=None):
        self.calls.append({"url": url, "params": params})
        if not self.htmls:
            return "<html></html>"
        index = min(len(self.calls) - 1, len(self.htmls) - 1)
        return self.htmls[index]

    def persist_cookies(self):
        self.persisted += 1


@pytest.fixture
def sleeps(monkeypatch):
    recorded = []
    monkeypatch.setattr(crawler_module.time, "sleep", lambda seconds: recorded.append(seconds))
    return recorded


def test_dedupe_movies_keeps_first_and_sorts_by_rank():
    movies = [
        Movie(rank=3, title="第三"),
        Movie(rank=1, title="第一次出现的第一名"),
        Movie(rank=2, title="第二"),
        Movie(rank=1, title="重复的第一名"),
    ]

    result = dedupe_movies(movies)

    assert [movie.rank for movie in result] == [1, 2, 3]
    assert result[0].title == "第一次出现的第一名"


def test_crawl_top250_parses_every_page(sample_html, sleeps):
    fetcher = FakeFetcher([sample_html, sample_html])

    movies = crawl_top250(fetcher=fetcher, pages=2, cooldown_every=0)

    assert len(movies) == 6
    assert fetcher.warmed == 1
    assert fetcher.persisted == 1
    assert [call["params"] for call in fetcher.calls] == [
        {"start": 0, "filter": ""},
        {"start": 25, "filter": ""},
    ]
    assert sleeps == []


def test_crawl_top250_clamps_pages_to_max(sample_html, sleeps):
    fetcher = FakeFetcher([sample_html])

    crawl_top250(fetcher=fetcher, pages=99, cooldown_every=0)

    assert len(fetcher.calls) == MAX_PAGES == 10
    assert fetcher.calls[-1]["params"]["start"] == 225


def test_crawl_top250_invokes_page_callback(sample_html, sleeps):
    fetcher = FakeFetcher([sample_html, sample_html])
    events = []

    crawl_top250(fetcher=fetcher, pages=2, cooldown_every=0,
                 on_page=lambda page, total, movies: events.append((page, total, len(movies))))

    assert events == [(1, 2, 3), (2, 2, 3)]


def test_crawl_top250_takes_cooldown_between_batches(sample_html, sleeps):
    fetcher = FakeFetcher([sample_html])

    crawl_top250(fetcher=fetcher, pages=3, cooldown_every=1, cooldown=(25.0, 45.0))

    assert len(sleeps) == 2                      # 最后一页之后不再休息
    assert all(25.0 <= seconds <= 45.0 for seconds in sleeps)


def test_crawl_top250_without_cooldown_never_sleeps(sample_html, sleeps):
    fetcher = FakeFetcher([sample_html])

    crawl_top250(fetcher=fetcher, pages=3, cooldown_every=0)

    assert sleeps == []


def test_crawl_top250_continues_on_empty_page(sleeps):
    fetcher = FakeFetcher(["<html><body>空页面</body></html>"])

    movies = crawl_top250(fetcher=fetcher, pages=2, cooldown_every=0)

    assert movies == []
    assert len(fetcher.calls) == 2
    assert fetcher.persisted == 1


# --------------------------------------------------------------------------- #
# 断点续传：页码 -> 排名区间、缺页计算、只抓指定页
# --------------------------------------------------------------------------- #
def test_page_start_and_ranks():
    assert page_start(1) == 0
    assert page_start(3) == 50
    assert page_ranks(2) == list(range(26, 51))


def test_missing_pages_finds_gap():
    movies = [Movie(rank=rank) for rank in range(1, 26)]
    movies += [Movie(rank=rank) for rank in range(51, 76)]

    assert missing_pages(movies, pages=3) == [2]


def test_missing_pages_all_when_local_is_empty():
    assert missing_pages([], pages=2) == [1, 2]
    assert missing_pages(None, pages=1) == [1]


def test_missing_pages_empty_when_everything_covered():
    movies = [Movie(rank=rank) for rank in range(1, 76)]

    assert missing_pages(movies, pages=3) == []


def test_missing_pages_treats_partial_page_as_missing():
    movies = [Movie(rank=rank) for rank in range(1, 251) if rank != 137]

    assert missing_pages(movies, pages=6) == [6]


def test_resolve_page_order_default_and_explicit():
    assert resolve_page_order(3) == [1, 2, 3]
    assert resolve_page_order(5, order=[2, 4, 2, 9]) == [2, 4]      # 去重且过滤越界
    assert resolve_page_order(99) == list(range(1, MAX_PAGES + 1))  # 页数夹取


def test_resolve_page_order_shuffle_is_seed_stable():
    first = resolve_page_order(10, shuffle=True, seed=42)
    second = resolve_page_order(10, shuffle=True, seed=42)

    assert sorted(first) == list(range(1, 11))
    assert first == second
    assert first != list(range(1, 11))       # 顺序确实被打乱了


def test_crawl_top250_only_fetches_requested_pages(sample_html, sleeps):
    fetcher = FakeFetcher([sample_html])

    crawl_top250(fetcher=fetcher, pages=10, cooldown_every=0, order=[2, 7])

    assert [call["params"]["start"] for call in fetcher.calls] == [25, 150]


def test_crawl_top250_skips_network_when_nothing_missing(sleeps):
    fetcher = FakeFetcher(["<html></html>"])

    movies = crawl_top250(fetcher=fetcher, pages=10, order=[])

    assert movies == []
    assert fetcher.calls == []
    assert fetcher.warmed == 1


def test_crawl_top250_shuffle_pages_keeps_same_page_set(sample_html, sleeps):
    fetcher = FakeFetcher([sample_html])

    crawl_top250(fetcher=fetcher, pages=4, cooldown_every=0, shuffle=True, seed=7)

    starts = sorted(call["params"]["start"] for call in fetcher.calls)
    assert starts == [0, 25, 50, 75]
