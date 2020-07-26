# -*- coding: utf-8 -*-
from __future__ import unicode_literals
from frappe import _
from . import __version__ as app_version
from frappe.core.doctype.user_permission.user_permission import clear_user_permissions

app_name = "mtrh_dev"
app_title = "MTRH Dev"
app_publisher = "MTRH"
app_description = "For all MTRH dev Frappe and ERPNext modifications"
app_icon = "octicon octicon-file-directory"
app_color = "grey"
app_email = "erp@mtrh.go.ke"
app_license = "MIT"

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/mtrh_dev/css/mtrh_dev.css"
# app_include_js = "/assets/mtrh_dev/js/mtrh_dev.js"
app_include_js = ["/assets/mtrh_dev/js/utilities.js"]

# include js, css files in header of web template
# web_include_css = "/assets/mtrh_dev/css/mtrh_dev.css"
# web_include_js = "/assets/mtrh_dev/js/mtrh_dev.js"

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
#	"Role": "home_page"
# }

# Website user home page (by function)
# get_website_user_home_page = "mtrh_dev.utils.get_home_page"

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]
#fixtures =["Custom Script","Server Script",'Workflow State','Workflow Action Master',"Role", "Role Profile", {"dt":"Workflow","filters":{"is_active":"1"}},
#			"UOM","Item Group","Supplier"]
#,"Tender Number","Tender Quotation Award",{"dt":"Item","filters":{"creation":[">","2020-05-26"],"disabled":"0"}}
#fixtures =["Email Account"]


default_mail_footer = "MTRH Enterprise System"
# Installation
# ------------

# before_install = "mtrh_dev.install.before_install"
# after_install = "mtrh_dev.install.after_install"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "mtrh_dev.notifications.get_notification_config"

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
	"Material Request":{
		"before_save":"mtrh_dev.mtrh_dev.utilities.process_workflow_log",	
		"on_cancel": "mtrh_dev.mtrh_dev.utilities.process_workflow_log",		
		"before_submit":["mtrh_dev.mtrh_dev.utilities.process_workflow_log","mtrh_dev.mtrh_dev.workflow_custom_action.auto_generate_purchase_order_by_material_request"]
	},
	"Tender Quotations Evaluations":{
		"before_save":"mtrh_dev.mtrh_dev.utilities.process_workflow_log",
		"before_submit":"mtrh_dev.mtrh_dev.utilities.process_workflow_log",
		"on_cancel": "mtrh_dev.mtrh_dev.utilities.process_workflow_log"
	},
	"Procurement Plan":{
		"before_save":"mtrh_dev.mtrh_dev.utilities.process_workflow_log",
		"before_submit":"mtrh_dev.mtrh_dev.utilities.process_workflow_log",
		"on_cancel": "mtrh_dev.mtrh_dev.utilities.process_workflow_log"
	},
	"Purchase Order":{
		"before_save":["mtrh_dev.mtrh_dev.utilities.process_workflow_log","mtrh_dev.mtrh_dev.workflow_custom_action.update_material_request_item_status"],
		"before_submit":"mtrh_dev.mtrh_dev.utilities.validate_budget",
		"on_cancel": "mtrh_dev.mtrh_dev.utilities.process_workflow_log"
	},
	"Tender Quotations Evaluations":{
		"before_submit":"mtrh_dev.mtrh_dev.tqe_on_submit_operations.apply_tqe_operation"
	},
	"Request for Quotation":{
		"before_save":["mtrh_dev.mtrh_dev.workflow_custom_action.update_material_request_item_status","mtrh_dev.mtrh_dev.utilities.Check_Rfq_Opinion"],		
		"on_submit":["mtrh_dev.mtrh_dev.tqe_evaluation.send_rfq_supplier_emails","mtrh_dev.mtrh_dev.tqe_evaluation.send_adhoc_members_emails"]
				
	},
	"Tender Quotation Award":{
		"before_submit":"mtrh_dev.mtrh_dev.doctype.tender_quotation_award.tender_quotation_award.update_price_list"
	},
	"Purchase Receipt":{
		"before_save":["mtrh_dev.mtrh_dev.utilities.process_workflow_log","mtrh_dev.mtrh_dev.utilities.check_purchase_receipt_before_save"]
	},
	"Quality Inspection":{
		"before_submit":"mtrh_dev.mtrh_dev.utilities.process_workflow_log",
		"on_submit":["mtrh_dev.mtrh_dev.purchase_receipt_utils.update_percentage_inspected","mtrh_dev.mtrh_dev.tqe_evaluation.create_grn_qualityinspectioncert_debitnote_creditnote"],
	},
	"Store Allocation":{
		"before_save":"mtrh_dev.mtrh_dev.doctype.store_allocation.store_allocation.check_duplicate_allocation",
		"on_submit":"mtrh_dev.mtrh_dev.doctype.store_allocation.store_allocation.insert_user_permissions"
	},
	"Stock Reconciliation":{
		"before_save":["mtrh_dev.mtrh_dev.utilities.process_workflow_log", "mtrh_dev.mtrh_dev.stock_utils.stock_reconciliation_set_default_price"]
		#"on_submit":"mtrh_dev.mtrh_dev.doctype.store_allocation.store_allocation.insert_user_permissions"
	},
	"Item":{
		"before_save":"mtrh_dev.mtrh_dev.stock_utils.item_workflow_operations",
		"on_submit":"mtrh_dev.mtrh_dev.stock_utils.item_workflow_operations"
	},
	"Stock Entry":{
		"before_save": "mtrh_dev.mtrh_dev.utilities.process_workflow_log"
	},
	"Document Expiry Extension":{
		"before_save": "mtrh_dev.mtrh_dev.utilities.process_workflow_log",
		"on_submit": "mtrh_dev.mtrh_dev.stock_utils.document_expiry_extension"	
	},
	"Chat Message":{
		"before_save": "mtrh_dev.mtrh_dev.utilities.alert_user_on_message"
	},
	"Workflow Action":{
		"before_save": "mtrh_dev.mtrh_dev.utilities.alert_user_on_workflowaction"
	},
	"Employee":{
		"before_save": "mtrh_dev.mtrh_dev.utilities.assign_department_permissions"
	},
	"Comment":{
		"before_save": "mtrh_dev.mtrh_dev.utilities.send_comment_sms"
	},
	"Supplier Quotation":{
		"before_save": "mtrh_dev.mtrh_dev.tender_quotation_utils.create_tq_opening_doc"
	}

 }

# Scheduled Tasks
# ---------------

# 	"all": [
# 		"mtrh_dev.tasks.all"
# 	],
# 	"daily": [
# 		"mtrh_dev.tasks.daily"
# 	],
# 	"hourly": [
# 		"mtrh_dev.tasks.hourly"
# 	],
# 	"weekly": [
# 		"mtrh_dev.tasks.weekly"
# 	]
# 	"monthly": [
# 		"mtrh_dev.tasks.monthly"
# 	]
#}

scheduler_events = {
    "cron": {
        "* * * * *": [
			"frappe.email.queue.flush",
			"frappe.email.doctype.email_account.email_account.pull",
			"frappe.email.doctype.email_account.email_account.notify_unreplied",
			"frappe.monitor.flush"
        ]
	},
	"hourly": [
		"frappe.integrations.doctype.google_drive.google_drive.daily_backup",
	]
}
# Testing
# -------

# before_tests = "mtrh_dev.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "mtrh_dev.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "mtrh_dev.task.get_dashboard_data"
# }

