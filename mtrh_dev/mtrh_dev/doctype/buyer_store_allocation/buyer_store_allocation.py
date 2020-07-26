# -*- coding: utf-8 -*-
# Copyright (c) 2020, MTRH and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe import msgprint
from frappe.model.document import Document

class BuyerStoreAllocation(Document):
	pass
@frappe.whitelist()
def alertfunction():
	msgprint("I have run again") 

@frappe.whitelist()
def supplier_map(item_group):
	frappe.db.sql("""DELETE FROM `tabItem Supplier` WHERE parent IN (SELECT item_code FROM tabItem WHERE item_group =%s);""",(item_group)) 
	frappe.db.sql("""INSERT INTO `tabItem Supplier`(name,supplier, parent, supplier_part_no) 
	SELECT uuid_short(), ps.supplier_name,ti.item_code,''
	FROM `tabPrequalification Supplier` ps, tabItem ti 
	WHERE ps.parent =%s and ps.parent = ti.item_group AND ps.supplier_name NOT IN 
	(SELECT supplier FROM `tabItem Supplier` WHERE (supplier !='' OR supplier IS NOT NULL) 
	AND parent IN (SELECT item_code FROM tabItem WHERE item_group=%s));""",
	(item_group, item_group))
	
	
	msgprint("Supplier records have been updated succesfully");		



