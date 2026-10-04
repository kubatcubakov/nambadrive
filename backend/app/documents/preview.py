"""Raster previews, isolated in a time-limited subprocess by the API."""

from __future__ import annotations

import io
import sys
import warnings
from pathlib import Path

from PIL import Image


def render(path: str, mime: str, page: int) -> bytes:
    warnings.simplefilter("error", Image.DecompressionBombWarning)
    Image.MAX_IMAGE_PIXELS = 25000000
    if mime == "application/pdf":
        import pypdfium2 as pdfium  # type: ignore[import-untyped]

        with pdfium.PdfDocument(path) as document:
            if page < 0 or page >= len(document):
                raise ValueError("Invalid preview page")
            pdf_page = document[page]
            try:
                width, height = pdf_page.get_size()
                if width <= 0 or height <= 0:
                    raise ValueError("Invalid page dimensions")
                scale = min(1600 / width, 1600 / height, 2)
                bitmap = pdf_page.render(scale=scale)
                try:
                    image = bitmap.to_pil().convert("RGB")
                finally:
                    bitmap.close()
            finally:
                pdf_page.close()
    elif mime in {"image/jpeg", "image/png"}:
        with Image.open(path) as original:
            original.thumbnail((1600, 1600))
            image = original.convert("RGB")
    elif mime.startswith("text/") or mime in {"application/json", "application/xml"}:
        # Text becomes pixels too: no active markup, document scripts or hidden metadata.
        from PIL import ImageDraw

        content = Path(path).read_bytes()[:12000].decode("utf-8-sig", errors="replace")
        lines = [
            line[i : i + 100]
            for line in content.splitlines()
            for i in range(0, max(1, len(line)), 100)
        ][:80]
        image = Image.new("RGB", (1200, max(60, len(lines) * 20 + 40)), "white")
        ImageDraw.Draw(image).multiline_text((20, 20), "\n".join(lines), fill="black", spacing=7)
    else:
        raise ValueError("Preview unavailable for this format")
    image.info.clear()
    out = io.BytesIO()
    image.save(out, format="PNG")
    image.close()
    return out.getvalue()


if __name__ == "__main__":
    if sys.platform == "linux":
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (1024 * 1024 * 1024, 1024 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    # Input paths are generated temporary paths, not supplied by the user.
    sys.stdout.buffer.write(render(sys.argv[1], sys.argv[2], int(sys.argv[3])))
