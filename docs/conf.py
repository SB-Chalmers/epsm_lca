# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EPSM Development contributors
# License: See LICENSE at the project root.
"""Build API pages from the installed package; no sibling import paths."""

from epsm_lca import __version__

project = "EPSM LCA"
release = __version__
extensions = ["sphinx.ext.autodoc", "sphinx.ext.napoleon"]
napoleon_numpy_docstring = True
napoleon_google_docstring = False
html_theme = "alabaster"
autodoc_typehints = "description"
