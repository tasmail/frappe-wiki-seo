"""Cut a test fixture from a Wiki page as a site served it (saved by a plain public GET).

    python -I scripts/cut_fixture.py <saved.html> <source url> <fixture.html>

The fixture keeps the bytes the hook reads and edits: everything up to the end of the opening `<body>` tag (the whole
`<head>`), the dark-mode script that follows it, the navbar up to the end of its brand container (the logo anchor),
and the script of the Wiki Settings (it holds `data-fd-hreflang` and `.navbar-brand` as text, which the hook must not
take for tags). The SVG sprites, the navbar items, the sidebar and the content are cut and marked by comments.
"""

import re
import sys
from pathlib import Path


def cut(page: str, source: str) -> str:
	body = re.search(r"<body\b[^>]*>", page)
	script_end = page.index("</script>", body.end()) + len("</script>")
	nav = page.index('<nav class="wiki-navbar')
	anchor_end = page.index("</a>", page.index('class="navbar-brand"', nav))
	brand_end = page.index("</div>", anchor_end) + len("</div>")
	marker = page.index("data-fd-hreflang", brand_end)
	settings = page[page.rfind("<script", 0, marker) : page.index("</script>", marker) + len("</script>")]
	return (
		page[:script_end]
		+ "\n\t<!-- fixture: SVG sprites cut -->\n\n"
		+ page[nav:brand_end]
		+ "\n<!-- fixture: navbar items, sidebar and content cut -->\n</nav>\n"
		+ settings
		+ "\n</body>\n</html>\n"
		+ f"<!-- fixture: cut by scripts/cut_fixture.py from {source} as served on 2026-11-09 (Wiki 2372f859f6) -->\n"
	)


if __name__ == "__main__":
	saved, source, out = sys.argv[1:4]
	Path(out).write_text(cut(Path(saved).read_text(encoding="utf-8"), source), encoding="utf-8")
