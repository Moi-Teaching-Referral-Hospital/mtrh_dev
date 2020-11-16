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
	purchase_order = doc.get("items")[0].purchase_order
	if not frappe.db.exists({"doctype":"Payment Request","reference_name":purchase_order,"checked":False}):
		#dn = doc.get("name")
		'''if frappe.db.count('Payment Request', {'reference_name': dn}) > 0:
			return
		else:'''
		try:
			args ={}
			args["dt"] = "Purchase Order"
			args["dn"] = purchase_order
			args["loyalty_points"] = ""
			args["party_type"] = "Supplier"
			args["party"]=doc.get("supplier")
			args["payment_request_type"]="Outward"
			args["transaction_date"]=date.today
			args["return_doc"]=True
			args["submit_doc"]=False
			args["order_type"]="Purchase Order"
			if args:
				from erpnext.accounts.doctype.payment_request.payment_request import make_payment_request
				payment_request_doc = make_payment_request(**args)
				#########################################################
				
				#SET PURCHASE ORDER AMOUNT
				po = frappe.get_doc(payment_request_doc.get("reference_doctype"), payment_request_doc.get("reference_name"))
				total_po_amount = po.get("total") or 0.0 
				payment_request_doc.set("order_amount", total_po_amount)
				#APPEND INVOICES/CREDIT NOTES IN TABLE
				payment_request_doc = append_invoice_to_request(payment_request_doc, doc)
				
				########################################################
				#INSERT DOCUMENT
				payment_request_doc.insert(ignore_permissions=True)
				doc.db_set("sent_to_pv", True)
				frappe.msgprint("Payment request {0} has been created successfully. ".format(payment_request_doc.get("name")))
		except Exception as e:
			frappe.msgprint("Operation could not be completed because of {0}"\
				.format(e))
	else:
		docname = frappe.db.get_value("Payment Request",{"reference_name":purchase_order,"checked":False},"name")
		payment_request_doc = frappe.get_doc("Payment Request", docname)
		payment_request_doc = append_invoice_to_request(payment_request_doc, doc)
		payment_request_doc.save(ignore_permissions=True)
	return
def append_invoice_to_request(payment_request, purchase_invoice):
	invoice = purchase_invoice.get("name")
	amount = purchase_invoice.get("total")
	if not purchase_invoice.get("is_return"):
		invoices_already_entered =[x.get("invoice_number") for x in payment_request.get("invoices")]
		if invoice not in invoices_already_entered:
			payment_request.append('invoices',{
				"invoice_number": invoice,
				"amount": amount
			})
	else:
		invoices_already_entered =[x.get("invoice_number") for x in payment_request.get("credit_notes")]
		if invoice not in invoices_already_entered:
			payment_request.append('credit_notes',{
				"invoice_number": invoice,
				"amount": amount
			})
	return payment_request
def validate_invoices_in_po_v2(doc,state):
	workflow = get_workflow_name(doc.get('doctype'))
	if workflow:
		new_workflow_state = get_doc_workflow_state(doc)
		old_workflow_state = frappe.db.get_value(doc.get('doctype'), doc.get('name'), 'workflow_state')
		if old_workflow_state == new_workflow_state:
			return
		elif new_workflow_state in ["Pending Payment Voucher", "Credit Note"]:
			doc.set("to_be_sent_to_pv", True)
			frappe.msgprint("Document checking successful")
	return
def set_purchase_request_as_checked(doc):
	workflow = get_workflow_name(doc.get('doctype'))
	if workflow:
		new_workflow_state = get_doc_workflow_state(doc)
		old_workflow_state = frappe.db.get_value(doc.get('doctype'), doc.get('name'), 'workflow_state')
		doc.set("checked", False)
		if old_workflow_state == new_workflow_state:
			return
		elif new_workflow_state not in ["Voteholder Checking"]:
			doc.set("checked", True)
			frappe.msgprint("Document checking successful")
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

				'''invoices_list = frappe.db.get_all('Purchase Invoice Item', filters={
													'purchase_order': purchase_order

													},
													fields=['parent'],
													group_by='parent',
													as_list = False)'''									
				sql_to_run = f"""SELECT DISTINCT parent FROM `tabPurchase Invoice Item`\
					WHERE purchase_order = '{purchase_order}'\
						 AND parent IN (SELECT name FROM `tabPurchase Invoice`\
							 WHERE workflow_state in ('Pending Payment Voucher', 'Credit Note'))"""
				invoices_list = frappe.db.sql(sql_to_run, as_dict=True)
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
				this_invoice_total = doc.get("total") if doc.get("total")>0 else doc.get("total")*-1
				if(po == (ta + tr+this_invoice_total)):
					invoices_arr.append(doc.get("name"))
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
def process_staged_invoices():
	invoices_dict = frappe.db.sql("SELECT name FROM `tabPurchase Invoice`\
			 WHERE to_be_sent_to_pv = 1 and sent_to_pv=0",as_dict=True)
	invoices =[x.get("name") for x in invoices_dict]
	print(invoices)
	if invoices:
		documents = [frappe.get_doc("Purchase Invoice",x) for x in invoices]
		documents_to_be_paid = [x for x in documents if x.get("is_return")==False]
		list(map(lambda x: raise_payment_request(x, "Submitted"),documents_to_be_paid))
def clean_up_payment_request(doc, state):
	#SET PURCHASE ORDER AMOUNT
	payment_request_doc = doc
	po = frappe.get_doc(payment_request_doc.get("reference_doctype"), payment_request_doc.get("reference_name"))
	total_po_amount = po.get("total") or 0.0 
	payment_request_doc.set("order_amount", total_po_amount)
	#GET AND SET INVOICES AMOUNT
	total_pv_amount = 0.0
	for d in payment_request_doc.get("invoices"):
		total_pv_amount += d.get("amount")
	payment_request_doc.set("grand_total", flt(total_pv_amount))
	#GET AND SET CREDIT NOTES AMOUNT
	total_cr_amount = 0.0
	if payment_request_doc.get("credit_notes"):
		for d in payment_request_doc.get("credit_notes"):
			total_cr_amount += d.get("amount")
	if total_cr_amount < 0:
		total_cr_amount*=-1
	total_processed_invoices_plus_credit_notes = total_pv_amount + total_cr_amount
	percent = total_processed_invoices_plus_credit_notes*100 / total_po_amount
	payment_request_doc.set("forwarded_invoices",percent) 
	set_purchase_request_as_checked(doc)
def resave_prqs():
	d = frappe.db.sql("SELECT name FROM `tabPayment Request`", as_dict=True)
	documents = [frappe.get_doc("Payment Request", x.get("name")) for x in d]
	if documents:
		list(map(lambda x: x.save(),documents))
#sudo -u erp-mtrh /usr/local/bin/bench --site portal.mtrh.go.ke execute mtrh_dev.mtrh_dev.invoice_utils.resave_prqs