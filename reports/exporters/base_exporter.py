"""
Abstract exporter interface for the Reports module.

Concrete exporters implement rendering only. Common hashing and metadata
behavior is centralized here.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from hashlib import sha256
from typing import Any, Mapping


class BaseExporter(ABC):
    """
    Base contract for all report exporters.

    Supported implementations may include PDF, Excel, CSV, DOCX and future
    formats. Callers interact only with this interface.
    """

    #: Unique export format identifier (e.g. PDF, EXCEL, CSV).
    format_code: str

    #: Default MIME type for the exporter.
    content_type: str

    #: Default filename extension.
    file_extension: str

    @abstractmethod
    def render(
        self,
        *,
        context: Mapping[str, Any],
    ) -> bytes:
        """
        Render a report into raw bytes.
        """
        raise NotImplementedError

    def compute_file_hash(self, content: bytes) -> str:
        """
        Compute the SHA-256 checksum of exported content.
        """
        return sha256(content).hexdigest()

    def build_filename(self, stem: str) -> str:
        """
        Build a filename using the exporter's default extension.
        """
        extension = self.file_extension.lstrip(".")
        return f"{stem}.{extension}"

    def export(
        self,
        *,
        context: Mapping[str, Any],
    ) -> tuple[bytes, str]:
        """
        Render the report and return its bytes together with a checksum.
        """
        content = self.render(context=context)
        return content, self.compute_file_hash(content)