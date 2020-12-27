# -*- coding: utf-8 -*-
# Copyright (c) 2020, MTRH and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe.model.document import Document

class BuyerSectionAllocation(Document):
	def before_save(self):
		user = frappe.get_value("Employee",self.purchasing_officer,"user_id")
		sections = [x.get("item_group") for x in self.get("sections_allocated")]
		for d in sections:
			if not frappe.db.exists({'doctype': 'User Permission', 'user': user, 'allow': 'Item Group', 'for_value': d, 'applicable_for': 'Purchase Order'}): 
				frappe.get_doc(dict(
					doctype='User Permission',
					user= user,
					allow="Item Group",
					for_value= d,
					apply_to_all_doctypes=0,
					applicable_for="Purchase Order"
				)).insert(ignore_permissions=True)