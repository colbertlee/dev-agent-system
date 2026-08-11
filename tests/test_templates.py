"""多语言模板单元测试。"""
from __future__ import annotations

import pytest

from dev_agent_system.templates import get_language, list_languages, TEMPLATES


def test_list_languages():
    assert set(list_languages()) >= {"python", "java", "go", "typescript"}


@pytest.mark.parametrize(
    "lang,expected_ext,test_ext",
    [
        ("python", "py", "py"),
        ("java", "java", "java"),
        ("go", "go", "go"),
        ("typescript", "ts", "test.ts"),
    ],
)
def test_template_fields(lang, expected_ext, test_ext):
    template = TEMPLATES[lang]
    assert template.file_ext == expected_ext
    assert template.main_file().endswith(f".{expected_ext}")
    assert template.test_file().endswith(test_ext)


def test_get_language_defaults_to_python():
    assert get_language("unknown").name == "python"
    assert get_language({"language": "rust"}).name == "python"


def test_java_main_and_test_names():
    template = TEMPLATES["java"]
    assert template.main_file("calc") == "Calc.java"
    assert template.test_file("calc") == "CalcTest.java"


def test_go_test_naming():
    template = TEMPLATES["go"]
    assert template.test_file("main") == "main_test.go"
