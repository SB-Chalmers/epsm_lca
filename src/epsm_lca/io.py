# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EPSM Development contributors
# License: See LICENSE at the project root.
"""Explicit report files: validated UTF-8 JSON and atomic publication."""

import json
import logging
import os
import tempfile
from pathlib import Path

from .renovation_result import RenovationResult

logger = logging.getLogger(__name__)


def save_report(report: RenovationResult, path, *, overwrite=False) -> Path:
    """Publish a report atomically; never create missing parent directories.

    Existing files are refused unless overwrite=True. A rejected write leaves
    the existing file untouched; any temporary file is removed on failure.
    """
    if not isinstance(overwrite, bool):
        raise ValueError("overwrite must be True or False")
    path = Path(path)
    encoded = (
        json.dumps(
            report.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    )
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=".epsm-lca-",
            suffix=".json",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        if overwrite:
            os.replace(temporary, path)
        else:
            os.link(
                temporary, path
            )  # Publication enforces no-overwrite, including races.
        logger.info(
            "Saved renovation report to %s",
            path,
            extra={
                "epsm_event": "lca.report.saved",
                "epsm_context": {},
                "epsm_details": {
                    "path": str(path),
                    "step_count": report.summary()["step_count"],
                },
            },
        )
    except OSError:
        logger.error(
            "Could not publish renovation report",
            extra={
                "epsm_event": "lca.report.save.failed",
                "epsm_context": {},
                "epsm_details": {"code": "lca.report.save.failed", "path": str(path)},
            },
        )
        raise
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return path


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate report field: {key}")
        result[key] = value
    return result


def _nonfinite(value):
    raise ValueError(f"Nonfinite report number: {value}")


def load_report(path) -> RenovationResult:
    """Read a supported UTF-8 report, checking inputs and saved accounting."""
    path = Path(path)
    try:
        with path.open(encoding="utf-8") as stream:
            data = json.load(
                stream, object_pairs_hook=_unique_object, parse_constant=_nonfinite
            )
        if not isinstance(data, dict):
            raise ValueError("A report must be a JSON object")
        result = RenovationResult.from_dict(data)
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        logger.error(
            "Rejected an invalid renovation report",
            extra={
                "epsm_event": "lca.report.load.failed",
                "epsm_context": {},
                "epsm_details": {"code": "lca.report.invalid", "path": str(path)},
            },
        )
        raise ValueError(f"Invalid renovation report {path}: {error}") from error
    logger.info(
        "Loaded renovation report from %s",
        path,
        extra={
            "epsm_event": "lca.report.loaded",
            "epsm_context": {},
            "epsm_details": {
                "path": str(path),
                "step_count": result.summary()["step_count"],
            },
        },
    )
    return result
