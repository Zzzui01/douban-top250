# -*- coding: utf-8 -*-
"""控制台报表测试：中文宽度对齐与预览截断。"""

from __future__ import annotations

import io

from douban_top250.report import display_width, pad, print_table, render_table


def test_display_width_counts_cjk_as_two_columns():
    assert display_width("肖申克") == 6
    assert display_width("abc") == 3
    assert display_width(1994) == 4


def test_pad_aligns_left_and_right():
    assert pad("abc", 5) == "abc  "
    assert pad("abc", 5, "right") == "  abc"
    assert pad("中文", 6, "right") == "  中文"    # 中文宽度 4 -> 补 2 空格


def test_render_table_contains_header_and_rows(sample_movies):
    table = render_table(sample_movies, limit=2)

    assert "排名" in table
    assert "肖申克的救赎" in table
    assert "霸王别姬" in table
    assert "无名之辈" not in table
    assert "共 3 条，仅预览前 2 条" in table


def test_print_table_writes_to_stream(sample_movies):
    stream = io.StringIO()

    print_table(sample_movies, limit=1, stream=stream)

    written = stream.getvalue()
    assert "肖申克的救赎" in written
    assert written.startswith("\n")
