# -*- coding: utf-8 -*-
"""豆瓣电影 Top250 爬虫入口（薄入口）。

真正的实现已按职责拆分到 ``douban_top250`` 包内：

    douban_top250/config.py         常量与环境路径
    douban_top250/models.py         Movie 数据类与字段定义
    douban_top250/parse.py          列表页 HTML 解析
    douban_top250/fetch.py          带预热/cookie/退避的抓取器
    douban_top250/crawler.py        翻页调度与去重
    douban_top250/clean.py          Pandas 清洗
    douban_top250/storage.py        CSV / JSON 读写
    douban_top250/report.py         终端预览表格
    douban_top250/excel.py          Excel 生成（含统计概览）
    douban_top250/cli.py            命令行参数与流程编排

本文件保留全部历史公开名字，既可以直接 ``python bot.py`` 运行，
也可以继续 ``from bot import crawl_top250, Fetcher, Movie, print_table``。

常用命令::

    python bot.py                                   # 抓 10 页 + 清洗 + 生成 Excel
    python bot.py --pages 2 --delay 3 6             # 只抓 2 页
    python bot.py --from-json output/douban_top250.json --clean   # 离线重跑清洗/Excel
    python bot.py --no-clean --no-xlsx              # 只要 CSV/JSON
"""

from __future__ import annotations

import sys

from douban_top250 import __version__
from douban_top250.cli import build_parser, main, run
from douban_top250.config import (
    BASE_URL,
    CACHE_DIR,
    CLEAN_CSV_NAME,
    CLEAN_JSON_NAME,
    COOKIE_FILE,
    CSV_NAME,
    DEFAULT_COOLDOWN,
    DEFAULT_COOLDOWN_EVERY,
    DEFAULT_DELAY,
    DEFAULT_MAX_BLOCK_RETRIES,
    DEFAULT_PREVIEW,
    DEFAULT_RETRIES,
    DEFAULT_TIMEOUT,
    HOME_URL,
    JSON_NAME,
    LOG_DIR,
    MAX_PAGES,
    OUTPUT_DIR,
    PAGE_SIZE,
    SOURCE,
    USER_AGENTS,
    XLSX_NAME,
)
from douban_top250.crawler import crawl_top250, dedupe_movies
from douban_top250.exceptions import AntiBotError, CleanError, CrawlError, FetchError
from douban_top250.fetch import Fetcher, load_cookies, save_cookies
from douban_top250.logging_setup import get_logger, setup_logging
from douban_top250.models import FIELD_LABELS, MOVIE_FIELDS, Movie, movies_from_rows, rows_from_movies
from douban_top250.parse import is_anti_bot_html, parse_page
from douban_top250.report import print_table, render_table
from douban_top250.storage import build_payload, load_json, load_movies, save_csv, save_json

__all__ = [
    "__version__",
    # 流程编排
    "main",
    "run",
    "build_parser",
    # 抓取
    "crawl_top250",
    "dedupe_movies",
    "Fetcher",
    "load_cookies",
    "save_cookies",
    # 解析
    "parse_page",
    "is_anti_bot_html",
    # 数据
    "Movie",
    "MOVIE_FIELDS",
    "FIELD_LABELS",
    "rows_from_movies",
    "movies_from_rows",
    # 存储与展示
    "save_csv",
    "save_json",
    "load_json",
    "load_movies",
    "build_payload",
    "print_table",
    "render_table",
    # 日志
    "setup_logging",
    "get_logger",
    # 异常
    "CrawlError",
    "FetchError",
    "AntiBotError",
    "CleanError",
    # 常量
    "BASE_URL",
    "HOME_URL",
    "SOURCE",
    "PAGE_SIZE",
    "MAX_PAGES",
    "USER_AGENTS",
    "DEFAULT_TIMEOUT",
    "DEFAULT_RETRIES",
    "DEFAULT_MAX_BLOCK_RETRIES",
    "DEFAULT_DELAY",
    "DEFAULT_COOLDOWN_EVERY",
    "DEFAULT_COOLDOWN",
    "DEFAULT_PREVIEW",
    "OUTPUT_DIR",
    "LOG_DIR",
    "CACHE_DIR",
    "COOKIE_FILE",
    "CSV_NAME",
    "JSON_NAME",
    "XLSX_NAME",
    "CLEAN_CSV_NAME",
    "CLEAN_JSON_NAME",
]


if __name__ == "__main__":
    sys.exit(main())
