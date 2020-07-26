# -*- coding: utf-8 -*-
# Copyright (c) 2020, MTRH and contributors
# For license information, please see license.txt


from __future__ import unicode_literals
import frappe
from frappe.model.document import Document
from erpnext.stock.doctype.quality_inspection_template.quality_inspection_template \
	import get_template_details
from frappe.model.mapper import get_mapped_doc

class DocumentExpiryExtension(Document):
	pass
@frappe.whitelist()
def document_names(doctype, txt, searchfield, start, page_len, filters):
	doctype_name = filters.get("from")
	return frappe.db.sql("""SELECT
		name FROM `tab{0}` WHERE docstatus!=2""".format(doctype_name))