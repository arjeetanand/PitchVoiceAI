"""Run PDF text extraction in a small, resource-limited child process."""

from __future__ import annotations

import json
import re
import sys

MAX_PDF_BYTES = 25 * 1024 * 1024
MAX_PDF_PAGES = 200
DEFAULT_MAX_CHARS = 50_000


def _limit_worker_resources() -> None:
    if not sys.platform.startswith("linux"):
        raise ValueError("PDF uploads require Linux process memory limits.")
    import resource

    if not hasattr(resource, "RLIMIT_AS"):
        raise ValueError("PDF uploads require Linux process memory limits.")

    for name, requested in (("RLIMIT_AS", 256 * 1024 * 1024), ("RLIMIT_CPU", 20)):
        limit = getattr(resource, name, None)
        if limit is None:
            continue
        _, current_hard = resource.getrlimit(limit)
        hard = requested if current_hard == resource.RLIM_INFINITY else min(requested, current_hard)
        resource.setrlimit(limit, (hard, hard))


def _normalise_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _extract(payload: bytes, max_chars: int) -> dict:
    import pymupdf

    try:
        with pymupdf.open(stream=payload, filetype="pdf") as document:
            page_count = len(document)
            if page_count > MAX_PDF_PAGES:
                raise ValueError(f"The PDF exceeds the {MAX_PDF_PAGES} page limit.")
            sections = []
            image_only_pages = []
            total_chars = 0
            for page_number, page in enumerate(document, start=1):
                text = _normalise_text(page.get_text("text"))
                if text:
                    total_chars += len(text)
                    if total_chars > max_chars:
                        raise ValueError("The document exceeds the character limit.")
                    sections.append({"text": text, "citation": f"Page {page_number}", "kind": "page"})
                else:
                    image_only_pages.append(page_number)
    except (pymupdf.FileDataError, ValueError) as exc:
        raise ValueError("This PDF could not be opened or exceeds an extraction limit.") from exc

    warnings = []
    if image_only_pages:
        warnings.append(
            "No selectable text was found on page(s) "
            + ", ".join(str(index) for index in image_only_pages)
            + "; scanned/image-only claims need review."
        )
    if not sections:
        warnings.append("No selectable PDF text was found.")
    return {
        "sections": sections,
        "metadata": {
            "format": "pdf",
            "pages": page_count,
            "sections": len(sections),
            "image_only_pages": image_only_pages,
            "warnings": warnings,
        },
    }


def _main() -> None:
    try:
        _limit_worker_resources()
        max_bytes = int(sys.argv[1]) if len(sys.argv) > 1 else MAX_PDF_BYTES
        max_chars = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_MAX_CHARS
        payload = sys.stdin.buffer.read(max_bytes + 1)
        if len(payload) > max_bytes:
            raise ValueError("The PDF exceeds the upload size limit.")
        result = _extract(payload, max_chars)
    except MemoryError:
        result = {"error": "PDF extraction exceeded its memory limit."}
    except ValueError as exc:
        result = {"error": str(exc)}
    sys.stdout.write(json.dumps(result, separators=(",", ":")))


if __name__ == "__main__":
    _main()
