"""Pytest 共享配置与命令行选项。"""
from __future__ import annotations

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--live",
        action="store_true",
        default=False,
        help="Run live LLM regression tests that call real API",
    )


def pytest_runtest_setup(item: pytest.Item) -> None:
    if "live" in item.keywords and not item.config.getoption("--live"):
        pytest.skip("need --live option to run live LLM regression tests")
