app_name = "enable_banking"
app_title = "Enable Banking"
app_publisher = "david-loe"
app_description = "Integrate Enable Banking APIs to automatically sync bank transactions"
app_email = "kontakt@david-loe.de"
app_license = "agpl-3.0"

# Apps
# ------------------

required_apps = ["erpnext"]

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "enable_banking",
# 		"logo": "/assets/enable_banking/logo.png",
# 		"title": "Enable Banking",
# 		"route": "/enable_banking",
# 		"has_permission": "enable_banking.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/enable_banking/css/enable_banking.css"
# app_include_js = "/assets/enable_banking/js/enable_banking.js"

# include js, css files in header of web template
# web_include_css = "/assets/enable_banking/css/enable_banking.css"
# web_include_js = "/assets/enable_banking/js/enable_banking.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "enable_banking/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "enable_banking/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# automatically load and sync documents of this doctype from downstream apps
# importable_doctypes = [doctype_1]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "enable_banking.utils.jinja_methods",
# 	"filters": "enable_banking.utils.jinja_filters"
# }

# Installation
# ------------

after_install = "enable_banking.setup.after_install"
after_migrate = "enable_banking.setup.after_migrate"

# Uninstallation
# ------------

# before_uninstall = "enable_banking.uninstall.before_uninstall"
# after_uninstall = "enable_banking.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "enable_banking.utils.before_app_install"
# after_app_install = "enable_banking.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "enable_banking.utils.before_app_uninstall"
# after_app_uninstall = "enable_banking.utils.after_app_uninstall"

# Build
# ------------------
# To hook into the build process

# after_build = "enable_banking.build.after_build"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "enable_banking.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# Document Events
# ---------------
# Hook on document methods and events

doc_events = {
	"Bank Account": {
		"validate": "enable_banking.bank_account.validate_enable_banking_link",
		"on_trash": "enable_banking.bank_account.prevent_linked_bank_account_deletion",
	}
}

# Scheduled Tasks
# ---------------

scheduler_events = {
	"hourly": [
		"enable_banking.tasks.enqueue_scheduled_account_syncs",
	],
	"daily": [
		"enable_banking.tasks.purge_consumed_authorizations",
	],
}

# Testing
# -------

before_tests = "enable_banking.setup.before_tests"

# Extend DocType Class
# ------------------------------
#
# Specify custom mixins to extend the standard doctype controller.
# extend_doctype_class = {
# 	"Task": "enable_banking.custom.task.CustomTaskMixin"
# }

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "enable_banking.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "enable_banking.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["enable_banking.utils.before_request"]
# after_request = ["enable_banking.utils.after_request"]

# Job Events
# ----------
# before_job = ["enable_banking.utils.before_job"]
# after_job = ["enable_banking.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"enable_banking.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []
