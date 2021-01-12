# -*- coding: utf-8 -*-
# Copyright (c) 2020, MTRH and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe.model.document import Document
import datetime

class TenderNumber(Document):
	def before_save(self):
		valid_extension = self.validate_extension()
		#if valid_extension:
		self.extend_awards(valid_extension)
	def validate_extension(self):
		valid = True
		today = frappe.utils.nowdate()
		today = datetime.datetime.strptime(today, '%Y-%m-%d')
		exp = self.expiry_date
		exp = datetime.datetime.strptime(str(exp), '%Y-%m-%d')
		if today >= exp:
			frappe.msgprint("You have selected a date earlier than today. No changes will be made on the award documents")
			valid = False
		return valid
	def extend_awards(self, valid):
		reference_number = self.name

		d = frappe.db.sql(f"SELECT name FROM `tabTender Quotation Award`\
			 WHERE reference_number ='{reference_number}' and workflow_state = 'Expired'", as_dict=True)
		if isinstance(d, list) and d:
			refs = [x.get("name") for x in d]
			awards = [frappe.get_doc("Tender Quotation Award", x) for x in refs]
			for x in awards:
				if valid:
					x.db_set("workflow_state","Approved")
					x.re_evaluate_document()
				else:
					x.mark_award_as_expired()
					x.remove_linked_award()
		return