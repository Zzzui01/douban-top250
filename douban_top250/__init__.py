# -*- coding: utf-8 -*-
"""豆瓣电影 Top250 爬虫包。

模块划分
--------
config          全局常量（URL、UA 池、默认节奏、路径）
exceptions      异常层级（CrawlError / FetchError / AntiBotError）
models          Movie 数据类与字段映射
parse           列表页 HTML 解析
fetch           网络层（会话预热、cookie 持久化、退避重试、限流止损）
crawler         翻页编排与去重
storage         CSV / JSON 存取
clean           pandas 清洗
excel           Excel 导出
logging_setup   日志配置
cli             命令行入口
"""

from __future__ import annotations

from .config import BASE_URL, MAX_PAGES, PAGE_SIZE, SOURCE
from .crawler import crawl_top250, dedupe_movies
from .exceptions import AntiBotError, CrawlError, FetchError
from .fetch import Fetcher, load_cookies, save_cookies
from .models import FIELD_LABELS, MOVIE_FIELDS, Movie
from .parse import parse_page
from .storage import load_json, load_movies, save_csv, save_json

__version__ = "1.0.0"

__all__ = [
    "BASE_URL",
    "SOURCE",
    "PAGE_SIZE",
    "MAX_PAGES",
    "Movie",
    "MOVIE_FIELDS",
    "FIELD_LABELS",
    "Fetcher",
    "crawl_top250",
    "dedupe_movies",
    "parse_page",
    "save_csv",
    "save_json",
    "load_json",
    "load_movies",
    "save_cookies",
    "load_cookies",
    "CrawlError",
    "FetchError",
    "AntiBotError",
    "__version__",
]
