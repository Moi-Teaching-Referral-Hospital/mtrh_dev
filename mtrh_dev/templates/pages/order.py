# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

from __future__ import unicode_literals
import frappe

from frappe import _
from frappe.utils import formatdate
from erpnext.shopping_cart.doctype.shopping_cart_settings.shopping_cart_settings import show_attachments

no_cache = 1
def get_context(context):
	context.no_cache = 1
	context.show_sidebar = True
	context.doc = frappe.get_doc(frappe.form_dict.doctype, frappe.form_dict.name)	
	context.doc.purchasereceipt_links = get_purchase_receipt(frappe.form_dict.name)
	if hasattr(context.doc, "set_indicator"):
		context.doc.set_indicator()

	if show_attachments():
		context.attachments = get_attachments(frappe.form_dict.doctype, frappe.form_dict.name)

	context.parents = frappe.form_dict.parents
	context.title = frappe.form_dict.name
	context.payment_ref = frappe.db.get_value("Payment Request",
		{"reference_name": frappe.form_dict.name}, "name")

	context.enabled_checkout = frappe.get_doc("Shopping Cart Settings").enable_checkout

	default_print_format = frappe.db.get_value('Property Setter', dict(property='default_print_format', doc_type=frappe.form_dict.doctype), "value")
	if default_print_format:
		context.print_format = default_print_format
	else:
		context.print_format = "Standard"

	if not frappe.has_website_permission(context.doc):
		frappe.throw(_("Not Permitted"), frappe.PermissionError)
	
	# check for the loyalty program of the customer
	customer_loyalty_program = frappe.db.get_value("Customer", context.doc.customer, "loyalty_program")	
	if customer_loyalty_program:
		from erpnext.accounts.doctype.loyalty_program.loyalty_program import get_loyalty_program_details_with_points
		loyalty_program_details = get_loyalty_program_details_with_points(context.doc.customer, customer_loyalty_program)
		context.available_loyalty_points = int(loyalty_program_details.get("loyalty_points"))

def get_attachments(dt, dn):
        return frappe.get_all("File",
			fields=["name", "file_name", "file_url", "is_private"],
			filters = {"attached_to_name": dn, "attached_to_doctype": dt, "is_private":0})
def get_purchase_receipt(ordernum):
	#purchaseditems = frappe.db.sql("""SELECT * FROM  `tabPurchase Receipt` WHERE `name` IN (select `parent` from `tabPurchase Receipt Item` WHERE `purchase_order` ='""" + ordernum + """');""", {}, as_dict=1)
	purchaseditems = frappe.db.sql("""select * from `tabPurchase Receipt` as a left join `tabDebit Note` as d on a.name=d.purchase_receipt_number where a.name in (select `parent` from `tabPurchase Receipt Item` as c WHERE c.purchase_order='""" + ordernum + """');""", {}, as_dict=1)
	#purchaseditems = frappe.db.sql("""select * from `tabPurchase Receipt` as a left join `tabDebit Note` as d on a.name=d.purchase_receipt_number""", {}, as_dict=1)

	for data in purchaseditems:
		data.creation = formatdate(data.creation)
	return purchaseditems or None