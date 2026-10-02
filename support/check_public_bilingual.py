"""Public bilingual and readability gate for the local staging tree."""
from __future__ import annotations

import argparse
import re
from pathlib import Path


PUBLIC_REL = [
    "web/index.html",
    "web/docs/index.html",
]
EN_SECTIONS = [
    "## Quick start",
    "## Six modules, one local truth layer",
    "## Use only what you need",
    "## How the pieces work together",
    "## Host integrations",
    "## Adaptive Router",
    "## Architecture",
    "## Security and local data",
    "## Project status",
    "## Contributing",
    "## License & acknowledgements",
]
ZH_SECTIONS = [
    "## 60 秒开始",
    "## 六个模块，一套本地真值",
    "## 只启用你需要的能力",
    "## 六个模块如何协作",
    "## 宿主集成",
    "## Adaptive Router",
    "## 架构",
    "## 安全与本地数据",
    "## 当前状态",
    "## 参与贡献",
    "## 许可证与致谢",
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    errors: list[str] = []
    warnings: list[str] = []
    en = root / "README.md"
    zh = root / "README_CN.md"
    for path in (en, zh):
        if not path.is_file():
            errors.append(f"{path.name}: missing")
    if en.is_file() and "README_CN.md" not in en.read_text(encoding="utf-8", errors="replace"):
        errors.append("README.md: missing Chinese switch link")
    if zh.is_file() and "README.md" not in zh.read_text(encoding="utf-8", errors="replace"):
        errors.append("README_CN.md: missing English switch link")
    if en.is_file() and zh.is_file():
        en_text = en.read_text(encoding="utf-8", errors="replace")
        zh_text = zh.read_text(encoding="utf-8", errors="replace")
        for section in EN_SECTIONS:
            if section not in en_text:
                errors.append(f"README.md: missing public section {section}")
        for section in ZH_SECTIONS:
            if section not in zh_text:
                errors.append(f"README_CN.md: missing public section {section}")
        for host in ("Codex", "Cursor", "Qoder", "OpenCode", "WorkBuddy"):
            if host not in en_text or host not in zh_text:
                errors.append(f"README host list missing {host}")
        if "0.6.0-alpha.1" in en_text or "0.6.0-alpha.1" in zh_text:
            errors.append("README contains the previous release label")
    css = root / "web" / "public.css"
    style_sources = [css] if css.is_file() else []
    for rel in PUBLIC_REL if (root / "web").exists() else []:
        path = root / rel
        if not path.is_file():
            errors.append(f"{rel}: missing")
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if not re.search(r"langBtn|data-locale-button|id=[\"']locale[\"']", text, re.I):
            errors.append(f"{rel}: no visible language switch marker")
        if rel != "web/index.html" and not re.search(r"id=[\"']locale[\"']|contextcord\.locale|data-locale-button", text, re.I):
            errors.append(f"{rel}: shared public behavior is missing")
        visible = re.sub(r"<script\b[^>]*>.*?</script\s*>|<style\b[^>]*>.*?</style\s*>", " ", text, flags=re.I | re.S)
        if rel == "web/index.html" and any(re.search(rf"\b{re.escape(token)}\b", visible, re.I) for token in ("A11", "A12", "HOST_NOT_RUN", "LOCALHOST_ONLY", "source_sha256")):
            errors.append(f"{rel}: internal progress label leaked into homepage")
        # Home and Docs intentionally keep their locked component styles inline;
        # the shared stylesheet check above is the only typography gate.
    for path in style_sources:
        text = path.read_text(encoding="utf-8", errors="replace")
        tiny = [float(value) for value in re.findall(r"font-size\s*:\s*([0-9.]+)px", text, flags=re.I) if float(value) < 12]
        if tiny:
            errors.append(f"{path.relative_to(root)}: public font-size below 12px: {sorted(set(tiny))}")
    print(f"errors={len(errors)} warnings={len(warnings)}")
    for item in errors:
        print(f"ERROR: {item}")
    for item in warnings:
        print(f"WARN: {item}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
