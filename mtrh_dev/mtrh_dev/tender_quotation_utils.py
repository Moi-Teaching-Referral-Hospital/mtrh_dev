# -*- coding: utf-8 -*-
# Copyright (c) 2020, MTRH and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe import _
from frappe import msgprint
from frappe.utils.user import get_user_fullname
from frappe.model.document import Document
import datetime
from datetime import date
from frappe.core.doctype.communication.email import make
from mtrh_dev.mtrh_dev.workflow_custom_action import send_tqe_action_email
STANDARD_USERS = ("Guest", "Administrator")


class TenderQuotationUtils(Document):
	pass
#https://discuss.erpnext.com/t/popup-message-using-frappe-publish-realtime/37286/2
def create_tq_opening_doc(doc, state):
	rfq = doc.get("request_for_quotation") or doc.get("items")[0].request_for_quotation
	count_quotations = frappe.db.count('Tender Quotation Evaluation', {'supplier_quotation': doc.get("name")})
	if count_quotations and count_quotations > 0:
		frappe.throw("Sorry, this supplier quotation has been already sent out")
	else:
		sq_doc = frappe.get_doc({
				"doctype": "Tender Quotation Evaluation",
				"rfq_no": rfq,
				"supplier_quotation": doc.get("name"),
			})
		sq_doc.flags.ignore_permissions = True
		sq_doc.run_method("set_missing_values")
		sq_doc.save()
def perform_sq_submit_operations(doc , state):
	rfq_in_question = doc.get("request_for_quotation") or doc.get("items")[0].request_for_quotation

	method =  frappe.db.get_value('Request for Quotation', rfq_in_question, 'mode_of_procurement')
	item_category = frappe.db.get_value('Item', doc.get("items")[0].item_code, 'item_group')
	winning_quote = doc.get("winning_quote")
	if method and rfq_in_question:
		material_request_number =  frappe.db.get_value('Request for Quotation Item', {'parent': rfq_in_question}, 'material_request')
		item_dict = frappe.db.get_value('Material Request Item', {"parent":material_request_number,"item_code":doc.get("items")[0].item_code}, ["item_code", "rate", "item_name",  "description",  "item_group","brand","qty","uom", "conversion_factor", "stock_uom", "warehouse", "schedule_date", "expense_account","department"], as_dict=1)
		if  "Tender" not in method:
			#RAISE AN ORDER FOR NON - TENDER MODE OF PROCUREMENT
			if winning_quote == True:
				actual_name = doc.get("supplier")
				try:
					sq_doc = frappe.get_doc({
						"supplier_name":actual_name,
						"conversion_rate":1,
						"currency":frappe.defaults.get_user_default("currency"),
						"supplier": actual_name,
						"supplier_test":actual_name,
						"company": frappe.defaults.get_user_default("company"),
						"naming_series": "PUR-ORD-.YYYY.-",
						"transaction_date" : date.today(),
						"item_category":item_category,
						"schedule_date" : add_days(nowdate(), 30),
						
					})		
					sq_doc.append('items', {
						"item_code": item_dict.item_code,
						"item_name": item_dict.item_name,
						"description": item_dict.description,
						"qty": item_dict.qty,
						"rate": item_dict.rate,
						#"supplier_part_no": frappe.db.get_value("Item Supplier", {'parent': item_dict.item_code, 'supplier': supplier}, "supplier_part_no"),
						"warehouse": item_dict.warehouse or '',
						#"material_request": material_request_number,
						#"department": item_dict.department
					})		
					#material_requests
					frappe.response["to_save"]=sq_doc	
					sq_doc.flags.ignore_permissions = True
					sq_doc.run_method("set_missing_values")
					sq_doc.save()
					frappe.db.set_value("Material Request Item", item_dict.name, "attended_to", "1")
					frappe.msgprint(_("Draft Quotation {0} created").format(sq_doc.name))
					
					#return sq_doc.name
				except Exception as e:

 