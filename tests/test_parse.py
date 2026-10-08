# -*- coding: utf-8 -*-
"""解析层测试：覆盖豆瓣新旧两种列表页结构、排名兜底与异常页面。"""

from __future__ import annotations

from bs4 import BeautifulSoup
import pytest

from douban_top250.parse import clean_text, is_anti_bot_html, match_year, parse_item, parse_page


def item_of(html: str):
    return BeautifulSoup(html, "html.parser").select_one("div.item")


def test_clean_text_merges_spaces_and_trims_slashes():
    assert clean_text("\xa0/ \xa0 你好   世界 /") == "你好 世界"
    assert clean_text(None) == ""
    assert clean_text("  ") == ""


@pytest.mark.parametrize(
    "text,expected",
    [("(1994)", "1994"), ("1993-01-01", "1993"), ("2018", "2018"), ("未知", "未知")],
)
def test_match_year(text, expected):
    assert match_year(text) == expected


def test_parse_modern_item(modern_item):
    """新版结构：评分容器无 class、评价人数在裸 span、短评是 p.quote 下的普通 span。"""
    movie = parse_item(item_of(modern_item))

    assert movie.rank == 1
    assert movie.title == "肖申克的救赎"
    assert movie.foreign_title == "The Shawshank Redemption"
    assert movie.aliases == "月黑高飞(港) / 刺激1995(台)"
    assert movie.year == "1994"
    assert movie.country == "美国"
    assert movie.genres == "犯罪 剧情"
    assert movie.rating == pytest.approx(9.7)
    assert movie.votes == 3347760
    assert movie.quote == "希望让人自由。"
    assert movie.url == "https://movie.douban.com/subject/1292052/"
    assert "p480747492" in movie.cover
    assert movie.staff.startswith("导演: 弗兰克·德拉邦特")


def test_parse_old_item(old_item):
    """旧版结构：div.star + span[property=v:votes] + span.inq，且链接是相对路径。"""
    movie = parse_item(item_of(old_item))

    assert movie.rank == 2
    assert movie.title == "霸王别姬"
    assert movie.foreign_title == "Farewell My Concubine"
    assert movie.year == "1993"
    assert movie.country == "中国大陆 中国香港"
    assert movie.genres == "剧情 爱情 同性"
    assert movie.rating == pytest.approx(9.6)
    assert movie.votes == 2210000
    assert movie.quote == "风华绝代。"
    assert movie.url == "https://movie.douban.com/subject/1291546/"


def test_parse_sparse_item_uses_defaults(sparse_item):
    """缺排名、缺短评时不应抛异常，字段回落为默认值。"""
    movie = parse_item(item_of(sparse_item))

    assert movie.rank == 0          # 页面没有 em.rank，直接解析时保持 0
    assert movie.title == "无名之辈"
    assert movie.rating == pytest.approx(8.1)
    assert movie.votes == 100
    assert movie.quote == ""
    assert movie.aliases == ""
    assert movie.foreign_title == ""
    assert movie.country == "中国大陆"
    assert movie.genres == "剧情 喜剧"


def test_parse_page_keeps_ranks_and_order(sample_html):
    movies = parse_page(sample_html, start=0)

    assert [movie.title for movie in movies] == ["肖申克的救赎", "霸王别姬", "无名之辈"]
    assert [movie.rank for movie in movies] == [1, 2, 3]


def test_parse_page_falls_back_to_start_offset(sparse_item):
    html = '<ol class="grid_view">{}</ol>'.format(sparse_item)

    movies = parse_page(html, start=25)

    assert len(movies) == 1
    assert movies[0].rank == 26     # start + offset + 1，第二页第一条应是 26


def test_parse_page_returns_empty_on_unexpected_page():
    assert parse_page("") == []
    assert parse_page("<html><body>对不起，您的访问过于频繁</body></html>") == []


def test_is_anti_bot_html():
    assert is_anti_bot_html("<html><title>检测到有异常请求</title></html>") is True
    assert is_anti_bot_html("<html><ol class='grid_view'></ol></html>") is False
