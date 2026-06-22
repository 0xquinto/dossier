"""Marker so ``research.evals`` is importable as a package (spec §7 eval scaffold).

The pipeline run-output directories under ``research/`` are not Python; this
package marker exists only to expose ``research.evals`` to the test suite and to
the eval entrypoints. It carries no code.
"""
