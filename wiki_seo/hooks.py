app_name = "wiki_seo"
app_title = "Wiki SEO"
app_publisher = "FOSS-On-Line"
app_description = "Server-side SEO for Frappe Wiki pages: lang, hreflang, title suffix and X-Robots-Tag through an after_request hook"
app_email = "foss@foss.ua"
app_license = "mit"
required_apps = ["frappe"]

after_request = ["wiki_seo.hook.after_request"]

# A change of a page or a space drops the route map; the next request builds it again.
doc_events = {
	"Wiki Page": {
		"on_update": "wiki_seo.routes.clear",
		"on_trash": "wiki_seo.routes.clear",
		"after_rename": "wiki_seo.routes.clear",
	},
	"Wiki Space": {
		"on_update": "wiki_seo.routes.clear",
		"on_trash": "wiki_seo.routes.clear",
	},
}
