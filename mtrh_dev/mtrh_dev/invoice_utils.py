# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

# ERPNext - web based ERP (http://erpnext.com)
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe, json
from frappe import _
from frappe.model.mapper import get_mapped_doc
from frappe.utils import get_url, cint
from frappe.utils.background_jobs import enqueue
from frappe import msgprint
from frappe.model.document import Document
import datetime
from frappe.utils import cint, flt, cstr, now
from datetime import date, datetime
from erpnext.stock.utils import get_stock_balance
from erpnext.stock.doctype.item.item import get_item_defaults, get_uom_conv_factor
from erpnext.setup.doctype.item_group.item_group import get_item_group_defaults
from erpnext.assets.doctype.asset_category.asset_category import get_asset_category_account
from erpnext.setup.doctype.brand.brand import get_brand_defaults
from mtrh_dev.mtrh_dev.utilities import get_doc_workflow_state
from frappe.model.workflow import get_workflow_name


class InvoiceUtils(Document):
	pass
def raise_payment_request(doc, state):
	try:
		args ={}
		args["dt"] = "Purchase Invoice"
		args["dn"] = doc.get("name")
		args["loyalty_points"] = ""
		args["party_type"] = "Supplier"
		args["party"]=doc.get("supplier")
		args["payment_request_type"]="Outward"
		args["transaction_date"]=date.today
		args["return_doc"]=True
		args["submit_doc"]=False
		args["order_type"]="Purchase Invoice"
		if args:
			from erpnext.accounts.doctype.payment_request.payment_request import make_payment_request
			payment_request_doc = make_payment_request(**args)
			payment_request_doc.insert(ignore_permissions=True)
			frappe.msgprint("Payment request {0} has been created successfully. ".format(payment_request_doc.get("name")))
	except Exception as e:
		frappe.msgprint("Operation could not be completed because of {0}"\
			.format(e))
	return
def validate_invoices_in_po(doc , state):
	workflow = get_workflow_name(doc.get('doctype'))
	if workflow:
		new_workflow_state = get_doc_workflow_state(doc)
		old_workflow_state = frappe.db.get_value(doc.get('doctype'), doc.get('name'), 'workflow_state')
		if old_workflow_state == new_workflow_state:
			return
		elif new_workflow_state in ["Pending Payment Voucher", "Credit Note"]:
			
			purchase_receipt = doc.get("items")[0].purchase_receipt
			
			purchase_order = doc.get("items")[0].purchase_order 

			if not purchase_receipt or not purchase_order:
				frappe.throw("Sorry. This invoice was not validly received with a system generated PO or GRN")
			else:
				total_po_amount = frappe.db.get_value("Purchase Order", purchase_order, 'total') or 0.0

				invoices_list = frappe.db.get_all('Purchase Invoice Item', filters={
													'purchase_order': purchase_order
													},
													fields=['parent'],
													group_by='parent',
													as_list = False)
				invoices_arr = [invoice.parent for invoice in invoices_list]

				#frappe.throw("Purchase Order: {0}".format(invoices_arr))

				total_accepted_amount = frappe.db.get_list('Purchase Invoice', filters={
													'name': ["IN",invoices_arr],
													'is_return': False
													},
													#fields="`tabPurchase Invoice`.name, sum(`tabPurchase Invoice`.total) as total") or [0.0]
													fields="sum(`tabPurchase Invoice`.total) as total") or [{"total":0.0}]
				total_returns = frappe.db.get_list('Purchase Invoice', filters={
													'name': ['IN',invoices_arr],
													'is_return': True
													},
													#fields='`tabPurchase Invoice`.name, sum(`tabPurchase Invoice`.total)*-1 as total') or [0.0]
													fields='sum(`tabPurchase Invoice`.total)*-1 as total') or [{"total":0.0}]
				po = total_po_amount or 0.0 
				ta = total_accepted_amount[0].total or 0.0
				tr = total_returns[0].total or 0.0

				#frappe.throw("Purchase Order: {0} Accepted Amount: {1} Returns: {2} for {3}".\
				#	format(total_po_amount,total_accepted_amount[0].total, total_returns, invoices_arr))
				
				if(po == (ta + tr)):
					documents = [frappe.get_doc("Purchase Invoice", x) for x in invoices_arr]
					documents_to_be_paid = [x for x in documents if x.get("is_return")==False]
					list(map(lambda x: raise_payment_request(x, "Submitted"),documents_to_be_paid))
					  #Raise all documents
					#CLOSE the PO
					from mtrh_dev.mtrh_dev.purchase_receipt_utils import close_purchase_order
					po_doc = frappe.get_doc("Purchase Order", purchase_order)
					close_purchase_order(po_doc)
	return				
def finalize_invoice_on_pv_submit(doc, state):
	frappe.db.set_value(doc.get("reference_doctype"), doc.get("reference_name"),"workflow_state", "Pending Payment Voucher")
	invoice_to_finalize = frappe.get_doc(doc.get("reference_doctype"), doc.get("reference_name"))
	invoice_to_finalize.flags.ignore_permissions = True
	invoice_to_finalize.submit()
	invoice_to_finalize.notify_update()
	frappe.msgprint(_("The payment voucher has been submitted successfully."))
	return
def update_invoice_state(doc, state):
	workflow = get_workflow_name(doc.get('doctype'))
	if workflow:
		new_workflow_state = get_doc_workflow_state(doc)
		old_workflow_state = frappe.db.get_value(doc.get('doctype'), doc.get('name'), 'workflow_state')
		if old_workflow_state == new_workflow_state:
			return
		else:
			#WORKFLOW STATE CHANGED. SO UPDATE INVOICE STATE AS WELL.
			frappe.db.set_value(doc.get("reference_doctype"), doc.get("reference_name"),"workflow_state", new_workflow_state)
			frappe.get_doc(doc.get("reference_doctype"), doc.get("reference_name")).notify_update()
			#invoice_to_update = frappe.get_doc(doc.get("reference_doctype"), doc.get("reference_name"))
			#invoice_to_update.flags.ignore_permissions = True
			#invoice_to_update.set("workflow_state", new_workflow_state)
			#invoice_to_update.save()
	return
def make_payment_entry_on_pv_submit(doc,state):
	from erpnext.accounts.doctype.payment_request.payment_request import make_payment_entry
	payment_entry_doc = make_payment_entry(doc.get("name"))
	payment_entry_doc.flags.ignore_permissions = True
	payment_entry_doc.insert()
	return 
	