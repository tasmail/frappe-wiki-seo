"""The `after_request` hook: SEO fixes of the Wiki pages in the served HTML, and `X-Robots-Tag` on errors and service pages.

Frappe calls the hook for every request, in `finally`, after the page is rendered (and after the page cache and the
HTML cache of the Wiki stored it, so a cached hit is rewritten too). The whole hook is wrapped in `try/except`: it never
raises, and on any error the response stays exactly as it was. Every change is computed first and applied at the end
(the headers, then one `response.set_data()`).
"""

import html
import re
import time
from urllib.parse import quote

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
		# the routes of the spaces in lower case: `/Docs/...` is the same space
		self.spaces = {
			str(space).strip("/").lower(): language
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


# Only an explicit "on" value enables the hook; anything else (absent, null, "", "disabled", false) is the kill switch.
ON = ("1", "on", "true", "yes")


def enabled(value) -> bool:
	if isinstance(value, bool):
		return value
	if isinstance(value, int):
		return value == 1
	return isinstance(value, str) and value.strip().lower() in ON


def load_config():
	"""The configuration of the site, or None when the key is absent, not a dict or not explicitly enabled."""
	raw = frappe.local.conf.get(CONFIG_KEY)
	if not isinstance(raw, dict) or not enabled(raw.get("enabled")):
		return None
	return Config(raw)


def normalise_host(host) -> str:
	"""Lower case, no port, no trailing dot: `WWW.FossDoc.com:443` -> `www.fossdoc.com`."""
	host = str(host or "").strip().lower()
	if host.startswith("["):  # an IPv6 literal
		return host.split("]", 1)[0] + "]"
	return host.split(":", 1)[0].rstrip(".")


LOG_INTERVAL = (
	60  # seconds: a failure that repeats on every request is logged at most once a minute per process
)
RETRY_AFTER = (
	60  # seconds: after the route map failed (no Wiki, a database or cache error) it is not asked again
)
_last_log = {}
_route_map_down_until = 0.0


def _log(kind: str, message: str):
	"""Log an error with its traceback, at most once per LOG_INTERVAL for each kind; the logging itself never raises."""
	try:
		now = time.monotonic()
		if now - _last_log.get(kind, float("-inf")) < LOG_INTERVAL:
			return
		_last_log[kind] = now
		frappe.logger(CONFIG_KEY).error(message, exc_info=True)
	except Exception:  # noqa: BLE001, S110  a broken logger must not fail the request either
		pass


def after_request(response=None, request=None):
	try:
		_after_request(response, request)
	except Exception:  # noqa: BLE001  every request of the site passes here: a bug must not change a response
		_log("hook", "wiki_seo: the hook failed, the response is left as it was")


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

	# the header rules first and on their own: a failure of the body rules (the route map, a rule) never costs the header
	if header_rules(config, path, response):
		response.headers.add(ROBOTS_HEADER, ROBOTS_VALUE)
	try:
		data = body_rules(config, path, response, request.args)
	except Exception:  # noqa: BLE001  the body stays as it was
		_log("body", "wiki_seo: a body rule failed, the body is left as it was")
		return
	if data is not None:
		response.set_data(data)
		response.headers[MARK_HEADER] = "1"


def in_spaces(config: Config, path: str) -> bool:
	"""Whether the path is under one of the configured spaces (the case ignored): only then is the route map asked."""
	route = path.strip("/").lower()
	return any(route.startswith(space + "/") for space in config.spaces)


def route_map_or_none():
	"""The route map, or None while it fails (logged at most once a minute, not asked again for RETRY_AFTER s)."""
	global _route_map_down_until
	if time.monotonic() < _route_map_down_until:
		return None
	try:
		return routes.get()
	except Exception:  # noqa: BLE001  no Wiki, a database or a cache error: only the body rules are skipped
		_route_map_down_until = time.monotonic() + RETRY_AFTER
		_log("routes", "wiki_seo: the route map failed, the body rules are skipped")
		return None


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
	if not in_spaces(config, path):
		return None
	route_map = route_map_or_none()
	if route_map is None:
		return None
	page = route_map.page(path)
	if page is None or page[0].lower() not in config.spaces:
		return None
	space, slug = page
	space_key = space.lower()
	data = response.get_data()
	head_end = HEAD_END.search(data)
	if head_end is None:
		return None
	head, rest = data[: head_end.start()], data[head_end.start() :]
	language = config.spaces[space_key]
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


def _url(space: str, slug: str) -> str:
	"""`/<space>/<slug>` with the slug percent-quoted (the space route keeps its slashes)."""
	return "/" + quote(space, safe="/-._~") + "/" + quote(slug, safe="-._~")


def hreflang_links(config: Config, route_map, slug: str) -> bytes:
	"""One link per language that publishes the slug, then `x-default`; nothing for a slug of one language."""
	spaces = {}  # language -> the first space of that language that publishes the slug
	for space, language in config.spaces.items():
		if language not in spaces and route_map.page(f"{space}/{slug}"):
			spaces[language] = route_map.page(f"{space}/{slug}")[0]
	languages = list(spaces)
	if len(languages) < 2:
		return b""
	default = config.x_default if config.x_default in languages else languages[0]

	def link(code, language):
		href = config.base_url + _url(spaces[language], slug)
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
	target = _attr(_url(space, first_slug))
	tag = match.group(0)
	href = HREF_ATTR.search(tag)
	if href and href.group(1).strip(b"\"'").strip() == target:
		return rest
	tag = _set_attr(tag, HREF_ATTR, b"href", target)
	return rest[: match.start()] + tag + rest[match.end() :]
