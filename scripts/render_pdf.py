#!/usr/bin/env python3
"""
Render HTML to PDF using Playwright (Python). Self-contained — no Node.js
or external html2poster.js needed. Used by GitHub Actions workflow.

Usage:
    python3 render_pdf.py <html_path> <pdf_path>
"""

import sys
import os


def render_html_to_pdf(html_path, pdf_path, width_px=720):
    """Render an HTML file to a single-page PDF using Playwright."""
    from playwright.sync_api import sync_playwright

    abs_html = os.path.abspath(html_path)
    file_url = f"file://{abs_html}"

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_viewport_size({"width": width_px, "height": 1200})
        page.goto(file_url, wait_until="networkidle")

        # Wait for fonts to load
        page.wait_for_timeout(1500)

        # Measure actual content height (single-canvas poster pattern)
        height = page.evaluate("""
            () => {
                const poster = document.querySelector('.poster');
                if (poster) return poster.scrollHeight;
                return document.body.scrollHeight;
            }
        """)

        # Add small padding to avoid clipping
        height = int(height) + 5

        page.pdf(
            path=pdf_path,
            width=f"{width_px}px",
            height=f"{height}px",
            print_background=True,
            margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
            prefer_css_page_size=False,
        )
        browser.close()


def main():
    if len(sys.argv) < 3:
        print("Usage: python3 render_pdf.py <html_path> <pdf_path>")
        sys.exit(1)

    html_path = sys.argv[1]
    pdf_path = sys.argv[2]

    if not os.path.isfile(html_path):
        print(f"ERROR: HTML file not found: {html_path}")
        sys.exit(1)

    # Make sure output directory exists
    out_dir = os.path.dirname(os.path.abspath(pdf_path))
    os.makedirs(out_dir, exist_ok=True)

    try:
        render_html_to_pdf(html_path, pdf_path)
        size_kb = os.path.getsize(pdf_path) / 1024
        print(f"✓ PDF rendered: {pdf_path} ({size_kb:.1f} KB)")
    except ImportError:
        print("ERROR: Playwright not installed.")
        print("Install with: pip install playwright && playwright install chromium")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR rendering PDF: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
