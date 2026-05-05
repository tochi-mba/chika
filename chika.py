"""Chika v2 — convenience entry point.

This top-level module exists so ``python chika.py`` keeps working. The
canonical implementation lives in :mod:`chika._cli` so that the ``chika``
console script (installed via ``pip install -e .``) and ``python chika.py``
share a single code path.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from chika._cli import cli


if __name__ == "__main__":
    cli()
