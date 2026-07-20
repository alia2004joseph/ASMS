from __future__ import annotations

from pathlib import Path


def make_unique_filename(
    filename: str,
    used_filenames: set[str],
) -> str:
    """
    Return a filename that is unique within the current export.

    If the supplied filename already exists, an incrementing numeric
    suffix is appended before the extension.

    Examples
    --------
    report.pdf
    report_1.pdf
    report_2.pdf

    Parameters
    ----------
    filename:
        Desired filename.

    used_filenames:
        Set of filenames already allocated within the archive.

    Returns
    -------
    str
        A filename guaranteed not to collide with those already used.
    """
    candidate = filename

    if candidate not in used_filenames:
        return candidate

    path = Path(filename)
    stem = path.stem
    suffix = path.suffix

    index = 1

    while True:
        candidate = f"{stem}_{index}{suffix}"

        if candidate not in used_filenames:
            return candidate

        index += 1