# -*- coding: utf-8 -*-
# Copyright (c) 2020, MTRH and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe import _
from frappe.model.document import Document

class ProcurementProfessionalOpinion(Document):
	def send_for_renegotiation(self, items):
		tqo_doc = frappe.get_doc("Tender Quotation Opening", self.get("reference_number"))
		tqo_doc.duplicate_rfq(items, "Renegotiation")
	def refloat_quotation(self, items):
		tqo_doc = frappe.get_doc("Tender Quotation Opening", self.get("reference_number"))
		tqo_doc.duplicate_rfq(items)
	def clear_award_schedule(self):
		self.validate_workflow_state()
		docname = self.get("name")
		frappe.db.sql(f"""DELETE FROM `tabAward Price Schedule Item` WHERE parent ='{docname}';""")
		self.add_comment("Shared", text ="Deleted existing award schedule")
		self.notify_update()
		frappe.msgprint(_('Document updated successfully, please refresh the page to view its updated version'))
		return
	def validate_workflow_state(self):
		if not self.workflow_state == "Draft":
			frappe.throw(_("Sorry, operation only permitted for Draft workflow state"))
