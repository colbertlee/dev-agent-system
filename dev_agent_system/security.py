"""安全与沙箱加固：命令、路径、敏感信息校验与脱敏。"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Tuple


class SafetyScanner:
    """命令与代码安全扫描器。"""

    # 命中即拦截的危险命令模式
    DANGEROUS_COMMAND_PATTERNS: List[Tuple[str, str]] = [
        (r"\brm\s+-rf\b", "递归强制删除"),
        (r"\bsudo\b", "提升权限执行"),
        (r"\bcurl\b.+\|\s*(sh|bash|zsh)\b", "管道执行远程脚本"),
        (r"\bwget\b.*-O-\b", "wget 输出到管道"),
        (r"\beval\s*\(", "eval 执行"),
        (r"\bexec\s*\(", "exec 执行"),
        (r">\s*/dev/null\s*;\s*", "重定向掩盖命令"),
        (r"&&\s*rm\b", "组合删除"),
        (r"\|\s*sh\b", "管道到 sh"),
        (r"\bshutdown\b", "关机命令"),
        (r"\bmkfs\b", "格式化文件系统"),
        (r"\bdd\s+if=", "dd 裸写设备"),
        (r"\bchmod\s+.*777\b", "过度授权"),
        (r"\bwget\s+.*-O\s*-\b", "wget 输出到标准输出"),
        (r";\s*rm\b", "分号后删除"),
    ]

    # 代码中需要告警的可疑模式（不直接拦截，仅返回风险列表）
    SUSPICIOUS_CODE_PATTERNS: List[Tuple[str, str, str]] = [
        (r"\beval\s*\(", "eval 执行", "high"),
        (r"\bexec\s*\(", "exec 执行", "high"),
        (r"\bcompile\s*\(", "动态编译", "high"),
        (r"__import__\s*\(", "动态导入", "high"),
        (r"\bimportlib\b", "importlib 动态加载", "medium"),
        (r"\bos\.system\b", "os.system 调用", "high"),
        (r"\bsubprocess\.", "subprocess 调用", "medium"),
        (r"\bsocket\.", "socket 网络操作", "medium"),
        (r"\burllib\.request\b", "urllib 网络请求", "medium"),
        (r"\brequests\.", "requests 网络请求", "low"),
        (r"\bpty\.", "pty 伪终端", "high"),
        (r"open\s*\(\s*[\"/]etc/", "读取系统配置文件", "high"),
        (r"open\s*\(\s*[\"/]proc/", "读取 proc 文件系统", "high"),
    ]

    @classmethod
    def scan_command(cls, command: str) -> Tuple[bool, List[str]]:
        """扫描命令字符串，返回 (是否安全, 命中的风险描述列表)。"""
        issues: List[str] = []
        if not command:
            return True, issues
        lower = command.lower()
        for pattern, reason in cls.DANGEROUS_COMMAND_PATTERNS:
            if re.search(pattern, lower, re.I):
                issues.append(reason)
        return not issues, list(set(issues))

    @classmethod
    def is_safe_command(cls, command: str) -> bool:
        safe, _ = cls.scan_command(command)
        return safe

    @classmethod
    def scan_code(cls, code: str) -> List[Dict[str, Any]]:
        """扫描代码片段中的可疑模式，返回风险项列表（不直接拦截）。"""
        issues: List[Dict[str, Any]] = []
        seen: set = set()
        for pattern, reason, severity in cls.SUSPICIOUS_CODE_PATTERNS:
            for m in re.finditer(pattern, code, re.I):
                key = (m.group(0), reason)
                if key in seen:
                    continue
                seen.add(key)
                issues.append(
                    {
                        "line": code[: m.start()].count("\n") + 1,
                        "match": m.group(0),
                        "reason": reason,
                        "severity": severity,
                    }
                )
        return issues


class PathValidator:
    """工作目录内路径校验，防止目录穿越与越界访问。"""

    @staticmethod
    def resolve(base_dir: Path, relative_path: str) -> Path:
        """将 relative_path 解析为 base_dir 下的安全绝对路径。"""
        base = Path(base_dir).resolve()
        # 阻止空路径与纯 .. 路径
        if not relative_path or relative_path.strip() in ("", ".", ".."):
            raise ValueError("无效路径")
        target = (base / relative_path).resolve()
        # 再次检查 resolve 后的结果仍在 base 下
        try:
            target.relative_to(base)
        except ValueError as exc:
            raise ValueError("路径越界：禁止访问工作目录之外") from exc
        return target

    @staticmethod
    def is_within(base_dir: Path, target: Path) -> bool:
        """判断 target 是否位于 base_dir 下。"""
        try:
            Path(target).resolve().relative_to(Path(base_dir).resolve())
            return True
        except ValueError:
            return False


class SecretRedactor:
    """敏感信息脱敏器。"""

    PATTERNS: List[Tuple[str, str]] = [
        (r"sk-[a-zA-Z0-9]{20,}", "[API_KEY_REDACTED]"),
        (r"\b(?:api[_-]?key|apikey|token|secret|access[_-]?key)\s*[:=]\s*[A-Za-z0-9_\-]{8,}", "[SECRET_REDACTED]"),
        (r"1[3-9]\d{9}", "[PHONE_REDACTED]"),
        (r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[EMAIL_REDACTED]"),
        (r"password\s*[:=]\s*\S+", "password=[REDACTED]"),
    ]

    @classmethod
    def redact(cls, text: str) -> str:
        if not text:
            return text
        result = text
        for pattern, replacement in cls.PATTERNS:
            result = re.sub(pattern, replacement, result, flags=re.I)
        return result
