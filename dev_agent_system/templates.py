"""多语言项目模板与工具链定义。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class LangTemplate:
    """描述一种编程语言的文件约定、默认产物与常用命令。"""

    name: str
    display: str
    file_ext: str
    test_ext: str
    build_cmd: str
    test_cmd: str
    package_file: Optional[str] = None
    default_files: Dict[str, str] = field(default_factory=dict)
    allowed_commands: List[str] = field(default_factory=list)

    def main_file(self, name: str = "main") -> str:
        if self.name == "java":
            return f"{name.capitalize()}.{self.file_ext}"
        return f"{name}.{self.file_ext}"

    def test_file(self, name: str = "main") -> str:
        if self.name == "python":
            return f"test_{name}.{self.file_ext}"
        if self.name == "go":
            return f"{name}_test.{self.file_ext}"
        if self.name == "java":
            return f"{name.capitalize()}Test.{self.file_ext}"
        if self.name == "typescript":
            return f"{name}.test.ts"
        return f"{name}_test.{self.test_ext}"


TEMPLATES: Dict[str, LangTemplate] = {
    "python": LangTemplate(
        name="python",
        display="Python",
        file_ext="py",
        test_ext="py",
        build_cmd="",
        test_cmd="pytest",
        package_file="requirements.txt",
        default_files={
            "requirements.txt": "# Auto-generated dependencies\n",
        },
        allowed_commands=["python", "pytest"],
    ),
    "java": LangTemplate(
        name="java",
        display="Java",
        file_ext="java",
        test_ext="java",
        build_cmd="mvn compile",
        test_cmd="mvn test",
        package_file="pom.xml",
        default_files={
            "pom.xml": """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.devagent</groupId>
  <artifactId>generated</artifactId>
  <version>1.0-SNAPSHOT</version>
  <properties>
    <maven.compiler.source>17</maven.compiler.source>
    <maven.compiler.target>17</maven.compiler.target>
    <project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>
  </properties>
  <dependencies>
    <dependency>
      <groupId>org.junit.jupiter</groupId>
      <artifactId>junit-jupiter</artifactId>
      <version>5.10.0</version>
      <scope>test</scope>
    </dependency>
  </dependencies>
</project>
""",
        },
        allowed_commands=["mvn", "javac", "java"],
    ),
    "go": LangTemplate(
        name="go",
        display="Go",
        file_ext="go",
        test_ext="go",
        build_cmd="go build ./...",
        test_cmd="go test ./...",
        package_file="go.mod",
        default_files={
            "go.mod": "module generated\n\ngo 1.21\n",
        },
        allowed_commands=["go"],
    ),
    "typescript": LangTemplate(
        name="typescript",
        display="TypeScript",
        file_ext="ts",
        test_ext="test.ts",
        build_cmd="npx tsc",
        test_cmd="npm test",
        package_file="package.json",
        default_files={
            "package.json": """{
  "name": "generated",
  "version": "1.0.0",
  "scripts": {
    "test": "jest",
    "build": "tsc"
  },
  "devDependencies": {
    "@types/node": "^20.0.0",
    "jest": "^29.0.0",
    "typescript": "^5.3.0"
  }
}
""",
        },
        allowed_commands=["npm", "npx", "node"],
    ),
}


def get_language(state_or_language) -> LangTemplate:
    """从 state 或字符串解析目标语言模板，默认 Python。"""
    if isinstance(state_or_language, str):
        lang = state_or_language.lower().strip()
    elif isinstance(state_or_language, dict):
        lang = (state_or_language.get("language") or "python").lower().strip()
    else:
        lang = "python"
    return TEMPLATES.get(lang, TEMPLATES["python"])


def list_languages() -> List[str]:
    return list(TEMPLATES.keys())
