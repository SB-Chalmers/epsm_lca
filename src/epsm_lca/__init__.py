# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EPSM Development contributors
# License: See LICENSE at the project root.
"""Building renovation climate assessment using Core buildings and Data factors."""

import logging

from ._version import __version__
from .assessment import assess
from .energy import AnnualEnergy
from .renovation import assess_renovation
from .renovation_result import RenovationResult, StageResult
from .result import LCAResult
from .settings import AssessmentSettings

_logger = logging.getLogger(__name__)
if not any(isinstance(handler, logging.NullHandler) for handler in _logger.handlers):
    _logger.addHandler(logging.NullHandler())

__all__ = [
    "AnnualEnergy",
    "AssessmentSettings",
    "LCAResult",
    "RenovationResult",
    "StageResult",
    "assess",
    "assess_renovation",
    "__version__",
]
