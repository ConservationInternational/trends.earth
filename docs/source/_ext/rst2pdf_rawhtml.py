"""Sphinx extension: render flagged raw HTML tables as PNG images for PDF output.

Provides the ``.. html-table-as-image::`` directive.  For the HTML builder the
content is emitted as ordinary ``.. raw:: html``.  For the rst2pdf **PDF**
builder the HTML is rendered to a PNG screenshot (via Playwright headless
Chromium) and an ``image`` node is inserted instead.

This avoids xhtml2pdf's severe CSS limitations while keeping a single source
for both HTML and PDF documentation.

Usage in RST::

    .. html-table-as-image::
       :viewport-width: 900

       <table class="status-matrix">
         ...
       </table>

``viewport-width`` (optional, default 900) sets the Chromium viewport width in
pixels used when capturing the screenshot.
"""

import hashlib
import logging
import os
import tempfile

from docutils import nodes
from docutils.parsers.rst import Directive, directives

logger = logging.getLogger(__name__)

_IMAGE_CACHE_DIR = os.path.join(tempfile.gettempdir(), "trendsearth_html_table_images")


# ---------------------------------------------------------------------------
# Custom directive
# ---------------------------------------------------------------------------


class HtmlTableAsImageDirective(Directive):
    """Mark a raw HTML block for PNG rendering in PDF output."""

    has_content = True
    option_spec = {
        "viewport-width": directives.positive_int,
    }

    def run(self):
        html_content = "\n".join(self.content)
        raw_node = nodes.raw("", html_content, format="html")
        container = nodes.container()
        container["classes"] = ["html-table-as-image"]
        container["viewport_width"] = self.options.get("viewport-width", 900)
        container += raw_node
        return [container]


# ---------------------------------------------------------------------------
# PNG rendering helpers
# ---------------------------------------------------------------------------


def _read_custom_css(app):
    """Read the project's custom.css so rendered PNGs match the HTML site."""
    conf_dir = app.confdir  # docs/source
    css_path = os.path.join(os.path.dirname(conf_dir), "resources", "en", "custom.css")
    if os.path.isfile(css_path):
        with open(css_path, encoding="utf-8") as f:
            return f.read()
    return ""


def _render_html_to_png(html_fragment, css, output_path, viewport_width=900):
    """Render *html_fragment* to a PNG file using Playwright + Chromium."""
    from playwright.sync_api import sync_playwright

    full_html = (
        "<!DOCTYPE html>\n"
        '<html><head><meta charset="utf-8"><style>\n'
        "body {\n"
        "  margin: 0; padding: 16px;\n"
        '  font-family: -apple-system, "Segoe UI", Roboto, Helvetica,'
        " Arial, sans-serif;\n"
        "  font-size: 14px; background: #fff;\n"
        "}\n"
        f"{css}\n"
        "</style></head><body>\n"
        f"{html_fragment}\n"
        "</body></html>"
    )

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(
            viewport={"width": viewport_width, "height": 200},
            device_scale_factor=3,
        )
        page.set_content(full_html, wait_until="networkidle")

        # Measure actual rendered size
        bbox = page.evaluate(
            "() => { const b = document.body;"
            " return { w: b.scrollWidth, h: b.scrollHeight }; }"
        )

        page.set_viewport_size(
            {
                "width": max(bbox["w"], viewport_width),
                "height": bbox["h"] + 32,
            }
        )
        page.screenshot(path=output_path, full_page=True)
        browser.close()


# ---------------------------------------------------------------------------
# Sphinx event handler
# ---------------------------------------------------------------------------


def _process_html_tables(app, doctree, docname):
    """Replace ``html-table-as-image`` containers with PNGs for the PDF builder."""
    if app.builder.name != "pdf":
        return

    css = _read_custom_css(app)
    os.makedirs(_IMAGE_CACHE_DIR, exist_ok=True)

    for container in list(doctree.traverse(nodes.container)):
        if "html-table-as-image" not in container.get("classes", []):
            continue

        # Collect raw HTML from inside this container
        raw_nodes = list(container.traverse(nodes.raw))
        html_parts = [r.astext() for r in raw_nodes if r.get("format", "") == "html"]
        if not html_parts:
            continue

        html_fragment = "\n".join(html_parts)
        viewport_width = container.get("viewport_width", 900)

        # Deterministic filename from content hash
        content_hash = hashlib.sha256(html_fragment.encode()).hexdigest()[:12]
        png_filename = f"html_table_{content_hash}.png"
        png_path = os.path.join(_IMAGE_CACHE_DIR, png_filename)

        if not os.path.isfile(png_path):
            logger.info("Rendering HTML table to %s …", png_filename)
            try:
                _render_html_to_png(html_fragment, css, png_path, viewport_width)
            except Exception as exc:
                logger.warning(
                    "Failed to render HTML table as image: %s.  "
                    "Is Playwright installed?  "
                    "(pip install playwright && playwright install chromium)",
                    exc,
                )
                continue

        img_node = nodes.image()
        img_node["uri"] = png_path
        img_node["alt"] = "Table"
        img_node["width"] = "95%"
        container.replace_self(img_node)


# ---------------------------------------------------------------------------
# Extension entry point
# ---------------------------------------------------------------------------


def setup(app):
    app.add_directive("html-table-as-image", HtmlTableAsImageDirective)
    app.connect("doctree-resolved", _process_html_tables)
    return {"version": "2.0", "parallel_read_safe": True}
