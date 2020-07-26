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

class SMSApi(Document):
	pass
#@frappe.whitelist()
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
			frappe.msgprint("Document submitted! "+str(inspected_items)+" out of "+str(all_purchase_receipt_items)+" items in this delivery have been inspected.")
@frappe.whitelist()
def delivery_completed_status():
	unalerted_grns = frappe.db.get_list('Purchase Receipt',
						filters={
							'percentage_inspected': [">",99.99],
							'docstatus':"0"
						},
						fields=['name'],
						order_by='creation desc',
						as_list=False
					)
	#ALERT DOC OWNER
	for grn in unalerted_grns:
		docname = grn.name
		supplier_ref = grn.get("supplier_delivery")
		frappe.response["grn"]=docname
		#purchase_receipt_document = frappe.db.get_doc("Purchase Receipt",docname)
		purchase_receipt_dict = frappe.db.get_value("Purchase Receipt",docname,['supplier','owner'],as_dict=1)
		recipient = purchase_receipt_dict.owner
		supplier = purchase_receipt_dict.supplier
		message ="Dear {0}\
			 This is to let you know that goods/services as per your delivery note {1}\
				  have been successfully inspected. Please invoice as per attached copy of GRN/Certificate document".format(supplier, supplier_ref)
		#GET ALL INSPECTION DOCUMENTS
		inspection_documents  = frappe.db.get_list('Quality Inspection',
						filters={
							'reference_name': docname,
						},
						fields=['name','item_name'],
						order_by='creation desc',
						as_list=False
					)
		#CREATE AN ATTACHMENTS ARRAY
		attachments =[]
		#GRN DOCUMENT ATTACHMENT
		grn_attachment = frappe.attach_print("Purchase Receipt", docname, file_name=docname)
		attachments.append(grn_attachment)
		#INSPECTION ATTACHMENT
		for item in inspection_documents:
			inspection = frappe.attach_print("Quality Inspection", item.name, file_name=item.item_name)
			attachments.append(inspection)
		email_args = {
					"recipients": recipient,
					"message": _(message),
					"subject": "Invoice Us - ["+docname+"]",
					"attachments": attachments,
					"reference_doctype": "Purchase Receipt",
					"reference_name": docname,
					}
		#email_args.update(template_args)
		frappe.response["response"] = email_args
		enqueue(method=frappe.sendmail, queue='short', timeout=300, **email_args)
		frappe.db.set_value("Purchase Receipt", docname, "docstatus", "1")
		frappe.db.set_value("Purchase Receipt", docname, "workflow_state", "To Bill")



			