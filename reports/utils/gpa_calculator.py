from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Sequence

GPA_PRECISION = Decimal("0.001")
ZERO_GPA = Decimal("0.000")


def compute_cumulative_gpa(
    term_gpas: Sequence[Decimal],
    term_credits: Sequence[Decimal],
) -> Decimal:
    """
    Compute the cumulative GPA using credit weighting.

    Formula:
        Σ(term_gpa × credits) / Σ(credits)

    Parameters
    ----------
    term_gpas:
        GPA earned for each academic term.

    term_credits:
        Credits earned in each corresponding term.

    Returns
    -------
    Decimal
        Credit-weighted cumulative GPA rounded to three decimal places.

    Raises
    ------
    ValueError
        If the GPA and credit collections are different lengths.
    """
    if len(term_gpas) != len(term_credits):
        raise ValueError(
            "term_gpas and term_credits must contain the same number of elements."
        )

    if not term_gpas:
        return ZERO_GPA

    total_credits = sum(term_credits, Decimal("0"))

    if total_credits <= 0:
        return ZERO_GPA

    weighted_total = sum(
        (
            gpa * credits
            for gpa, credits in zip(term_gpas, term_credits)
        ),
        Decimal("0"),
    )

    return (
        weighted_total / total_credits
    ).quantize(
        GPA_PRECISION,
        rounding=ROUND_HALF_UP,
    )