"""Sphinx 最小配置。"""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

project = "autodo-kit"
author = "Ethan Lin"
copyright = "2026, Ethan Lin"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "myst_parser",
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]
source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}
root_doc = "index"
language = "zh_CN"
html_theme = "alabaster"
html_static_path = ["_static"]
autodoc_member_order = "bysource"
napoleon_google_docstring = True
napoleon_numpy_docstring = False
myst_enable_extensions = ["colon_fence"]
suppress_warnings = ["myst.header", "misc.highlighting_failure"]
