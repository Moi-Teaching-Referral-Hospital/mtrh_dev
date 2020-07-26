# -*- coding: utf-8 -*-
# Copyright (c) 2020, MTRH and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
# import frappe
import frappe, json
from frappe import _
from frappe import msgprint
from frappe.utils.user import get_user_fullname
from frappe.model.document import Document
import datetime
from datetime import date
from frappe.core.doctype.communication.email import make
from mtrh_dev.mtrh_dev.workflow_custom_action import send_tqe_action_email
STANDARD_USERS = ("Guest", "Administrator")

class TenderQuotationAward(Document):
	pass
#++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
# THIS CODE MANUALLY UPDATES THE PRICELIST AND DEFAULT SUPPLIER OF AN ITEM ONLY WHEN AUTHORITY IS SOUGHT
def update_price_list(doc, state):
	item_code = doc.get("item_code")
	reference =doc.get("reference_number") or "Standard Buying"
	bidders = doc.get("suppliers")
	bidder_payload ={}
	for bidder in bidders:
		if(bidder.get("awarded_bidder")):
			bidder_payload = bidder
	suppname  = bidder_payload.get("supplier_name")
	price_per_unit = bidder_payload.get("unit_price")
	user = frappe.session.user
	item_name = frappe.db.get_value("Item",item_code,"item_name")
	pricelist_exists = frappe.db.exists({
		'doctype': 'Price List',
		'name': reference,
	})
	pricelist_price_exists  = frappe.db.exists({
		'doctype': 'Item Price',
		'price_list': reference,
		'item_code':item_code,
	})
	company = frappe.db.get_single_value("Global Defaults", "default_company")
	item_default_exists = frappe.db.exists({
		'doctype': 'Item Default',
		'parent':item_code,
	})
	#frappe.throw("Starting processing of payload for {0}...".format(item_code))
	if not item_default_exists:
		frappe.msgprint("Creating a defaults entry...")
		frappe.db.sql("""INSERT INTO  `tabItem Default` (name,creation,modified,modified_by,owner,docstatus,parent,company, parenttype, parentfield) values(uuid_short(),now(),now(),%s,%s,'0',%s,%s,"Item","item_defaults")""",(user,user,item_code,company))
	supplierdefault = frappe.db.sql("""UPDATE `tabItem Default` set default_supplier=%s where parent=%s""",(suppname,item_code))
	if not pricelist_exists:
		pricelist = frappe.db.sql("""INSERT INTO  `tabPrice List` (name,creation,modified,modified_by,owner,docstatus,currency,price_list_name,enabled,buying) values(%s,now(),now(),%s,%s,'0','KES',%s,1,1)""",(reference,user,user,reference))
	if not pricelist_price_exists:
		itempriceinsert=frappe.db.sql("""INSERT INTO  `tabItem Price` (name,creation,modified,modified_by,owner,docstatus,currency,item_description,lead_time_days,buying,selling,
		item_name,valid_from,brand,price_list,item_code,price_list_rate) values(uuid_short(),now(),now(),%s,%s,'0','KES',%s,'0','1','0',%s,now(),%s,%s,%s,%s)""",(user,user,item_name,item_name,"-",reference,item_code,price_per_unit))
	else:
		itempriceinsert = frappe.db.sql("""UPDATE `tabItem Price` SET price_list_rate =%s WHERE price_list =%s AND item_code =%s""",(price_per_unit,reference,item_code))
	setdefaultpricelist =frappe.db.sql("""UPDATE `tabItem Default` set default_price_list=%s where parent=%s""",(reference,item_code))
	frappe.response["affected_item"] = item_name
	frappe.response["affected_bidder"] = bidder_payload