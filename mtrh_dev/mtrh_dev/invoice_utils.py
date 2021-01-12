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
from frappe.utils import flt, nowdate, get_url
from erpnext.accounts.doctype.payment_request.payment_request import get_payment_entry
from erpnext.accounts.doctype.payment_request.payment_request import make_payment_entry
from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry, get_company_defaults
from erpnext.accounts.utils import get_account_currency


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
				#doc.db_set("sent_to_pv", True)
				frappe.msgprint("Payment request {0} has been created successfully. ".format(payment_request_doc.get("name")))
		except Exception as e:
			frappe.msgprint("Operation could not be completed because of {0}"\
				.format(e))
	else:
		docname = frappe.db.get_value("Payment Request",{"reference_name":purchase_order,"checked":False},"name")
		payment_request_doc = frappe.get_doc("Payment Request", docname)
		payment_request_doc = append_invoice_to_request(payment_request_doc, doc)
		payment_request_doc.save(ignore_permissions=True)
	doc.db_set("sent_to_pv", True)
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
def payment_request_submit_operations():
	unprocessed_pvs =frappe.db.sql(f"""SELECT name FROM `tabPayment Request`\
		 WHERE docstatus =1 and processed = 1 and sent_for_payment = 0""", as_dict=True)
	if unprocessed_pvs:
		documents =[frappe.get_doc("Payment Request", x) for x in unprocessed_pvs]
		list(map(lambda  x: make_payment_entry_on_pv_submit(x), documents))
def invoice_submit_operations_cron():
	#sudo -u erp-mtrh /usr/local/bin/bench --site portal.mtrh.go.ke execute mtrh_dev.mtrh_dev.invoice_utils.invoice_submit_operations_cron
	unprocessed_pvs =frappe.db.sql(f"""SELECT name FROM `tabPayment Request`\
		 WHERE docstatus =1 and processed = 0""", as_dict=True)
	if unprocessed_pvs:
		documents =[frappe.get_doc("Payment Request", x) for x in unprocessed_pvs]
		list(map(lambda  x: finalize_invoice_on_pv_submit(x), documents))
def finalize_invoice_on_pv_submit(doc):
	try:
		for invoice in doc.get("invoices"):
			d = invoice.get("invoice_number")
			invoice_to_finalize = frappe.get_doc("Purchase Invoice", d)
			department = invoice_to_finalize.get("items")[0].department
			invoice_to_finalize.db_set("department", department)
			invoice_to_finalize.flags.ignore_permissions = True
			invoice_to_finalize.submit()
			invoice_to_finalize.notify_update()
		doc.db_set("processed",True)
	except Exception as e:
		doc.db_set("processed", False)
		frappe.throw(f"{e}")
	frappe.msgprint(_("Payment invoices have been submitted successfully."))
	return
def update_invoice_state(doc, state):
	if doc.docstatus ==1:
		return
	workflow = get_workflow_name(doc.get('doctype'))
	if workflow:
		new_workflow_state = get_doc_workflow_state(doc)
		old_workflow_state = frappe.db.get_value(doc.get('doctype'), doc.get('name'), 'workflow_state')
		if old_workflow_state == new_workflow_state:
			return
		else:
			#WORKFLOW STATE CHANGED. SO UPDATE INVOICE STATE AS WELL.
			invoice_docs =[frappe.get_doc("Purchase Invoice", x.get("invoice_number")) for x in doc.get("invoices")]
			for d in invoice_docs:
				frappe.db.set_value(d.get("doctype"), d.get("name"),"workflow_state", new_workflow_state)
				d.notify_update()
			#invoice_to_update = frappe.get_doc(doc.get("reference_doctype"), doc.get("reference_name"))
			#invoice_to_update.flags.ignore_permissions = True
			#invoice_to_update.set("workflow_state", new_workflow_state)
			#invoice_to_update.save()
	return
def make_payment_entry_on_pv_submit(doc):
	print(doc.doctype,doc.name)
	pe_exists = frappe.db.get_value("Payment Entry",{"linked_payment_voucher": doc.name},"name")
	print("this", pe_exists)
	try:
		for d in doc.get("invoices"):
			invoice_doc = frappe.get_doc("Purchase Invoice", d.invoice_number)
			if pe_exists:
				print(f"Payment Entry Exists: {pe_exists}")
				pe = pe_exists
				pe = append_invoice_to_pe(pe, d.get("invoice_number"))	
				pe.save()
			else:
				print("Here because no PE exists")
				
				party_account = invoice_doc.credit_to
				party_account_currency = invoice_doc.get("party_account_currency")\
					 or get_account_currency(party_account)
				if party_account_currency == invoice_doc.company_currency\
						and party_account_currency != invoice_doc.currency:
					party_amount = invoice_doc.base_grand_total
				else:
					party_amount = invoice_doc.grand_total
				bank_amount = invoice_doc.grand_total
				print(f"Starting business {bank_amount}")
				pe2 = return_custom_payment_entry(invoice_doc, submit=False, party_amount=party_amount,\
					bank_amount=bank_amount,payment_request_doc = doc)
				print(f"Now proceeding....")
				pe2.linked_payment_voucher = doc.name
				'''pe2 = get_payment_entry(invoice_doc.doctype, invoice_doc.name,\
					party_amount=party_amount, bank_account=invoice_doc.payment_account,\
						 bank_amount=bank_amount)'''
				pe2.flags.ignore_permissions = True
				pe2.run_method("set_missing_values")
				pe2.insert()
				print("Inserted", pe2.name)
				if pe2:
					pe_exists = pe2.name
					print("here because pe2 exists")
		doc.db_set("sent_for_payment",True)
	except Exception as e:
		doc.db_set("sent_for_payment",False)
		frappe.throw(f"{e}")
	return
def append_invoice_to_pe(pe_no, invoice_number):
	pe,pi = frappe.get_doc("Payment Entry", pe_no), frappe.get_doc("Purchase Invoice", invoice_number)
	print("exists, so will work with", pe) 
	grand_total = pi.base_rounded_total or pi.base_grand_total
	grand_total = flt(grand_total)
	new_payment = flt(pe.get("paid_to"))
	new_total = new_payment + grand_total
	#WE NEED TO RECALCULATE THE TOTAL AMOUNT ALLOCATED TO THE PAYMENT
	pe.set("paid_amount" , new_total)
	outstanding_amount = pi.outstanding_amount
	pe.append("references", {
					'reference_doctype': "Purchase Invoice",
					'reference_name': invoice_number,
					"bill_no": pi.get("bill_no"),
					"due_date": pi.get("due_date"),
					'total_amount': grand_total,
					'outstanding_amount': outstanding_amount,
					'allocated_amount': outstanding_amount
				})
	pe.flags.ignore_permissions = True
	pe.setup_party_account_field()
	pe.set_missing_values()
	return pe
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
def return_custom_payment_entry(doc, submit=False, party_amount=0.0,bank_amount=0.0,payment_request_doc=None):#CONTEXT=INVOICE
	payment_entry = get_payment_entry(doc.doctype, doc.name,
			party_amount=party_amount, bank_account=payment_request_doc.payment_account, bank_amount=bank_amount)
	print(f"at the custom method")
	payment_entry.update({
		"reference_no": doc.name,
		"reference_date": nowdate(),
		"remarks": "Payment Entry against {0} {1} via Payment Request {2}".format(doc.doctype,
			doc.name, payment_request_doc.name)
	})

	if payment_entry.difference_amount:
		company_details = get_company_defaults(doc.company)

		payment_entry.append("deductions", {
			"account": company_details.exchange_gain_loss_account,
			"cost_center": company_details.cost_center,
			"amount": payment_entry.difference_amount
		})

	if submit:
		payment_entry.insert(ignore_permissions=True)
		payment_entry.submit()

	return payment_entry
#sudo -u erp-mtrh /usr/local/bin/bench --site portal.mtrh.go.ke execute mtrh_dev.mtrh_dev.invoice_utils.resave_prqs
