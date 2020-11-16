# -*- coding: utf-8 -*-
# Copyright (c) 2020, MTRH and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
# import frappe
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
from frappe.core.doctype.user_permission.user_permission import clear_user_permissions

class StoreAllocation(Document):
	pass
@frappe.whitelist()
def check_duplicate_allocation(doc,state):
	user = doc.user
	name =doc.name
	allocations = frappe.db.get_list('Store Allocation',
					filters={
						'user': user,
						'docstatus':['!=','2'],
						'name':['!=', name]
					}, 
					fields=['count(name) as count']
					)
	number = allocations[0].count
	if number > 0:
		frappe.throw("Sorry, There is an existing entry for this user. Please cancel and/or ammend the existing document")
def insert_user_permissions(doc,state):
	user = doc.user
	#first we remove all existing permissions for warehouse
	clear_user_permissions(user,"Warehouse")
	#next we add permissions
	warehouses = doc.warehouse_allocated
	#data ={}
	for warehouse in warehouses:
		docname = warehouse.warehouse_name
		assigned = warehouse.assigned
		if assigned:
			frappe.permissions.add_user_permission("Warehouse",docname,user)
			#pass


