"""The `after_request` hook: SEO fixes of the Wiki pages in the served HTML, and `X-Robots-Tag` on errors and service pages.

Frappe calls the hook for every request, in `finally`, after the page is rendered (and after the page cache and the
HTML cache of the Wiki stored it, so a cached hit is rewritten too). The whole hook is wrapped in `try/except`: it never
raises, and on any error the response stays exactly as it was. Every change is computed first and applied at the end
(the headers, then one `response.set_data()`).
"""

import html
import re

import frappe

from wiki_seo import routes

CONFIG_KEY = "wiki_seo"
ROBOTS_HEADER = "X-Robots-Tag"
ROBOTS_VALUE = "noindex, nofollow"
MARK_HEADER = "X-Wiki-Seo"
# Paths the hook never looks at (a path segment, so `/apptop-...` is not `/app`).
SKIPPED_PREFIXES = ("/api", "/app", "/desk", "/assets", "/files", "/private", "/socket.io")


def _tag(name: bytes, attribute: bytes, value: bytes) -> re.Pattern:
	"""A start tag `<name ... attribute="value" ...>` (any quotes, any order of the attributes)."""
	value = re.escape(value)
	return re.compile(
		rb"<%s\b[^>]*(?<![\w:-])%s\s*=\s*(?:\"%s\"|'%s'|%s(?=[\s/>]))[^>]*>"
		% (name, attribute, value, value, value),
		re.IGNORECASE,
	)


# The query arguments of the Wiki editor and of a patch preview: the page under them is not the published one.
EDITOR_ARGS = ("editWiki", "newWiki", "wikiPagePatch")

HEAD_END = re.compile(rb"</head\s*>", re.IGNORECASE)
HTML_TAG = re.compile(rb"<html\b[^>]*>", re.IGNORECASE)
LANG_ATTR = re.compile(rb"(?<![\w:-])lang\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", re.IGNORECASE)
META_LANGUAGE = _tag(b"meta", b"name", b"language")
CONTENT_ATTR = re.compile(rb"(?<![\w:-])content\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", re.IGNORECASE)
TITLE = re.compile(rb"(<title\b[^>]*>)(.*?)(</title\s*>)", re.IGNORECASE | re.DOTALL)
CANONICAL = _tag(b"link", b"rel", b"canonical")
HREFLANG_LINK = re.compile(rb"<link\b[^>]*\bdata-fd-hreflang\b[^>]*>", re.IGNORECASE)
OG_SITE_NAME = _tag(b"meta", b"property", b"og:site_name")
OG_TITLE = _tag(b"meta", b"property", b"og:title")
# The logo of the Wiki navbar: `<a class="navbar-brand" ... href="...">`, its attributes over several lines.
BRAND_ANCHOR = re.compile(
	rb"<a\b[^>]*?\bclass\s*=\s*[\"'][^\"']*(?<![\w-])navbar-brand(?![\w-])[^\"']*[\"'][^>]*>",
	re.IGNORECASE | re.DOTALL,
)
HREF_ATTR = re.compile(rb"(?<![\w:-])href\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", re.IGNORECASE | re.DOTALL)


def _list(value) -> list:
	"""A list or tuple of strings; anything else is an empty list (a bad value never fails the hook)."""
	return [str(item) for item in value if isinstance(item, str)] if isinstance(value, (list, tuple)) else []


def _text(value, default: str = "") -> str:
	return value if isinstance(value, str) else default


class Config:
	"""The site config key `wiki_seo` (a dict), read for every request: no restart is needed to change or stop it.

	A missing or malformed field takes a safe default (no hosts: the hook does nothing; no spaces: no body rule);
	unknown fields are ignored.
	"""

	def __init__(self, raw: dict):
		self.hosts = {normalise_host(host) for host in _list(raw.get("hosts"))}
		self.base_url = _text(raw.get("base_url")).rstrip("/")
		spaces = raw.get("spaces") if isinstance(raw.get("spaces"), dict) else {}
		self.spaces = {
			str(space).strip("/"): language
			for space, language in spaces.items()
			if isinstance(language, str) and str(space).strip("/")
		}
		self.x_default = _text(raw.get("x_default"), "uk") or "uk"
		self.title_suffix = _text(raw.get("title_suffix"))
		self.site_name = _text(raw.get("site_name"))
		# the first path segment of a service route (`login`, `orders`), matched without the case
		self.noindex_paths = {
			path.strip("/").lower() for path in _list(raw.get("noindex_paths")) if path.strip("/")
		}
		self.noindex_errors = raw.get("noindex_errors", True) is not False


OFF = (False, 0, "0", "false", "off", "no")


def load_config():
	"""The configuration of the site, or None when the key is absent, not a dict or `enabled` is false (kill switch)."""
	raw = frappe.local.conf.get(CONFIG_KEY)
	if not isinstance(raw, dict):
		return None
	enabled = raw.get("enabled", True)
	if (enabled.strip().lower() if isinstance(enabled, str) else enabled) in OFF:
		return None
	return Config(raw)


def normalise_host(host) -> str:
	"""Lower case, no port, no trailing dot: `WWW.FossDoc.com:443` -> `www.fossdoc.com`."""
	host = str(host or "").strip().lower()
	if host.startswith("["):  # an IPv6 literal
		return host.split("]", 1)[0] + "]"
	return host.split(":", 1)[0].rstrip(".")


def after_request(response=None, request=None):
	try:
		_after_request(response, request)
	except Exception:  # noqa: BLE001  every request of the site passes here: a bug must not change a response
		frappe.logger(CONFIG_KEY).error(
			"wiki_seo: the hook failed, the response is left as it was", exc_info=True
		)


def _after_request(response, request):
	config = load_config()
	if config is None or response is None:
		return
	request = request if request is not None else getattr(frappe.local, "request", None)
	if request is None or normalise_host(request.host) not in config.hosts:
		return
	if request.method not in ("GET", "HEAD"):
		return
	if response.direct_passthrough or response.is_streamed:
		return
	if response.headers.get("Content-Encoding"):
		return
	path = request.path or "/"
	if any(path == prefix or path.startswith(prefix + "/") for prefix in SKIPPED_PREFIXES):
		return
	if 300 <= response.status_code < 400:
		return

	add_robots = header_rules(config, path, response)
	data = body_rules(config, path, response, request.args)

	if add_robots:
		response.headers.add(ROBOTS_HEADER, ROBOTS_VALUE)
	if data is not None:
		response.set_data(data)
		response.headers[MARK_HEADER] = "1"


def header_rules(config: Config, path: str, response) -> bool:
	"""Whether `X-Robots-Tag: noindex, nofollow` is to be added: a service path (any status) or an HTML error page."""
	present = [value.replace(" ", "").lower() for value in response.headers.getlist(ROBOTS_HEADER)]
	if ROBOTS_VALUE.replace(" ", "") in present:
		return False
	# `/orders` and `/orders/SO-0001` alike; the query string is not part of `request.path`
	segment = path.strip("/").split("/", 1)[0].lower()
	if segment and segment in config.noindex_paths:
		return True
	return config.noindex_errors and response.status_code >= 400 and response.mimetype == "text/html"


def body_rules(config: Config, path: str, response, args=None):
	"""The new body of a Wiki page of a configured space, or None when nothing is to change."""
	if response.status_code != 200 or response.mimetype != "text/html":
		return None
	if args and any(name in args for name in EDITOR_ARGS):  # the editor and a patch preview: not the page
		return None
	if response.mimetype_params.get("charset", "utf-8").lower() != "utf-8":
		return None
	if not config.spaces:
		return None
	route_map = routes.get()
	page = route_map.page(path)
	if page is None or page[0] not in config.spaces:
		return None
	space, slug = page
	data = response.get_data()
	head_end = HEAD_END.search(data)
	if head_end is None:
		return None
	head, rest = data[: head_end.start()], data[head_end.start() :]
	language = config.spaces[space]
	head = set_html_lang(head, language)
	head = set_meta_language(head, language)
	head = add_hreflang(head, config, route_map, slug)
	head = add_title_suffix(head, config.title_suffix)
	head = add_site_name(head, config.site_name)
	rest = set_logo_href(rest, route_map.first[space], space)  # a page of the map: its space has a first
	new = head + rest
	return None if new == data else new


def _attr(value: str) -> bytes:
	return html.escape(value, quote=True).encode()


def _set_attr(tag: bytes, pattern: re.Pattern, name: bytes, value: bytes) -> bytes:
	"""`tag` with the attribute `name` set to `value` (added after the tag name when it is missing)."""
	quoted = b'"' + value + b'"'
	match = pattern.search(tag)
	if match:
		return tag[: match.start(1)] + quoted + tag[match.end(1) :]
	cut = re.match(rb"<[\w:-]+", tag).end()
	return tag[:cut] + b" " + name + b"=" + quoted + tag[cut:]


def set_html_lang(head: bytes, language: str) -> bytes:
	match = HTML_TAG.search(head)
	if match is None:
		return head
	tag = _set_attr(match.group(0), LANG_ATTR, b"lang", _attr(language))
	return head[: match.start()] + tag + head[match.end() :]


def set_meta_language(head: bytes, language: str) -> bytes:
	match = META_LANGUAGE.search(head)
	if match is None:
		return head + b'<meta name="language" content="' + _attr(language) + b'">\n'
	tag = _set_attr(match.group(0), CONTENT_ATTR, b"content", _attr(language))
	return head[: match.start()] + tag + head[match.end() :]


def hreflang_links(config: Config, route_map, slug: str) -> bytes:
	"""One link per space that publishes the slug, then `x-default`; nothing for a slug of one space."""
	languages = route_map.languages(slug, config.spaces)
	if len(languages) < 2:
		return b""
	spaces = {}
	for space, language in config.spaces.items():
		spaces.setdefault(language, space)
	default = config.x_default if config.x_default in languages else languages[0]

	def link(code, language):
		href = f"{config.base_url}/{spaces[language]}/{slug}"
		return b'<link rel="alternate" hreflang="%s" href="%s" data-fd-hreflang>' % (_attr(code), _attr(href))

	return b"".join(link(language, language) for language in languages) + link("x-default", default)


def add_hreflang(head: bytes, config: Config, route_map, slug: str) -> bytes:
	if HREFLANG_LINK.search(head):
		return head
	links = hreflang_links(config, route_map, slug)
	if not links:
		return head
	canonical = CANONICAL.search(head)
	at = canonical.end() if canonical else len(head)
	return head[:at] + links + head[at:]


def add_title_suffix(head: bytes, suffix: str) -> bytes:
	match = TITLE.search(head)
	if match is None or not suffix:
		return head
	escaped = html.escape(suffix, quote=False).encode()
	text = match.group(2).rstrip()
	if text.endswith((escaped, suffix.encode())):
		return head
	return head[: match.start(2)] + text + escaped + head[match.end(2) :]


def add_site_name(head: bytes, site_name: str) -> bytes:
	if not site_name or OG_SITE_NAME.search(head):
		return head
	tag = b'<meta property="og:site_name" content="' + _attr(site_name) + b'">'
	og_title = OG_TITLE.search(head)
	at = og_title.end() if og_title else len(head)
	return head[:at] + tag + head[at:]


def set_logo_href(rest: bytes, first_slug: str, space: str) -> bytes:
	"""The first navbar anchor (`class="navbar-brand"`) points to the first page of the sidebar of the space.

	The template writes `href="/<space>"` (a 301 to that page) when the space has a logo and `href=" /"` (the site root,
	with a space) when it has none; both are replaced. A page without the anchor keeps its body.
	"""
	match = BRAND_ANCHOR.search(rest)
	if match is None:
		return rest
	target = _attr(f"/{space}/{first_slug}")
	tag = match.group(0)
	href = HREF_ATTR.search(tag)
	if href and href.group(1).strip(b"\"'").strip() == target:
		return rest
	tag = _set_attr(tag, HREF_ATTR, b"href", target)
	return rest[: match.start()] + tag + rest[match.end() :]
