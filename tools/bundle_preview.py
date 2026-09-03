"""Gera um preview.html de arquivo único (dados embutidos) p/ publicar como Artifact.

Uso: python tools/bundle_preview.py <saida.html>
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
FONT_IMPORT = (
    "@import url('https://fonts.googleapis.com/css2?"
    "family=Barlow+Semi+Condensed:wght@400;500;600"
    "&family=IBM+Plex+Mono:wght@400;500;600"
    "&family=IBM+Plex+Sans:wght@400;500;600&display=swap');\n"
)


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "preview.html"

    html = (DOCS / "index.html").read_text()
    css = (DOCS / "style.css").read_text()
    js = (DOCS / "app.js").read_text()

    body = re.search(r"<body>(.*)</body>", html, re.S).group(1)
    body = body.replace('<script src="app.js"></script>', "").strip()

    bundle = {}
    for f in sorted(DOCS.glob("data/*.json")):
        bundle[f"data/{f.name}"] = json.loads(f.read_text())

    shim = (
        "const _B = " + json.dumps(bundle, ensure_ascii=False) + ";\n"
        "const _f = window.fetch.bind(window);\n"
        "window.fetch = (u, o) => {\n"
        "  const k = String(u).split('?')[0].replace(/^\\.?\\//, '');\n"
        "  return _B[k] ? Promise.resolve({ ok: true, json: () => Promise.resolve(_B[k]) })\n"
        "               : _f(u, o);\n"
        "};\n"
    )

    parts = [
        "<title>Bet Trends</title>",
        f"<style>\n{FONT_IMPORT}{css}\n</style>",
        body,
        f"<script>\n{shim}</script>",
        f"<script>\n{js}\n</script>",
    ]
    out.write_text("\n".join(parts))
    print(f"escrito {out} ({out.stat().st_size // 1024} KB, {len(bundle)} arquivos de dados)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
