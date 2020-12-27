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
from frappe.utils import nowdate, getdate, add_days, add_years, cstr, get_url, get_datetime
import copy
STANDARD_USERS = ("Guest", "Administrator")

class TenderQuotationAward(Document):
	def before_save(self):
		if "Tender" not in self.procurement_method and not self.is_internal:
			hint =" <p><b>Hint: </b>RFQs and Direct procurement awards can either be entered as externally generated order(with attachments) or the process restarted from Material Request</p>"
			frappe.throw(f"Non-Tendered items cannot be submitted. Please check your mode of procurement. {hint}")
	def before_cancel(self):
		if "Tender" in self.procurement_method:
			self.remove_linked_award()
	def remove_linked_award(self):
		item_code = self.item_code
		frappe.msgprint(f"De-linking Award from {item_code}")
		if "Tender" in self.procurement_method:
			item_code = self.item_code
			item_doc = frappe.get_doc("Item", item_code)
			pl = self.reference_number
			frappe.db.sql(f"""UPDATE `tabItem Default` SET default_supplier ='', default_price_list=''\
				WHERE parent ='{item_code}' and default_price_list ='{pl}'""")
			item_doc.add_comment("Shared", text=f"Award {pl} delinked from this item.")
			self.add_comment("Shared", text=f"Award {pl} delinked from this item.")
			frappe.msgprint(f"Award {pl} de-linked from item {item_code} successfully.")
	def re_evaluate_document(self):
		update_price_list(self, "Submitted")
	def mark_award_as_expired(self):
		self.db_set("workflow_state","Expired")
def expired_tenders_cron():
	d = frappe.db.sql("SELECT name FROM `tabTender Quotation Award` WHERE reference_number IN\
		 (SELECT name FROM `tabTender Number` WHERE expiry_date = current_date) ", as_dict=True)
	if isinstance(d, list) and d:
		refs = [x.get("name") for x in d]
		awards = [frappe.get_doc("Tender Quotation Award", x) for x in refs]
		for x in awards:
			x.mark_award_as_expired()
			x.remove_linked_award()
@frappe.whitelist()
def switch_bidder(selected_bidder,reference_name):
	doc = frappe.get_doc("Tender Quotation Award", reference_name)
	previously_awarded =""
	for x in doc.get("suppliers"):
		if x.awarded_bidder:
			previously_awarded = x.supplier_name
	user = frappe.session.user
	if doc.docstatus != 1:
		frappe.throw(f"Operation allowed for approved documents only")
		return
	if "Quotations Manager" not in frappe.get_roles(frappe.session.user):
		frappe.throw("Sorry, only Buyer role allowed to amend suppliers")
		return
	frappe.db.sql(f"""UPDATE `tabTender Quotation Award Suppliers`\
		 SET awarded_bidder=0 WHERE parent ='{reference_name}' AND name !=''""")
	frappe.db.sql(f"""UPDATE `tabTender Quotation Award Suppliers`\
		 SET awarded_bidder=1 WHERE supplier_name='{selected_bidder}'\
			  AND parent ='{reference_name}' AND name !=''""")
	doc.add_comment("Shared", text=f"{user} ammended awarded supplier\
		 from {previously_awarded} to {selected_bidder}")
	doc.notify_update()
	return

#++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
# THIS CODE MANUALLY UPDATES THE PRICELIST AND DEFAULT SUPPLIER OF AN ITEM ONLY WHEN AUTHORITY IS SOUGHT
@frappe.whitelist()
def tender_quotation_award_shorthand(docname):
	doc = frappe.get_doc("Tender Quotation Award", docname)
	update_price_list(doc,"Submitted")
def update_price_list(doc, state):
	try:
		item_code = doc.get("item_code")
		#frappe.msgprint(f"Starting process...{item_code}")
		reference = doc.get("reference_number") or "Standard Buying"
		procurement_method = doc.get("procurement_method")
		
		bidders = doc.get("suppliers")
		bidder_payload ={}
		for bidder in bidders:
			if(bidder.get("awarded_bidder")):
				bidder_payload = bidder
		suppname  = bidder_payload.get("supplier_name")
		price_per_unit = bidder_payload.get("unit_price")
		user = frappe.session.user
		item_name = frappe.db.get_value("Item",item_code,"item_name")
		if "Tender" in procurement_method:
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
		else:

			if not doc.get("department"):
				frappe.throw("Sorry, user department is mandatory for creation of Purchase Order")
			else:
				if doc.get("is_internal"):
					return
				else:
					frappe.throw("Non-Tendered items cannot be submitted. Please check your mode of procurement")
					po_doc = frappe.new_doc('Purchase Order')
					actual_name = suppname
					purchase_order_items = get_po_item_dict(actual_name,item_code,\
						reference, price_per_unit, doc)
					item_category = frappe.db.get_value("Item",item_code,'item_group')
					po_doc.update(
							{
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
								"items":purchase_order_items
							}
						)
					po_doc.insert()
					po = po_doc.get("name")
					frappe.msgprint(f"Purchase Order {po}\
						has been drafted successfully and posted in this system for further action.")
	except Exception as e:
		frappe.response["Exception"] = e
		frappe.throw(f"{e}")	
def get_po_item_dict(supplier, item_code, reference, quoted_price, award_doc, quantity =None):
	from mtrh_dev.mtrh_dev.stock_utils import get_item_default_expense_account
	purchase_order_items =[]
	row ={}
	department = award_doc.get("department")
	if not department:
		departmentqry = frappe.db.sql(f"""SELECT department FROM `tabMaterial Request`\
			WHERE name = (SELECT material_request FROM `tabRequest for Quotation Item` WHERE \
				parent ='{reference}' and item_code = '{item_code}' ) """, as_dict=True) 
		department = departmentqry[0].get("department")
	doc = frappe.get_doc("Item", item_code)
	item_group = doc.get("item_group") 
	default_warehouse = frappe.db.get_value("Item Default",\
		{"parent":item_code,"parenttype":"Item"},'default_warehouse') \
			or \
			frappe.db.get_value("Item Default",\
				{"parent":item_group,"parenttype":"Item Group"},'default_warehouse')
	row["item_code"]=item_code
	
	qty = quantity or frappe.db.get_value('Supplier Quotation Item',\
		{"request_for_quotation":reference,'item_code': item_code},'qty') or 1
	rate = quoted_price
	amount = float(qty) * float(rate)
	row["item_code"]=doc.get("item_code")
	row["item_name"]=doc.get("item_name")
	row["description"]=doc.get("description")
	row["rate"] = rate
	row["warehouse"] = default_warehouse
	#row["transaction_date"] = add_days(nowdate(), 0)
	row["schedule_date"] = add_days(nowdate(), 30)
	#Rate we have to get the quoted rate
	row["qty"]= qty
	row["stock_uom"]= doc.get("stock_uom")
	row["uom"] = doc.get("stock_uom")
	
	row["conversion_factor"]=1 #To be revised: what if a supplier packaging changes from what we have?
	#row["material_request"] =
	row["amount"] = amount #calculated
	row["net_amount"]=amount
	row["base_rate"] = rate 
	row["base_amount"] = amount
	row["expense_account"] = get_item_default_expense_account(item_code)
	row["department"] = department
	#Let's add this row to the items array
	purchase_order_items.append(row.copy())
	return purchase_order_items
