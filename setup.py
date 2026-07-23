"""Compatibility entry point for editable installs with older pip versions."""

from pathlib import Path

from setuptools import find_packages, setup


ROOT = Path(__file__).parent

setup(
    name="codex-dream-seed",
    version="0.4.0",
    description="A local-first, incremental learning system for Codex sessions",
    long_description=(ROOT / "README.md").read_text(encoding="utf-8"),
    long_description_content_type="text/markdown",
    author="weiqinghang",
    url="https://github.com/weiqinghang/codex-dream-seed",
    packages=find_packages(include=["codex_dream*"]),
    package_data={"codex_dream.console_static": ["*.html", "*.css", "*.js"]},
    python_requires=">=3.9,<3.14",
    entry_points={
        "console_scripts": [
            "codex-dream=codex_dream.cli:main",
            "codex-dream-review=codex_dream.review:main",
            "codex-dream-knowledge=codex_dream.knowledge:main",
            "codex-dream-console=codex_dream.console:main",
        ]
    },
)
