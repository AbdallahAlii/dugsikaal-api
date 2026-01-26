from weasyprint import HTML

from tempfile import NamedTemporaryFile

def render_pdf(html: str) -> bytes:
    with NamedTemporaryFile(suffix=".pdf") as f:
        HTML(string=html).write_pdf(f.name)
        return f.read()
