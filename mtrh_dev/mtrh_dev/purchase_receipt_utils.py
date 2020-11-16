# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

# ERPNext - web based ERP (http://erpnext.com)
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe, json
import http.client
import mimetypes
from frappe import _
from frappe.model.mapper import get_mapped_doc
from frappe.utils import get_url, cint
from frappe.utils.background_jobs import enqueue
from frappe import msgprint
from frappe.model.document import Document
import datetime
from frappe.utils import cint, flt, cstr, now
from datetime import date, datetime
from mtrh_dev.mtrh_dev.utilities import get_doc_workflow_state, forcefully_update_doc_field
from frappe.model.workflow import get_workflow_name, get_workflow_state_field
from frappe.utils import nowdate, getdate, add_days, add_years, cstr, get_url, get_datetime

class SMSApi(Document):
	pass
#@frappe.whitelist()
def complete_closed_mr():
	sql_query ="""select distinct name from `tabPurchase Order` where status='Closed' and completed ='0';"""

	recently_closed_pos = frappe.db.sql(sql_query,as_dict=True)
	
	po_docs = [frappe.get_doc("Purchase Order", x.get("name")) for x in recently_closed_pos]
	
	uncompleted_goods =[]

	for po in po_docs:
		po_name = po.get("name")
		sql_query =f"""UPDATE `tabPurchase Order` SET status = 'To Bill'\
			 where name ='{po_name}' ;"""
		frappe.db.sql(sql_query)
		items = po.get("items")
		#RETURN A DICT OF ITEMS AND THEIR UNDELIVERED QTY FROM PURCHASE RECEIPT
		uncompleted_goods = [x for x in items if (x.get("qty")-x.get("received_qty"))>0.0] 
		#FILTERS OUT FULLY SUPPLIED ITEMS
		if len(uncompleted_goods)>0:
			raise_debit_note(po,uncompleted_goods)
		else:
			close_purchase_order(po)
	return uncompleted_goods 
def raise_debit_note(po, uncompleted_goods):
	debit_note_doc = make_debit_note(po, uncompleted_goods)
	debit_note_doc.flags.ignore_permissions = True
	debit_note_doc.run_method("set_missing_values")
	debit_note_doc.insert()
	close_purchase_order(po)
def close_purchase_order(po):
	po_name = po.get("name")
	sql_query =f"""UPDATE `tabPurchase Order` SET status = 'Closed', completed='1'\
			 where name ='{po_name}' ;"""
	frappe.db.sql(sql_query)	
def make_debit_note(po, uncompleted_goods):
	sq_doc = frappe.get_doc({
			"doctype": "Purchase Invoice",
			"supplier": po.get("supplier"),
			"company": frappe.db.get_single_value("Global Defaults", "default_company"),
			"due_date": add_days(nowdate(), 30),
			"posting_date": date.today(),
			"posting_time": datetime.now().strftime("%H:%M:%S"),	
			"is_return": True	
		})
	
	for item in uncompleted_goods:
		to_debit = item.get("qty") - item.get("received_qty")
		sq_doc.append('items', {
			"item_code": item.get('item_code'),
			"item_name": item.get('item_name'),
			"rate": item.get('rate'),
			"purchase_order": po.get("name"),
			"po_detail": item.get("name"),
			"qty": to_debit*-1,
			"stock_uom": item.get('stock_uom'),
			"uom": item.get('uom'),
		})
	
	return sq_doc
def update_percentage_inspected(doc, state):
	if doc.get("reference_name") and doc.get("reference_type"):
		if doc.get("reference_type") == "Purchase Receipt":
			purchase_receipt = doc.get("reference_name")

			#COUNT INSPECTED ITEMS
			inspected_items = frappe.db.count('Purchase Receipt Item', {'parent': purchase_receipt,'quality_inspection':['!=',""]})
			#COUNT ALL ITEMS
			all_purchase_receipt_items = frappe.db.count('Purchase Receipt Item', {'parent': purchase_receipt})
			percentage = float(inspected_items)*100/float(all_purchase_receipt_items)
			frappe.db.set_value("Purchase Receipt", purchase_receipt, "percentage_inspected", percentage)
			docname=frappe.db.get_value("Purchase Receipt Item",{"item_code":doc.item_code,"parent":purchase_receipt},"name")
			frappe.db.set_value("Purchase Receipt Item", docname, "qty", doc.sample_size)
#			frappe.msgprint("Document submitted! "+str(inspected_items)+" out of "+str(all_purchase_receipt_items)+" items in this delivery have been inspected.")
			#if percentage and percentage > 99.99:
			#	delivery_completed_status(doc , state)
@frappe.whitelist()		
def delivery_completed_status_shorthand(docname):	
	doc = frappe.get_doc("Quality Inspection", docname)
	frappe.response["id"]=docname
	delivery_completed_status(doc,"Submitted")
def delivery_completed_status_cron():
	print("Starting cron")
	unalerted_grns = frappe.db.get_all('Purchase Receipt',
						filters={
							'percentage_inspected': [">",99.99],
							'docstatus': '0'
						},
						fields=['name'],
						as_list=False
					)
	process_qi(unalerted_grns)
	return
@frappe.whitelist()
def delivery_completed_status(doc , state):
	unalerted_grns = frappe.db.get_all('Purchase Receipt',
						filters={
							'percentage_inspected': [">",99.99],
							'docstatus': '0',
							'name': doc.get("reference_name")
						},
						fields=['name'],
						as_list=False
					)
	process_qi(unalerted_grns)
	return unalerted_grns
def update_posting_date_and_time(doc):
	#CONTEXT PURCHASE RECEIPT
	doc.flags.ignore_permissions = True
	doc.set("posting_date",date.today())
	doc.set("posting_time",datetime.now().strftime("%H:%M:%S"))
	doc.save()
	return doc
def process_qi(unalerted_grns):
	#unalerted_grns = [doc.get("reference_name")]
	#ALERT DOC OWNER
	if not unalerted_grns:
		return#frappe.throw("Sorry, you must inspect all Delivered items")
	for grn in unalerted_grns:
		docname = grn.name
		grn = update_posting_date_and_time(grn)
		supplier_ref = grn.get("supplier_delivery")
		frappe.response["grn"]=docname
		#purchase_receipt_document = frappe.db.get_doc("Purchase Receipt",docname)
		purchase_receipt_dict = frappe.db.get_value("Purchase Receipt",docname,['supplier','owner'],as_dict=1)
		supplier = purchase_receipt_dict.supplier
		thesupplier = supplier
		contact = frappe.db.get_value("Dynamic Link", {"link_doctype":"Supplier", "link_title":thesupplier, "parenttype":"Contact"} ,"parent")
		email = frappe.db.get_value("Contact", contact, "email_id")
		recipient = email #purchase_receipt_dict.owner
		#supplier = purchase_receipt_dict.supplier
		message ="Dear {0}\
			 This is to let you know that goods/services as per your delivery note {1}\
				  have been successfully inspected. Please invoice as per attached copy of GRN/Certificate document. If you have already submitted an invoice, no further action is needed at this point.".format(supplier, supplier_ref)
		#GET ALL INSPECTION DOCUMENTS
		inspection_documents  = frappe.db.get_all('Quality Inspection',
						filters={
							'reference_name': docname,
						},
						fields=['name','item_name'],
						order_by='creation desc',
						as_list=False
					)
		#CREATE AN ATTACHMENTS ARRAY
		attachments = []
		#GRN DOCUMENT ATTACHMENT
		grn_attachment = frappe.attach_print("Purchase Receipt", docname, file_name=docname)
		attachments.append(grn_attachment)
		#INSPECTION ATTACHMENT
		for item in inspection_documents:
			inspection = frappe.attach_print("Quality Inspection", item.name, file_name=item.item_name)
			attachments.append(inspection)
		
		pr_doc = frappe.get_doc("Purchase Receipt", docname)
		pr_doc.flags.ignore_permissions = True
		pr_doc.run_method("set_missing_values")
		#pr_doc.save()
		pr_doc.submit()

		email_args = {
					"recipients": recipient,
					"message": _(message),
					"subject": "Invoice Us - ["+docname+"]",
					"attachments": attachments,
					"reference_doctype": "Purchase Receipt",
					"reference_name": docname,
					}
		#email_args.update(template_args)
		#frappe.response["response"] = pr_doc
		enqueue(method=frappe.sendmail, queue='short', timeout=300, **email_args)
		
		

		#frappe.db.set_value("Purchase Receipt", docname, "docstatus", "1")
		#frappe.db.set_value("Purchase Receipt", docname, "workflow_state", "To Bill")

		from erpnext.stock.doctype.purchase_receipt.purchase_receipt import make_purchase_invoice
		purchase_invoice = make_purchase_invoice(docname)
		purchase_invoice.flags.ignore_permissions = True
		purchase_invoice.run_method("set_missing_values")
		inc_doc = purchase_invoice.insert() #frappe.db.insert(purchase_invoice)
		frappe.msgprint("A supplier Invoice has been posted to Finance as Invoice: " + inc_doc.name + " for evaluation and approval.")
	return
def recall_purchase_receipt(doc , state):
	workflow = get_workflow_name(doc.get('doctype'))
	if not workflow: 
		return
	else:
		this_doc_workflow_state = get_doc_workflow_state(doc)
		if	this_doc_workflow_state =="Reversed":
			quality_inspections = frappe.db.get_all('Quality Inspection',
								filters={		
									'reference_name': doc.get("name")
								},
								fields=['name'],
								as_list=False
							)

			q_documents =[frappe.get_doc("Quality Inspection", x.get("name"))\
				for x in quality_inspections if quality_inspections]

			submitted_qis  =[x for x in q_documents if x.get("docstatus")==1]
			if len(submitted_qis) > 0:
				frappe.throw("It seems that some inspection documents are already submitted.\
					To recall specific items please recall them from Quality Inspection doctype")
				return
			else:
				list(map(lambda x: x.delete(ignore_permissions=True), q_documents))
				doc.db_set('workflow_state', "Draft", notify=True, commit=True, update_modified=True)
	return
def recall_quality_inspection_item(doc , state):
	workflow = get_workflow_name(doc.get('doctype'))
	if not workflow: 
		return
	else:
		this_doc_workflow_state = get_doc_workflow_state(doc)
		if	this_doc_workflow_state =="Reversed":
			pr_name = doc.get("reference_name")
			item_code = doc.get("item_code")
			purchase_receipt = frappe.get_doc("Purchase Receipt", pr_name)
			if purchase_receipt:
				item_row_id = frappe.db.sql(f"""SELECT name FROM `tabPurchase Receipt Item`\
					WHERE parent ='{pr_name}' AND item_code ='{item_code}' """)[0][0]
				row_doc = frappe.get_doc("Purchase Receipt Item", item_row_id)
				row_doc.flags.ignore_permissions = True
				row_doc.delete()
				purchase_receipt.flags.ignore_permissions = True
				purchase_receipt.run_method("set_missing_values")
				purchase_receipt.save()
				purchase_receipt.notify_update()
				doc.flags.ignore_permissions = True
				doc.delete() #DELETE THIS INSPECTION DOCUMENT
				#frappe.set_route("List", "Quality Inspection",{"reference_name": pr_name})
		elif this_doc_workflow_state =="Cancelled":
			pass


			