from __future__ import unicode_literals
import frappe
from frappe import _

def get_context(context):
	# show breadcrumbs
	context.no_cache = 1
	context.show_sidebar = True
	context.parents = frappe.form_dict.parents
	# context.parents = [{'name': 'Purchase Receipt', 'title': _('GRNs') }]
	context["title"] = frappe.form_dict.name
def get_list_content(context):
    context.no_cache = 1