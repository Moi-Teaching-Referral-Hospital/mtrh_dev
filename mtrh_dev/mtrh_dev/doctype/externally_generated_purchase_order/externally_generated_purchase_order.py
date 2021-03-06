# -*- coding: utf-8 -*-
# Copyright (c) 2020, MTRH and contributors
# For license information, please see license.txt
from __future__ import unicode_literals
import frappe
from frappe.model.document import Document

class ExternallyGeneratedPurchaseOrder(Document):
	def validate_amount(self):
		computed = 0.0 
		amount =0.0
		for d in self.get("items"):
			amount = d.qty*d.rate
			d.amount = amount
			computed += amount
		self.total_order_value = computed 
		if int(self.get("total_scanned_order_value")) != int(self.get("total_order_value")) or self.get("total_scanned_order_value")<1:	
			scanned_value =self.get("total_scanned_order_value") 		
			massage_to_display = f"<p>Total Value(Scanned Order): {scanned_value}. Computed {computed} </p>"
			frappe.throw(f"This document does not tally with\
				 the scanned document value {massage_to_display}")
		else:
			attachment = self.get("external_po_and_relevant_documentation")
	def before_submit(self):
		self.validate_amount()
		self.migrate_links()
	def migrate_links(self):
		pass
