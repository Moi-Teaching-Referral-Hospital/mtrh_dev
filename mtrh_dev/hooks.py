# -*- coding: utf-8 -*-
from __future__ import unicode_literals
from frappe import _
from . import __version__ as app_version

app_name = "mtrh_dev"
app_title = "MTRH Dev"
app_publisher = "MTRH"
app_description = "For all MTRH dev Frappe and ERPNext modifications"
app_icon = "octicon octicon-file-directory"
app_color = "grey"
app_email = "erp@mtrh.go.ke"
app_license = "MIT"
website_context = {
	"favicon": "/assets/mtrh_dev/images/logo.jpg",
	"splash_image": "/assets/mtrh_dev/images/logo.jpg"
}
app_logo_url = '/assets/mtrh_dev/images/logo.jpg'
#mtrh logo
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
	"*": {
		"before_save": [
			"mtrh_dev.mtrh_dev.utilities.log_time_to_action",
			"mtrh_dev.mtrh_dev.utilities.capitalize_essential_fields",
			"mtrh_dev.mtrh_dev.utilities.append_attachments_to_file"
		],
		"before_submit": [
			"mtrh_dev.mtrh_dev.utilities.log_time_to_action"
		],
		"before_cancel": [
			"mtrh_dev.mtrh_dev.utilities.log_time_to_action"
		]
	},
	"Material Request":{
		"before_save":"mtrh_dev.mtrh_dev.utilities.process_workflow_log",	
		"on_cancel": "mtrh_dev.mtrh_dev.utilities.process_workflow_log",		
		"before_submit":["mtrh_dev.mtrh_dev.utilities.process_workflow_log",
		"mtrh_dev.mtrh_dev.workflow_custom_action.auto_generate_purchase_order_by_material_request"]
	},
	"Tender Quotations Evaluations":{
		"before_save":"mtrh_dev.mtrh_dev.utilities.process_workflow_log",
		"before_submit": ["mtrh_dev.mtrh_dev.tqe_on_submit_operations.apply_tqe_operation", "mtrh_dev.mtrh_dev.utilities.process_workflow_log"],
		"on_cancel": "mtrh_dev.mtrh_dev.utilities.process_workflow_log"
	},
	"Procurement Plan":{
		"before_save":"mtrh_dev.mtrh_dev.utilities.process_workflow_log",
		"before_submit":"mtrh_dev.mtrh_dev.utilities.process_workflow_log",
		"on_cancel": "mtrh_dev.mtrh_dev.utilities.process_workflow_log"
	},
	"Purchase Order":{
		"before_save":["mtrh_dev.mtrh_dev.utilities.process_workflow_log",
		"mtrh_dev.mtrh_dev.workflow_custom_action.update_material_request_item_status", "mtrh_dev.mtrh_dev.utilities.reassign_ownership"],
		"before_submit":"mtrh_dev.mtrh_dev.utilities.validate_budget",
		"on_cancel": "mtrh_dev.mtrh_dev.utilities.process_workflow_log",
		"on_submit": "mtrh_dev.mtrh_dev.tqe_evaluation.stage_supplier_email"	
	},
	"Request for Quotation":{
		"before_save":["mtrh_dev.mtrh_dev.workflow_custom_action.update_material_request_item_status",
		"mtrh_dev.mtrh_dev.utilities.clean_up_rfq", "mtrh_dev.mtrh_dev.utilities.reassign_ownership"],		
		"on_submit":"mtrh_dev.mtrh_dev.tqe_evaluation.stage_supplier_email"			
	},
	"Tender Quotation Award":{
		#"before_save":"mtrh_dev.mtrh_dev.tender_quotation_utils.submit_manually_entered_tqas",
		"before_submit":"mtrh_dev.mtrh_dev.doctype.tender_quotation_award.tender_quotation_award.update_price_list"
	},
	"Purchase Receipt":{
		"before_save":["mtrh_dev.mtrh_dev.utilities.check_purchase_receipt_before_save", "mtrh_dev.mtrh_dev.purchase_receipt_utils.recall_purchase_receipt",
		"mtrh_dev.mtrh_dev.utilities.process_workflow_log"]
	},
	"Quality Inspection":{
		"before_save":["mtrh_dev.mtrh_dev.purchase_receipt_utils.recall_quality_inspection_item",
		 			"mtrh_dev.mtrh_dev.utilities.process_workflow_log"],
		"on_submit":["mtrh_dev.mtrh_dev.purchase_receipt_utils.update_percentage_inspected",
				"mtrh_dev.mtrh_dev.tqe_evaluation.create_grn_qualityinspectioncert_debitnote_creditnote"],
		"before_submit":"mtrh_dev.mtrh_dev.utilities.process_workflow_log"
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
		"before_save":["mtrh_dev.mtrh_dev.utilities.enforce_unique_item_name",
		"mtrh_dev.mtrh_dev.stock_utils.item_workflow_operations",
		"mtrh_dev.mtrh_dev.utilities.enforce_variants"],
		"on_submit":"mtrh_dev.mtrh_dev.stock_utils.item_workflow_operations"
	},
	"Stock Entry":{
		"before_save": "mtrh_dev.mtrh_dev.utilities.process_workflow_log"
	},
	"Document Expiry Extension":{
		"before_save": ["mtrh_dev.mtrh_dev.stock_utils.validate_expiry_extension",
		"mtrh_dev.mtrh_dev.utilities.process_workflow_log"],
		"on_submit": "mtrh_dev.mtrh_dev.stock_utils.document_expiry_extension"	
	},
	"Chat Message":{
		"before_save": "mtrh_dev.mtrh_dev.utilities.alert_user_on_message"
	},
	"Workflow Action":{
		"before_save": "mtrh_dev.mtrh_dev.utilities.alert_user_on_workflowaction"
	},
	"Employee":{
		#"before_save": "mtrh_dev.mtrh_dev.utilities.assign_department_permissions"
	},
	"Comment":{
		"before_save": "mtrh_dev.mtrh_dev.utilities.process_comment"
	},
	"Supplier Quotation":{
		#"before_save": "mtrh_dev.mtrh_dev.tender_quotation_utils.perform_sq_save_operations",
		"before_submit": "mtrh_dev.mtrh_dev.tender_quotation_utils.perform_sq_submit_operations"
	},
	"Tender Quotation Opening":{
		"before_submit": "mtrh_dev.mtrh_dev.tender_quotation_utils.perform_tqo_submit_operations"
	},
	"Externally Generated Purchase Order":{
		"before_save": "mtrh_dev.mtrh_dev.stock_utils.external_lpo_save_transaction",
		"before_submit": "mtrh_dev.mtrh_dev.stock_utils.externally_generated_po"
	},
	"File":{
		"before_save": "mtrh_dev.mtrh_dev.utilities.sync_purchase_receipt_attachments"
	},
	"Purchase Invoice":{
		"before_save": ["mtrh_dev.mtrh_dev.utilities.update_pinv_attachments_before_save", 
		"mtrh_dev.mtrh_dev.invoice_utils.validate_invoices_in_po"]
	},
	"Payment Request":{
		"before_save": "mtrh_dev.mtrh_dev.invoice_utils.update_invoice_state",
		"before_submit": "mtrh_dev.mtrh_dev.invoice_utils.finalize_invoice_on_pv_submit",
		"on_submit": "mtrh_dev.mtrh_dev.invoice_utils.make_payment_entry_on_pv_submit"
	},
	"Document Email Dispatch":{
		"after_insert":"mtrh_dev.mtrh_dev.tqe_evaluation.dispatch_staged_email",
		#"on_update":"mtrh_dev.mtrh_dev.tqe_evaluation.dispatch_staged_email"			
	},
	"Project":{
		"before_save":"mtrh_dev.mtrh_dev.utilities.project_budget_submit"
	},
	"Budget":{
		"on_submit":"mtrh_dev.mtrh_dev.utilities.project_budget_approved"
	},
	"Contact":{
		"before_save":"mtrh_dev.mtrh_dev.tqe_evaluation.set_supplier_profile"
	},
	"Bid Evaluation Committee":{
		"before_save":"mtrh_dev.mtrh_dev.tqe_evaluation.update_member_list_on_opening_drafts"
	},
	"Procurement Professional Opinion":{
		"before_save":"mtrh_dev.mtrh_dev.tender_quotation_utils.perform_bid_schedule_save_operations"
#		"before_submit":"mtrh_dev.mtrh_dev.tender_quotation_utils.perform_bid_schedule_submit_operations"
	},
	"Task":{
		"before_save":"mtrh_dev.mtrh_dev.tasks.task_save_operations",
		"on_update":"mtrh_dev.mtrh_dev.tasks.update_task_report"
	},
	"Task Duplicator":{
		"before_submit":"mtrh_dev.mtrh_dev.tasks.task_duplicator",
		#"on_update":"mtrh_dev.mtrh_dev.tasks.update_task_report"
	},
	"SMS Log":{
		"after_insert": "mtrh_dev.mtrh_dev.utilities.mark_sms_center_document_as_scheduled"
	},
	"ToDo":{
		"after_insert":"mtrh_dev.mtrh_dev.tasks.append_task_assignment"
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
		"5 * * * *": [
			"mtrh_dev.mtrh_dev.tender_quotation_utils.professional_opinion_to_award_cron"
		]
	},
	"all": [
		"mtrh_dev.mtrh_dev.utilities.daily_pending_work_reminder"
	],
	"hourly": [
		"frappe.integrations.doctype.google_drive.google_drive.daily_backup"
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