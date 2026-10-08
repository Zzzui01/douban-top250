# -*- coding: utf-8 -*-
"""日志配置：控制台输出 + 轮转文件日志。

设计要点
--------
* 控制台默认只显示 INFO 及以上，`--quiet` 时只显示 WARNING 及以上，保证交互输出干净；
* 文件日志固定记录 DEBUG 及以上，带时间、模块、行号，便于事后排查被限流的过程；
* `setup_logging()` 可重复调用（会先清空旧 handler，避免日志重复打印）。
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from .config import LOG_BACKUP_COUNT, LOG_FILE, LOG_MAX_BYTES

LOGGER_NAME = "douban_top250"

CONSOLE_FORMAT = "%(levelname)-5s %(message)s"
FILE_FORMAT = "%(asctime)s %(levelname)-7s %(name)s:%(lineno)d | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """取包内 logger（子模块传入 __name__ 即可自动挂到 douban_top250 之下）。"""
    if not name or name == LOGGER_NAME:
        return logging.getLogger(LOGGER_NAME)
    if name.startswith(LOGGER_NAME + "."):
        return logging.getLogger(name)
    return logging.getLogger(LOGGER_NAME + "." + name)


def setup_logging(
    level: str = "INFO",
    quiet: bool = False,
    log_dir: Optional[Path] = None,
    log_file: str = LOG_FILE,
    to_file: bool = True,
) -> logging.Logger:
    """配置并返回包 logger。

    :param level: 控制台日志级别（DEBUG/INFO/WARNING/ERROR）
    :param quiet: 静默模式，控制台只保留 WARNING 及以上
    :param log_dir: 日志目录，None 表示使用 config.LOG_DIR
    :param log_file: 日志文件名
    :param to_file: 是否写文件日志
    """
    from .config import LOG_DIR

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    console_level = logging.WARNING if quiet else getattr(logging, str(level).upper(), logging.INFO)
    console = logging.StreamHandler(stream=sys.stdout)
    console.setLevel(console_level)
    console.setFormatter(logging.Formatter(CONSOLE_FORMAT, DATE_FORMAT))
    logger.addHandler(console)

    if to_file:
        directory = Path(log_dir) if log_dir else Path(LOG_DIR)
        try:
            directory.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                str(directory / log_file),
                maxBytes=LOG_MAX_BYTES,
                backupCount=LOG_BACKUP_COUNT,
                encoding="utf-8",
            )
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(logging.Formatter(FILE_FORMAT, DATE_FORMAT))
            logger.addHandler(file_handler)
        except OSError as exc:  # 日志目录不可写时不影响主流程
            logger.warning("无法创建日志文件（%s），仅输出到控制台", exc)

    return logger
