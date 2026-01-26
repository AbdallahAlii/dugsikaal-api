from __future__ import annotations

import logging
from typing import Any, Dict
from flask import render_template
log = logging.getLogger(__name__)
def render_html_template(template: str, context: Dict[str, Any]) -> str:
    """
    Thin wrapper around Flask's render_template.
    Adds logging for debugging.
    """
    try:
        log.info(f"Rendering template: {template} with context: {context}")
        html_output = render_template(template, **context)
        log.info(f"Template rendered successfully.")
        return html_output
    except Exception as e:
        log.error(f"Error rendering template {template}: {e}")
        raise
