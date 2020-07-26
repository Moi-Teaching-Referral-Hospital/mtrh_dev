# -*- coding: utf-8 -*-
# Copyright (c) 2020, MTRH and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe.model.document import Document

class TenderQuotationEvaluation(Document):
	pass
@frappe.whitelist()
def unevaluated_items_query(rfq):
	#rfq_items = frappe.db.sql("""SELECT item_code FROM `tabRequest for Quotation Item` WHERE parent =%s""",(rfq),as_dict=1)
	rfq_items = frappe.db.get_list('Request for Quotation Item',
														filters={
															'parent': rfq
														},
														fields=['item_code'],
														order_by='creation desc',
														as_list=False
													)
	rfq_items_arr =[]
	for item in rfq_items:
		rfq_items_arr.append(item.item_code)
	frappe.response["message"]=rfq_items_arr