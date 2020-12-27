# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

# ERPNext - web based ERP (http://erpnext.com)
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe, json
from frappe import _
from frappe.model.mapper import get_mapped_doc
from frappe.utils import get_url, cint, get_link_to_form
from frappe.utils.background_jobs import enqueue
from frappe import msgprint
from frappe.model.document import Document
import datetime
from frappe.utils import cint, flt, cstr, now
from datetime import date, datetime
from erpnext.stock.utils import get_stock_balance
from erpnext.stock.doctype.item.item import get_item_defaults, get_uom_conv_factor
from erpnext.setup.doctype.item_group.item_group import get_item_group_defaults
from erpnext.assets.doctype.asset_category.asset_category import get_asset_category_account
from erpnext.setup.doctype.brand.brand import get_brand_defaults
from frappe.utils import nowdate, getdate, add_days, add_years, cstr, get_url, get_datetime



class StockUtils(Document):
	pass
@frappe.whitelist()
def stock_availability_per_warehouse(item_code):
	warehouses =  frappe.db.get_list('Warehouse', filters={
    'disabled': "0"
	})
	warehouse_json ={}
	payload =[]
	global_shortage ="yes"
	for warehouse in warehouses:
		warehouse_name = warehouse.name
		balance = get_stock_balance(item_code, warehouse_name)
		if balance >0:
			global_shortage ="no"
			warehouse_json["warehouse_name"] = warehouse_name
			warehouse_json["balance"]=balance
			payload.append(warehouse_json)
	get_item_default_expense_account(item_code)
	frappe.response["payload"]=payload
	frappe.response["global_shortage"]=global_shortage
def raise_surplus_task_qty(item_code, quantity_required, except_warehouse):
	warehouses =  frappe.db.get_list('Warehouse', filters={
    'disabled': "0",
	'name':["!=",except_warehouse]
	})
	warehouse_json ={}
	payload =[]
	global_shortage ="yes"
	#1. 1st we return warehouses with item balances, excluding our former store
	for warehouse in warehouses:
		warehouse_name = warehouse.name
		balance = get_stock_balance(item_code, warehouse_name)
		if balance >0:
			global_shortage ="no"
			warehouse_json["warehouse_name"] = warehouse_name
			warehouse_json["balance"]=balance
			payload.append(warehouse_json)
	#[{"warehouse_name":"Stores-MTRH", "balance":6},{"warehouse_name":"Maintenance Store - MTRH", "balance":6}..]
	#2. Loop through the store to return what each one of them can afford
	qty_needed = quantity_required
	args = frappe._dict(payload)
	warehouse_dict ={}
	payload_to_return =[]
	for feasible_warehouse in args:
		if qty_needed > 0: #IF WE STILL HAVE SOME BALANCE on QTY NEEDED
			wh = feasible_warehouse.get("warehouse_name")
			wh_balance = feasible_warehouse.get("balance")
			warehouse_dict["warehouse_name"] = wh
			if float(wh_balance) >= float(qty_needed):
				warehouse_dict["can_afford"]=float(qty_needed) #CAN AFFORD THE WHOLE QTY NEEDED
				qty_needed =0
			else:
				warehouse_dict["can_afford"]= float(wh_balance)#CAN AFFORD  ONLY ITS BALANCE
				qty_needed = qty_needed - float(wh_balance) #DEDUCT WHAT THE STORE CAN AFFORD FROM QTY NEEDED
			payload_to_return.append(warehouse_dict)
	frappe.response["whatremained"]=qty_needed
	frappe.response["payload"]=warehouse_dict
	frappe.response["global_shortage"]=global_shortage
def validate_expiry_extension(doc,state):
	doctype = doc.get("document_type")
	if doctype =="Request for Quotation":
		rfq = doc.get("quotations_and_tenders")
		opened = frappe.db.sql(f"""SELECT name FROM `tabTender Quotation Opening`\
			WHERE rfq_no ='{rfq}' and docstatus = 1""", as_dict=True)
		if opened and len(opened)>0:#
			opening_doc = get_link_to_form("Tender Quotation Opening", opened[0].get("name"))
			frappe.throw(f"""Sorry, bids for this document have already been\
				 opened under reference {opening_doc} and as such it is a violation of PPADR Act to extend it""")
	return
@frappe.whitelist()
def get_item_default_expense_account(item_code):
	item_defaults = get_item_defaults(item_code, frappe.db.get_single_value("Global Defaults", "default_company"))
	item_group_defaults = get_item_group_defaults(item_code, frappe.db.get_single_value("Global Defaults", "default_company"))
	expense_account = get_asset_category_account(fieldname = "fixed_asset_account", item = item_code, company= frappe.db.get_single_value("Global Defaults", "default_company"))
	if not expense_account:
		expense_account = item_group_defaults.get("expense_account") or get_brand_defaults(item_code,frappe.db.get_single_value("Global Defaults", "default_company")) or item_defaults.get("expense_account")
	frappe.response["expense_account"] = expense_account
	frappe.response["company"]= frappe.db.get_single_value("Global Defaults", "default_company")
	return expense_account
def stock_reconciliation_set_default_price(doc,state):
	#CHECK THAT THE DEPARTMENT DIMENSION HAS BEEN SET. IT IS NEEDED IN THE BALANCE SHEET ACCOUNT ENTRIES.
	if not doc.get("department"):
		frappe.throw("Please set the department where these items are intended to be used. This is mandatory when tracking accounts.")

	count =0
	for item in doc.items:
		print("Working")
		item_code = item.item_code
		item_name = item.item_name
		price_per_unit = item.valuation_rate or 0.0
		default_pricelist = doc.name
		user = frappe.session.user
		#function  here
		update_price_list(item_code, item_name, price_per_unit,default_pricelist,user)
		count = count + 1
	frappe.msgprint("Successfully updated stock valuation rate for "+str(count)+" items.")
def update_price_list(item_code, item_name, price_per_unit,default_pricelist,user):
	print("Starting business")
	#======================================================================
	#INSERT A BLANK ROW IN ITEM DEFAULT IF NONE EXIST ELSE DO NOTHING
	#======================================================================
	company = frappe.db.get_single_value("Global Defaults", "default_company")
	item_default_exists = frappe.db.exists({
		'doctype': 'Item Default',
		'parent':item_code,
	})
	#frappe.throw("Starting processing of payload for {0}...".format(item_code))
	if not item_default_exists:
		frappe.msgprint("Creating a defaults entry...")
		frappe.db.sql("""INSERT INTO  `tabItem Default` (name,creation,modified,modified_by,owner,docstatus,parent,company, parenttype, parentfield) values(uuid_short(),now(),now(),%s,%s,'0',%s,%s,"Item","item_defaults")""",(user,user,item_code,company))
	#======================================================================
	#INSERT A PRICE LIST IF ONE DOES NOT EXIST ELSE DO NOTHING
	#======================================================================
	if not frappe.db.exists({
				'doctype': 'Price List',
				'name': default_pricelist,
			}):
			pricelist = frappe.db.sql("""INSERT INTO  `tabPrice List` (name,creation,modified,modified_by,owner,docstatus,currency,price_list_name,enabled,buying) values(%s,now(),now(),%s,%s,'0','KES',%s,1,1)""",(default_pricelist,user,user,default_pricelist))
	item_name = frappe.db.get_value('Item', {'parent': item_code}, 'item_name')
	#==============================================================================================
	#INSERT THE ITEM PRICE IF ONE DOES NOT EXIST, ELSE UPDATE EXISTING ITEM PRICE FOR THIS ITEM CODE
	#==============================================================================================
	if not frappe.db.exists({
				'doctype': 'Item Price',
				'price_list': default_pricelist,
				'item_code':item_code,
			}):
		itempriceinsert=frappe.db.sql("""INSERT INTO  `tabItem Price` (name,creation,modified,modified_by,owner,docstatus,currency,item_description,lead_time_days,buying,selling,
	item_name,valid_from,brand,price_list,item_code,price_list_rate) values(uuid_short(),now(),now(),%s,%s,'0','KES',%s,'0','1','0',%s,now(),%s,%s,%s,%s)""",(user,user,item_name,item_name,"-",default_pricelist,item_code,price_per_unit))
	else:
		itempriceinsert = frappe.db.sql("""UPDATE `tabItem Price` SET price_list_rate =%s WHERE price_list =%s AND item_code =%s""",(price_per_unit,default_pricelist,item_code))
	#======================================================================
	#UPDATE THE PRICE LIST FOR THIS ITEM
	#======================================================================
	setdefaultpricelist =frappe.db.sql("""UPDATE `tabItem Default` set default_price_list=%s where parent=%s""",(default_pricelist,item_code))
def item_workflow_operations(doc, state):
	from mtrh_dev.mtrh_dev.duplicate_item_checker import duplicate_checker
	potential_duplicates = duplicate_checker(doc.get("item_name"))
	for entry in potential_duplicates:
		if entry.get("ratio")>98:
			frappe.db.set_value("Item",doc.get("name"),"disabled",1)
			frappe.throw("There is a duplicate entry {0} {1} and therefore this item will be disabled".format(entry.get("item_code"), entry.get("item_name")))
	if state == "before_save":
		frappe.db.set_value("Item",doc.get("name"),"disabled",1)
	if state=="on_submit":
		frappe.db.set_value("Item",doc.get("name"),"disabled",0)
def document_expiry_extension(doc,state):
	from mtrh_dev.mtrh_dev.utilities import forcefully_update_doc_field
	datefields_to_update = { 
        "Purchase Order": "schedule_date", 
        "Material Request": "schedule_date", 
        "Request for Quotation": "transaction_date", 
		"Contract": "end_date"
    }
	docfields  = { 
        "Purchase Order": "document_name", 
        "Material Request": "material_requests", 
        "Request for Quotation": "quotations_and_tenders", 
		"Contract": "contracts"
    }
	doctype = doc.get("document_type")
	name_of_field = docfields.get(doctype)
	docname = doc.get(name_of_field)
	forcefully_update_doc_field(doctype, docname, datefields_to_update.get(doctype), doc.get("to_this_date"))
	#frappe.db.set_value(doctype,docname,datefields_to_update.get(doctype),doc.get("to_tdate"))
	frappe.msgprint("Successfully updated {0} date for {1} - {2} from {3} to {4}".
					format(datefields_to_update.get(doctype),doctype,docname,doc.get("from_date"),doc.get("to_this_date")))
def externally_generated_po(doc, state):
	if doc.get("items"):
		itemstable =   doc.get("items")
		actual_name = doc.get("supplier")
		naming_series = "PUR-EX-ORD-.YYYY.-"
		if doc.is_proforma_invoice == True:
			naming_series = "PUR-PRF-ORD-.YYYY.-"
		try:
			sq_doc = frappe.get_doc({
				"doctype":"Purchase Order",
				"naming_series": naming_series,
				"supplier_name": actual_name, 
				"conversion_rate":1,
				"currency":frappe.defaults.get_user_default("currency"),
				"supplier": actual_name,
				"supplier_test":actual_name,
				"company": frappe.defaults.get_user_default("company"),
				"transaction_date" : doc.get("posting_date"),
				"item_category":"",
				"schedule_date" : add_days(nowdate(), 30),
				"items": itemstable.copy()
			})		
			
			sq_doc.flags.ignore_permissions = True
			sq_doc.run_method("set_missing_values")
			sq_doc.save()
			
			frappe.db.sql("""UPDATE `tabPurchase Order Item` SET department = '{0}', externally_generated_order='{1}' WHERE parent ='{2}'""".format(doc.get("department"),doc.get("name"), sq_doc.get("name")))	
			#frappe.db.set_value(doc.get("doctype"), doc.get("name"),"linked_po",sq_doc.get("name"))
			if doc.get("is_approved"):
				sq_doc.submit()
			doc.add_comment('Shared', text="Purchase Order {0} has been generated and submitted in this system ".format(sq_doc.get("name")))
			frappe.msgprint("Purchase Order {0} has been generated and submitted in this system ".format(sq_doc.get("name")))
		except Exception as e:
			frappe.throw("Could not complete transaction because : {0}".format(e)) 

def external_lpo_save_transaction(doc,state):
	doc.validate_amount()
def sync_external_order_attachments(doc, state):
	##CONTEXT IS PURCHASE ORDER
	externally_generated_items = [x.get("externally_generated_order") for x in doc.get("items") if x.get("externally_generated_order")]
	if isinstance(externally_generated_items, list) and externally_generated_items:
		attachments = """"""
def update_mr_reference_number():
	#ORIGINAL_USER_REQUEST
	stock_entries = frappe.db.sql("""SELECT name FROM `tabStock Entry` WHERE ORIGINAL_USER_REQUEST is NULL;""", as_dict=True)
	print(stock_entries)
	if isinstance(stock_entries, list) and  stock_entries:
		documents = [frappe.get_doc("Stock Entry",x.get("name")) for x in stock_entries]
		for d in documents:
			mr = d.get("items")[0].get("material_request")
			if mr:
				d.db_set("ORIGINAL_USER_REQUEST", mr)	
@frappe.whitelist()
def get_child_groups(group_name):
	child_groups = frappe.db.sql(f"""SELECT name FROM `tabItem Group`\
		 WHERE name ='{group_name}' OR parent_item_group ='{group_name}'""", as_dict=True)
	return [x.get("name") for x in child_groups]
def validate_material_request(doc, state):
	from mtrh_dev.mtrh_dev.utilities import get_link_to_form_new_tab
	mr_item_group = doc.item_category
	all_available_groups = get_child_groups(mr_item_group)
	#all_available_groups = the_child_groups.append(mr_item_group)
	items = doc.get("items")
	'''items_not_for_group =[x.get("item_code") for x in items \
		if not frappe.db.get_value("Item", {"item_group": mr_item_group, \
			"item_code":x.get("item_code")},"name")]'''
	items_not_for_group =[]
	for x in items:
		the_item_group = frappe.db.get_value("Item", { "item_code":x.item_code},"item_group")
		if the_item_group not in all_available_groups:
			items_not_for_group.append(x.item_code) 
	'''[x.get("item_code") for x in items \
		if not frappe.db.get_value("Item", {"item_group": ["IN",all_available_groups], \
			"item_code":x.get("item_code")},"name")]'''
	itemlist = "<p></p>"
	for d in items_not_for_group:
		item_dict = frappe.db.get_value("Item", d, ["item_name","item_group"], as_dict =True)
		item_group = item_dict.get("item_group")
		link_to_item = get_link_to_form_new_tab("Item",d, item_dict.get("item_name"))
		itemlist += f"<li>{link_to_item} : {item_group}</li>"
	if mr_item_group and items_not_for_group and len(items_not_for_group)>0:
		#pass
		frappe.throw(f"""These items have been wrongly placed under {mr_item_group}: {itemlist}""")
	return
