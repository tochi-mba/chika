"""Chika CLI — Claude Code-inspired terminal UI.

Public entry point: ``cli()`` (re-exported from :mod:`chika`).
Use ``python chika.py`` or the ``chika`` console script (after ``pip install -e .``).
"""
from chika._cli.app import cli

__all__ = ["cli"]
