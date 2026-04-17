#!/usr/bin/env python3
"""Render PDF pages as PNG images for vision-based extraction.

Claude Opus 4.7 accepts images up to 2576px (up from 1568 on 4.6), with
~3× the pixel count and major document-understanding gains
(CharXiv Reasoning 69.1% → 82.1% no-tools). For table/figure-dominant
pages, passing a rendered image alongside the extracted text meaningfully
improves extraction accuracy.

Uses pdfplumber if it can produce images, else falls back to pdf2image.
Output: PNG files at state/extract_images/<sha256>_p<page>.png
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path


def render_with_pdfplumber(pdf_path: Path, pages: list[int], out_dir: Path,
                           sha256: str, res_px: int) -> list[str]:
    """pdfplumber page.to_image() — uses Wand/ImageMagick under the hood."""
    try:
        import pdfplumber  # type: ignore
    except ImportError:
        return []
    outputs = []
    with pdfplumber.open(pdf_path) as pdf:
        for p in pages:
            if p < 1 or p > len(pdf.pages):
                continue
            page = pdf.pages[p - 1]
            # to_image resolution is in DPI; tune so the long edge hits res_px
            page_pts = max(page.width, page.height)  # in points
            dpi = max(72, int(round(res_px * 72 / page_pts)))
            try:
                img = page.to_image(resolution=dpi)
            except Exception as e:
                print(f"pdfplumber to_image failed p{p}: {e}", file=sys.stderr)
                continue
            out = out_dir / f"{sha256}_p{p:03d}.png"
            img.save(str(out), format="PNG")
            outputs.append(str(out))
    return outputs


def render_with_pdf2image(pdf_path: Path, pages: list[int], out_dir: Path,
                          sha256: str, res_px: int) -> list[str]:
    """Fallback: pdf2image uses poppler. Installed via `brew install poppler`
    on macOS; `apt install poppler-utils` on Debian."""
    try:
        from pdf2image import convert_from_path  # type: ignore
    except ImportError:
        return []
    # pdf2image takes a dpi argument.
    # Approximate: 150 dpi on an 8.5x11 page = ~1275x1650 px.
    # For res_px target on the long edge of a standard page, dpi = res_px / 11.
    dpi = max(72, int(round(res_px / 11)))
    outputs = []
    for p in pages:
        try:
            imgs = convert_from_path(str(pdf_path), dpi=dpi,
                                     first_page=p, last_page=p)
        except Exception as e:
            print(f"pdf2image failed p{p}: {e}", file=sys.stderr)
            continue
        for img in imgs:
            out = out_dir / f"{sha256}_p{p:03d}.png"
            img.save(str(out), format="PNG")
            outputs.append(str(out))
    return outputs


def parse_page_list(s: str) -> list[int]:
    pages: list[int] = []
    for part in s.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            pages.extend(range(int(a), int(b) + 1))
        elif part:
            pages.append(int(part))
    return pages


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sha256", required=True)
    ap.add_argument("--pages", required=True,
                    help="Page list or range: '1' or '1,3,5' or '1-3'")
    ap.add_argument("--out", type=Path, required=True,
                    help="Output directory for PNGs")
    ap.add_argument("--res", type=int, default=2576,
                    help="Target long-edge pixels (default 2576 for Opus 4.7)")
    ap.add_argument("--project-root", type=Path, required=True)
    args = ap.parse_args()

    # Resolve PDF path from manifest
    db = (args.project_root / "state" / "manifest.sqlite").resolve()
    con = sqlite3.connect(db)
    try:
        row = con.execute(
            "SELECT canonical_path FROM pdfs WHERE sha256 = ?", (args.sha256,)
        ).fetchone()
    finally:
        con.close()
    if not row:
        print(f"sha256 not in manifest: {args.sha256}", file=sys.stderr)
        return 2
    pdf_path = Path(row[0]).resolve()
    if not pdf_path.exists():
        print(f"pdf missing from disk: {pdf_path}", file=sys.stderr)
        return 2

    args.out.mkdir(parents=True, exist_ok=True)
    pages = parse_page_list(args.pages)

    # Try pdfplumber first, then pdf2image
    outputs = render_with_pdfplumber(pdf_path, pages, args.out,
                                     args.sha256, args.res)
    if not outputs:
        outputs = render_with_pdf2image(pdf_path, pages, args.out,
                                        args.sha256, args.res)

    print(json.dumps({
        "sha256": args.sha256,
        "pdf_path": str(pdf_path),
        "rendered": outputs,
        "resolution_px": args.res,
        "count": len(outputs),
    }, indent=2))
    return 0 if outputs else 1


if __name__ == "__main__":
    sys.exit(main())
