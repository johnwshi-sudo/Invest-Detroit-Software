"""PDF intake checks: type, size, page count, encryption, text layer."""
from __future__ import annotations

import io
from dataclasses import dataclass

from pypdf import PdfReader

MAX_BYTES = 32 * 1024 * 1024      # Claude request limit (base64 inflates ~33%; we also check the total)
MAX_PAGES = 600


@dataclass
class PdfInfo:
    name: str
    size: int
    pages: int
    encrypted: bool
    has_text_layer: bool
    error: str | None = None


def inspect_pdf(name: str, data: bytes) -> PdfInfo:
    if not data[:5] == b"%PDF-":
        return PdfInfo(name, len(data), 0, False, False, "Not a PDF file.")
    if len(data) > MAX_BYTES:
        return PdfInfo(name, len(data), 0, False, False, f"File is {len(data) / 1e6:.1f} MB; the limit is 32 MB.")
    try:
        r = PdfReader(io.BytesIO(data))
    except Exception as e:  # noqa: BLE001
        return PdfInfo(name, len(data), 0, False, False, f"Could not read PDF: {e}")
    if r.is_encrypted:
        try:
            if r.decrypt("") == 0:
                return PdfInfo(name, len(data), 0, True, False, "PDF is password-protected. Upload an unlocked copy.")
        except Exception:  # noqa: BLE001
            return PdfInfo(name, len(data), 0, True, False, "PDF is password-protected. Upload an unlocked copy.")
    n = len(r.pages)
    if n > MAX_PAGES:
        return PdfInfo(name, len(data), n, False, False, f"PDF has {n} pages; the limit is {MAX_PAGES}.")
    text_chars = 0
    for p in r.pages[: min(n, 5)]:
        try:
            text_chars += len((p.extract_text() or "").strip())
        except Exception:  # noqa: BLE001
            pass
    return PdfInfo(name, len(data), n, False, text_chars > 50)
