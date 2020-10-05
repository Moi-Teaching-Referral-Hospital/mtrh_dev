# -*- coding: utf-8 -*-
# Copyright (c) 2020, MTRH and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe , json
from frappe import msgprint
from frappe.model.document import Document
from frappe.utils.background_jobs import enqueue
from frappe.desk.form.utils import get_pdf_link
from frappe.utils.verified_command import get_signed_params, verify_request
from frappe import _
from frappe.model.workflow import apply_workflow, get_workflow_name, \
	has_approval_access, get_workflow_state_field, send_email_alert, get_workflow_field_value
from frappe.desk.notifications import clear_doctype_notifications
from frappe.model.mapper import get_mapped_doc
from frappe.utils.user import get_users_with_role
import datetime
from datetime import date
from erpnext.stock.get_item_details import get_serial_no
from frappe.utils import nowdate, getdate, add_days, add_years, cstr, get_url, get_datetime
import copy
from frappe.utils import get_files_path, get_hook_method, call_hook_method, random_string, get_fullname, today, cint, flt
class WorkFlowCustomAction(Document):
	pass
#https://discuss.erpnext.com/t/popup-message-using-frappe-publish-realtime/37286/2
def process_workflow_custom_actions(doc, state):
	workflow = get_workflow_name(doc.get('doctype'))
	current_state = doc.status
	docname = doc.name
	full_user_name = frappe.db.get_value("User",frappe.session.user,"full_name")
	#frappe.msgprint("Current state "+str(current_state))
	#if current_state== "Cancelled" or current_state =="Terminated" or current_state =="Rejected":
	#frappe.publish_realtime(event='eval_js', message='alert("{0}")', user=frappe.session.user)
	# msgprint with server and client side action
	frappe.msgprint(msg='You '+current_state+" document "+docname+" please click the appropriate reason. If you need to add a comment please scroll to the bottom of this document and tag specific users",
		title='Document '+docname+' '+current_state,
		#raise_exception=FileNotFoundError
		primary_action={
			'label': _('Alert stakeholders for action'),
			'server_action': 'dotted.path.to.method',
			'args': {"comment_type":"Comment","comment_email":full_user_name, "reference_doctype":"Material Request", "reference_name":docname, content:""} })
@frappe.whitelist()
#Called by the frappe.prompt procedure in process_workflow_custom_actions method
def apply_custom_action(comment_type,comment_email,reference_doctype,reference_name):
	doc = frappe.new_doc('Comment')
	doc.comment_type = comment_type
	doc.comment_email = comment_email
	doc.reference_doctype = reference_doctype
	doc.reference_name = reference_name
	doc.insert()
	frappe.response["message"]=doc
	return
def update_material_request_item_status(doc, state):
	doctype = doc.get('doctype')
	items = doc.get("items")	
	if(doctype=="Request for Quotation"):
		#material_requests = doc.get("material_requests")

		items_list, mr_list_dup =[x.get("item_code") for x in items],\
			[x.get("material_request") for x in items]
		mr_list= list(dict.fromkeys(mr_list_dup))
		items_q, mrs_q =  '('+','.join("'{0}'".format(i) for i in items_list)+')', \
			 '('+','.join("'{0}'".format(i) for i in mr_list)+')'
			
		from mtrh_dev.mtrh_dev.utilities import get_doc_workflow_state
		
		if get_doc_workflow_state(doc) =="Re-Routed":
			frappe.db.sql(f"""UPDATE `tabMaterial Request Item` SET attended_to ='0'\
				WHERE item_code IN {items_q} and parent IN {mrs_q}""")
			action = list(map(lambda x: auto_generate_purchase_order_by_material_request_shorthand(x), mr_list))
		
		for mr in mr_list:
			count_attended_to = frappe.db.sql("""SELECT count(attended_to) as attended_count FROM `tabMaterial Request Item` WHERE parent = %s AND attended_to =1 """,(mr), as_dict=1)
			count_all_items = frappe.db.sql("""SELECT count(*) as all_count FROM `tabMaterial Request Item` WHERE parent = %s""",(mr), as_dict=1)
			per_attended_to = float(count_attended_to[0].attended_count) * 100/ float(count_all_items[0].all_count)
			frappe.db.set_value('Material Request', mr, 'per_attended', float(per_attended_to))		
	else:
		count_attended_to =0
		material_request =""
		for item in items:
			material_request = item.material_request
			item_code = item.item_code
			docname = frappe.get_value("Material Request Item", {"item_code": item_code, "parent":material_request},"name")
			frappe.db.set_value('Material Request Item', docname, 'attended_to', "1")
			count_attended_to = count_attended_to + 1
	
		count_all_items = frappe.db.sql("""SELECT count(*) as all_count FROM `tabMaterial Request Item` WHERE parent = %s""",(material_request), as_dict=1)
		count_all = 1 if float(count_all_items[0].all_count)  == 0 else float(count_all_items[0].all_count)
		per_attended_to = float(count_attended_to) * 100/ float(count_all)
		
		frappe.db.set_value('Material Request', material_request, 'per_attended', float(per_attended_to))
def process_pending_material_requests():
	pending_mrs_query =f"""SELECT DISTINCT parent FROM `tabMaterial Request Item`\
				  WHERE attended_to ='0' and docstatus ='1' """
	pending_mrs = frappe.db.sql(pending_mrs_query, as_dict=True)
	
	the_documents =[frappe.get_doc("Material Request",x.get("parent")) for x in pending_mrs]

	list(map(lambda x: process_material_request(x, "before_submit"), the_documents))
	return pending_mrs
@frappe.whitelist()		
def auto_generate_purchase_order_by_material_request_shorthand(docname):	
	doc = frappe.get_doc("Material Request", docname)
	'''if doc.get("per_attended")==0:
		for item in doc.get("items"):
			item.attended_to = 0
	doc.flags.ignore_permissions = True
	doc.save()'''
	process_material_request(doc, "before_submit")
def process_material_request(doc, state):
	'''
	-This is version 2 of [def auto_generate_purchase_order_by_material_request(doc,state):]
	-It compresses the code in an effective and less complex function
	-Removes unneccessary loops
	-Is more modular
	'''
	try:
		all_items , all_items_dict = [x.get("item_code")
		for x in doc.get("items") if x.get("attended_to")=="0"],\
			[x for x in doc.get("items") if x.get("attended_to")=="0"]
		all_items_q_str = '('+','.join("'{0}'".format(i) for i in all_items)+')'
		if doc.get("material_request_type") == "Purchase" and all_items:
			filtered_dict =[]
			awarded_items_query =f"""SELECT DISTINCT parent FROM `tabItem Default` 
			WHERE parent in {all_items_q_str} AND (default_supplier !='' or default_supplier IS NOT NULL) """
			#---------------------------------------------------------------------------------------
			######PURCHASE ORDER
			#-----------------------------------------------------------------------------------------
			#frappe.throw(awarded_items_query)
			awarded_items = frappe.db.sql(awarded_items_query, as_dict=True)
			awarded_item_list =[]
			if awarded_items:
				frappe.msgprint(f"Beginning raising orders...'{all_items_q_str}'")
				awarded_item_list = [x.get("parent") for x in awarded_items]
				#FURTHER FILTER THE ITEM DICT TO REMAIN WITH AWARDED ITEMS
				filtered_dict = [x for x in all_items_dict if x.get("item_code") in awarded_item_list]
				itm = len(filtered_dict)
				frappe.msgprint(f"{itm} items to be raised on PO..")
				raise_orders(doc, filtered_dict, all_items_q_str)
				
			#-------------------------------------------------------------------------------------------
			#####REQUEST FOR QUOTATION
			#--------------------------------------------------------------------------------------
			unawarded_items_list = [x for x in all_items if x not in awarded_item_list]
			if unawarded_items_list:
				frappe.msgprint("Beginning raising requests to vendors...")
				filtered_dict = [x for x in all_items_dict if x.get("item_code") in unawarded_items_list]	
				raise_rfq(doc, filtered_dict)
				
		else:
			#raise_stock_entry(doc, all_items)
			return
		#set_attended_to(doc, all_items_q_str)
	except Exception as e:
		frappe.throw(f"Sorry an error occured because: {e}")
def raise_orders(doc, items, itemsarr):
	try:
		item_codes = [x.get("item_code") for x in items]
		item_codes_q_str = '('+','.join("'{0}'".format(i) for i in item_codes)+')'
		supplier_list = frappe.get_all('Item Default',
												filters={
													'parent': ["IN", item_codes]
												},
												fields=['default_supplier'],
												order_by='creation desc',
												group_by='default_supplier',
												as_list=False
											)
		l_sup = len(supplier_list)
		frappe.msgprint(f"{l_sup} suppliers found")
		frappe.msgprint(f"{item_codes} list of coded in context")
		for supplier in supplier_list:
			the_supplier = supplier.get("default_supplier")
			supplier_items = frappe.db.sql(f"""SELECT DISTINCT parent FROM\
				`tabItem Default`\
					WHERE default_supplier ='{the_supplier}' AND parent IN\
						 {item_codes_q_str}""", as_dict=True)
			supplier_item_list = [x.get("parent") for x in supplier_items]
			filtered_supplier_item_dict =[x for x in items\
				 if x.get("item_code") in supplier_item_list]
			frappe.msgprint(f"Sending an order for {supplier}")
			raise_order(the_supplier, filtered_supplier_item_dict, doc.get("item_category"), doc.get("name"))
			set_attended_to(doc, supplier_item_list)
	except Exception as e:
		frappe.throw(f"Error: {e}")			
def raise_order(supplier, supplier_items, item_category, material_request_number):
	try:
		frappe.msgprint("Raising Purchase Order")
		po_doc = frappe.get_doc({
				"doctype": "Purchase Order",
				"supplier_name":supplier,
				"conversion_rate":1,
				"currency":frappe.defaults.get_user_default("currency"),
				"supplier": supplier,
				"supplier_test":supplier,
				"company": frappe.defaults.get_user_default("company"),
				"naming_series": "PUR-ORD-.YYYY.-",
				"transaction_date" : date.today(),
				"item_category":item_category,
				"schedule_date" : add_days(nowdate(), 30),
			})
		for item_dict in supplier_items:
			item = item_dict.get("item_code")
			qty = item_dict.qty
			default_pricelist = frappe.db.get_value('Item Default', {'parent': item}, 'default_price_list')
			rate = frappe.db.get_value('Item Price',  {'item_code': item,'price_list': default_pricelist},\
				'price_list_rate') or item_dict.get("rate")
			amount = float(qty) * float(rate)
			po_doc.append('items',{
				'item_code': item,
				'item_name' : item_dict.item_name,
				'description': item_dict.item_name,
				'rate' : rate,
				'warehouse' : item_dict.warehouse,
				'schedule_date': add_days(nowdate(), 30),
				'qty': item_dict.qty,
				'stock_uom' : item_dict.stock_uom,
				'uom': item_dict.uom,
				'brand' : item_dict.brand,
				'conversion_factor': item_dict.conversion_factor,
				'material_request': material_request_number,
				'amount': amount,
				'net_amount': amount,
				'base_rate' : rate,
				'base_amount' : amount,
				'expense_account' : item_dict.get("expense_account"),
				'department': item_dict.department,
				'project': item_dict.project if item_dict.project else None
			})
		po_doc.flags.ignore_permissions =True
		po_doc.run_method("set_missing_values")
		po_doc.insert()
		po = po_doc.get("name")
		frappe.msgprint(f"Purchase order {po} created")
	except Exception as e:
		frappe.throw(f"Sorry transaction could not complete because: {e}")
	return
def get_item_group(item):
	return frappe.db.get_value("Item", item, 'item_group')
def raise_rfq(doc, items):
	item_codes = (x.get("item_code") for x in items)
	item_codes_q_str = '('+','.join("'{0}'".format(i) for i in item_codes)+')'
	item_category = doc.get("item_category") or get_item_group(items[0].get("item_code"))
	#frappe.msgprint(item_category)
	draft_rfqs_in_this_category = frappe.db.sql(f"""SELECT name FROM `tabRequest for Quotation`\
		WHERE buyer_section='{item_category}'\
			 AND workflow_state = 'Draft' AND mode_of_purchase IS NULL \
				 AND name NOT IN\
					  (SELECT parent FROM `tabRequest for Quotation Item`\
						   WHERE docstatus="0" AND item_code IN {item_codes_q_str})\
						   """, as_dict=True)
	if draft_rfqs_in_this_category:#
		documents =[frappe.get_doc("Request for Quotation", x.get("name")) for x in draft_rfqs_in_this_category]
		#I only need one so i'll take document at 0
		items_for_new_rfq =[]
		items_for_existing_rfq =[]
		rfq_doc2append = documents[0]
		for item in items:
			rfq_dict = None
			rfq_dict = item
			if rfq_dict.get("item_code") in [x.get("item_code") for x in rfq_doc2append.get("items")]:
				items_for_new_rfq.append(rfq_dict)
			else:
				items_for_existing_rfq.append(rfq_dict)#[{}]
				#append_item_to_rfq(documents[0], item)
		if items_for_new_rfq:
			raise_new_rfq(doc, items_for_new_rfq)#SECOND ARG IS A DICT
		if items_for_existing_rfq:
			doc2append = append_items_to_rfq(rfq_doc2append, items_for_existing_rfq)#SECOND ARG IS A DICT
			doc2append.run_method("set_missing_values")
			doc2append.save()
			items_attended = [x.get("item_code") for x in items_for_existing_rfq]
			set_attended_to(doc, items_attended)
	else:
		raise_new_rfq(doc, items)
	return
def append_items_to_rfq(sq_doc , items):
	material_request_number = items[0].get("parent")
	procurement_value = 0.0
	for item_dict in items:
		sq_doc.append('items', {
			"item_code": item_dict.get("item_code"),
			"item_name": item_dict.get("item_name"),
			"description": item_dict.get("description"),
			"qty": item_dict.get("qty"),
			"rate": item_dict.get("rate"),		
			"amount": item_dict.get("amount"),		
			"warehouse": item_dict.get("warehouse") or None,
			"material_request": material_request_number,
			"schedule_date": add_days(nowdate(), 30),
			"stock_uom": item_dict.get("stock_uom"),
			"uom": item_dict.get("uom"),
			"conversion_factor": item_dict.get("conversion_factor")
		})
		#ADD UP THE TOTAL VALUE  FOR THIS RFQ.
		#total = float(item_dict)
		procurement_value += flt(item_dict.get("amount"))

	#procurement_value = flt(sum(item.get('amount') for item in doc.get("items")))
	sq_doc.value_of_procurement = procurement_value

	if not material_request_number in [x.get("material_request") for x in sq_doc.get("material_requests")]:
		sq_doc.append('material_requests', {
			"material_request": material_request_number
		})
	sq_doc.flags.ignore_permissions = True
	return sq_doc
@frappe.whitelist()
def reroute_rfq_item(docname , item_ids):	
	try:
		item_ids = json.loads(item_ids)
		#frappe.throw(item_ids)
		doc = frappe.get_doc("Request for Quotation", docname)
		cdata =[frappe.get_doc("Request for Quotation Item", x) for x in item_ids]
		item_ids_str = '('+','.join("'{0}'".format(i) for i in item_ids)+')'
		items2raise =[]
		for data in cdata:
			mrdata, docname =None, None
			docname=frappe.get_value("Material Request Item",{"parent":data.get("material_request"),\
				"item_code": data.get("item_code")}, "name")
			mrdata = frappe.get_doc("Material Request Item", docname)
			items2raise.append(mrdata)
		#None, items2raise,doc.get("buyer_section"),frappe.defaults.get_user_default("Company")
		raise_new_rfq(None, items2raise,doc.get("buyer_section"),frappe.defaults.get_user_default("Company"))
		delete_items = f"DELETE FROM `tabRequest for Quotation Item` WHERE name IN {item_ids_str}"
		frappe.db.sql(delete_items)
		doc.notify_update
		return
	except Exception as e:
		frappe.throw(f"Sorry and error occured because of {e}")
def raise_new_rfq(doc, items, item_group=None, company_name=None):
	item_category = item_group or doc.get("item_category")
	prequalification_list = prequalified_suppliers_list(item_category)
	try:
		sq_doc = frappe.get_doc({
			"doctype": "Request for Quotation",
			"suppliers": prequalification_list,
			"buyer_section":item_category,
			"transaction_date": add_days(nowdate(), 30),
			"company": company_name or doc.get("company"),	
			"message_for_supplier": "Please find attached, a list of item/items for your response via a quotation. We now only accept responses to the quotation via our portal. \
				Responses by replying via email or via paper based methods are not accepted for this quote. Please login to the portal using your credentials here: https://portal.mtrh.go.ke. Then click on 'Request for Quotations', pick this RFQ/Tender and fill in your unit price inclusive of tax.",
			"status":"Draft"			
		})	
		sq_doc = append_items_to_rfq(sq_doc , items)
		sq_doc.flags.ignore_permissions = True
		sq_doc.run_method("set_missing_values")
		sq_doc.save()
		items_attended = [x.get("item_code") for x in items]
		set_attended_to(doc, items_attended)
	except Exception as e:
		frappe.throw(f"Sorry an error occured because : {e}")	
	return
def prequalified_suppliers_list(item_category):
	
	prequalified_suppliers_q	=	f"""SELECT DISTINCT supplier_name FROM `tabPrequalification Supplier`\
								WHERE item_group_name = '{item_category}' AND supplier_name !='Open Tender'\
									AND docstatus='1' """
	prequalified_suppliers = frappe.db.sql(prequalified_suppliers_q, as_dict=True)\
		 or [{"supplier_name":"Open Tender"}]
	
	theprequalifiedjson ={}
	theprequalifieddict =[]
	
	for supplier in prequalified_suppliers:
		theprequalifiedjson = {}
		thesupplier = supplier.get("supplier_name")
		contact = frappe.db.get_value("Dynamic Link",\
				{"link_doctype":"Supplier", "link_title":thesupplier, "parenttype":"Contact"} ,"parent")
		email = frappe.db.get_value("Contact", contact, "email_id")
		theprequalifiedjson["supplier"] =thesupplier
		theprequalifiedjson["supplier_name"] = thesupplier
		theprequalifiedjson["contact"] = contact
		theprequalifiedjson["email_id"] = email
		#----------------------------
		theprequalifiedjson["send_email"] = False
		theprequalifiedjson["email_sent"] = False
		theprequalifiedjson["no_quote"] = False
		theprequalifiedjson["quote_status"] = "Pending"
		theprequalifieddict.append(theprequalifiedjson)
	#frappe.response["fff"]=theprequalifieddict
	return theprequalifieddict
def raise_stock_entry(doc, items):
	pass
def set_attended_to(doc, items, action=None):
	docname = doc.get("name")
	items_str = '('+','.join("'{0}'".format(i) for i in items)+')'
	action_string =f" SET attended_to ='1' "
	if action:
		action_string = f"SET attended_to ='{action}'"
	update_action_query = f"UPDATE `tabMaterial Request Item` {action_string}\
		 WHERE parent = '{docname}' AND item_code IN {items_str};"
	frappe.db.sql(update_action_query)
	doc.notify_update()
def compute_percentage_attended_to(doc):
	pass
@frappe.whitelist()		
def auto_generate_purchase_order_by_material_request(doc,state):	
	material_request_number  = doc.get("name")

	item_category = doc.get("item_category")
	frappe.response["status..."]="Beginning work for "+item_category+" items"
	
	if doc.get("material_request_type") in ["Material Issue","Material Transfer"]:
		count = frappe.db.count('Stock Entry Detail', {'material_request': material_request_number})
		if count and count > 0:
			return
		else:
			frappe.msgprint("Forwarding request to the Stock Controller..")
			if doc.get("material_request_type") == "Material Transfer":
				to_warehouse = doc.get("set_warehouse")
				from_warehouse = doc.get("set_from_warehouse")
			else:
				to_warehouse = None
				from_warehouse = doc.get("set_warehouse")
			stock_entry_items  = doc.get("items")
			stock_entry_doc = frappe.new_doc('Stock Entry')
			updated_dict =[]
			updated_json={}
			attended_to_arr =[]
			frappe.response["status"] = "Creating a stock entry"
			for item in stock_entry_items:
				if item.get("attended_to") != "1":
					updated_json={}
					updated_json["item_code"]=item.get("item_code")
					updated_json["item_name"]=item.get("item_name")
					updated_json["department"]=item.get("deparment")
					updated_json["qty"]=item.get("qty")
					updated_json["material_request_qty"]=item.get("qty")
					updated_json["t_warehouse"]=to_warehouse
					updated_json["s_warehouse"]=from_warehouse
					transfer_qty = item.get("qty") * item.get("conversion_factor")
					updated_json["transfer_qty"]= transfer_qty
					updated_json["material_request"]= material_request_number
					updated_json["material_request_item"]=item.get("name")
					updated_json["basic_rate"]= item.get("rate")
					updated_json["valuation_rate"]=item.get("rate")
					updated_json["basic_amount"]=item.get("rate")*item.get("qty")
					updated_json["amount"]= item.get("rate")*item.get("qty")
					updated_json["allow_zero_valuation"]= "0"
					#material_request_item
					args = {
						'item_code'	: item.get("item_code"),
						'warehouse'	: from_warehouse,
						'stock_qty'	: transfer_qty
					}
					payload= frappe._dict(args)
					serial_no =  get_serial_no(payload) #if  get_serial_no(payload).get("message") else ""
					if serial_no:
						serial_no = get_serial_no(payload).message
					else:
						serial_no = ""
					updated_json["serial_no"]=serial_no
					frappe.response["updated json"]=updated_json
					updated_dict.append(updated_json.copy())
					attended_to_arr.append(item.get("name"))
			stock_entry_doc.update(
				{
					"naming_series": "MAT-STE-.YYYY.-",
					"stock_entry_type":doc.get("material_request_type"),			
					"company": frappe.defaults.get_user_default("company"),	
					"from_warehouse":from_warehouse,
					"issued_to": frappe.db.get_value("Employee",{"user_id":doc.owner},"employee_number") or "-",
					"to_warehouse":	to_warehouse,
					"requisitioning_officer":	doc.get("owner"),	
					"requisitioning_time":	doc.get("creation"),
					"items": updated_dict
				}
			)
			stock_entry_doc.insert(ignore_permissions=True)
			for docname in attended_to_arr:
				frappe.db.set_value("Material Request Item", docname, "attended_to", "1")
			#frappe.msgprint(doclist)
def update_stock_entry_data(doc,state):
	issuing_officer = frappe.session.user
	current_timestamp  =frappe.utils.data.now_datetime()
	frappe.db.set_value("Stock Entry",doc.name,"issued_by", issuing_officer)
	frappe.db.set_value("Stock Entry",doc.name,"issued_on", current_timestamp)
@frappe.whitelist()
def procurement_method_on_select(material_request, supplier_name):
	#VALIDATE THIS MATERIAL REQUEST FIRST
	docstatus = frappe.db.get_value("Material Request",material_request,"docstatus")
	is_purchase = frappe.db.exists({
						"doctype":"Material Request",
						"name": material_request,
						"material_request_type": "Purchase"
						})
	if docstatus ==1 and  is_purchase:
		#GET ALL UNATTENDED MATERIAL REQUEST ITEMS (PURCHASE) FOR THIS MR
		mr_items_filtered = frappe.db.get_list("Material Request Item",
			filters={
			"docstatus": "1",
			"attended_to":"0",
			"parent": material_request
			},
			fields="`tabMaterial Request Item`.item_code, `tabMaterial Request Item`.item_name,`tabMaterial Request Item`.procurement_method, sum(`tabMaterial Request Item`.qty) as quantity, `tabMaterial Request Item`.ordered_qty, `tabMaterial Request Item`.item_group, `tabMaterial Request Item`.warehouse, `tabMaterial Request Item`.uom, `tabMaterial Request Item`.description, `tabMaterial Request Item`.parent",
			order_by="creation desc",
			ignore_permissions = True,
			as_list=False
		)
		#RETURN SUPPLIER OBJECT TOO
		supplier_json_object ={}
		supplier_full_set =[]
		contact = frappe.db.get_value("Dynamic Link", {"link_doctype":"Supplier", "link_title":supplier_name, "parenttype":"Contact"} ,"parent")
		email = frappe.db.get_value("Contact", contact, "email_id")
		supplier_json_object["supplier_name"]=supplier_name
		supplier_json_object["contact"]=contact
		supplier_json_object["email"]=email
		supplier_full_set.append(supplier_json_object)
		#PREPARE A JSON OBJECT FOR THE SINGLE MR WE HAVE
		mr_list_filtered=[material_request]
		#RETURN PAYLOAD NOW
		frappe.response["status"] ="valid"
		frappe.response["suppliers_for_group"] = supplier_full_set
		frappe.response["filtered_items"] =mr_items_filtered
		frappe.response["material_requests"] = mr_list_filtered
	else:
		frappe.response["status"] ="invalid"
		frappe.response["docstatus"] = docstatus


@frappe.whitelist()
def buyer_section_on_select(item_group):
	#item_group = frappe.form_dict.item_group

	#GET ALL UNATTENDED MATERIAL REQUEST ITEMS (PURCHASE,TRANSFER, ISSUE etc) FOR THIS GROUP ONLY
	unattended_item_codes = frappe.db.get_list("Material Request Item",
		filters={
		"docstatus": "1",
			"attended_to":"0",
			"item_group": item_group
		},
		fields=["item_code"],
		order_by="creation desc",
		ignore_permissions = True,
		as_list=False
	)
	if unattended_item_codes:
		#Now build an unattended array of non-awarded items only
		unnattended_arr =[]
		for unattended in unattended_item_codes:
			unawarded = frappe.db.exists({
						"doctype":"Item Default",
						"parent": unattended.item_code,
						"default_supplier": ""
						})
			if unawarded:
					unnattended_arr.append(unattended.item_code.copy())
		#BUILD A ITEMS PAYLOAD NOW
		mr_items_filtered = frappe.get_list("Material Request Item",
			filters={
				"docstatus": "1",
				"attended_to":"0",
				"item_group": item_group,
				"item_code": ["IN", unnattended_arr]
			},
			fields="`tabMaterial Request Item`.item_code, `tabMaterial Request Item`.item_name,`tabMaterial Request Item`.procurement_method, sum(`tabMaterial Request Item`.qty) as quantity, `tabMaterial Request Item`.ordered_qty, `tabMaterial Request Item`.item_group, `tabMaterial Request Item`.warehouse, `tabMaterial Request Item`.uom, `tabMaterial Request Item`.description, `tabMaterial Request Item`.parent",
			group_by="item_code",
			order_by="creation",
			#page_length=2000
			ignore_permissions = True,
			#as_list=False
		)
		#BUILD A MATERIAL REQUEST LIST PAYLOAD NOW
		mr_list_filtered = frappe.get_list("Material Request Item",
			filters={
				"docstatus": "1",
				"attended_to":"0",
				"item_group": item_group,
				"item_code": ["IN", unnattended_arr]
			},
			fields=["parent"],
			order_by="creation",
			#page_length=2000
			ignore_permissions = True,
			#as_list=False
		)
		
		#BUILD A PREQUALIFICATION SUPPLIER PAYLOAD
		
		#STEP 3 RETURN PREQUALIFICATION LIST FOR ITEM CATEGORY
		#===============================
		#GET SUPPLIERS FOR THIS ITEM GROUP AS WELL.
		suppliers_for_group = frappe.db.get_list("Prequalification Supplier",
			filters={
				"item_group_name": ["IN", item_group],
				"docstatus":"1"
			},
			fields=["supplier_name"],
			ignore_permissions = True,
			as_list=False
		)
		#=====================================================================================
		#GET SUPPLIERS WITH CONTACTS. REMOVE SUPPLIERS IF ITEMS EMPTY
		supplier_full_set = []
		supplier_json_object={}
		for supplier in suppliers_for_group:
			contact = frappe.db.get_value("Dynamic Link", {"link_doctype":"Supplier", "link_title":supplier.supplier_name, "parenttype":"Contact"} ,"parent")
			email = frappe.db.get_value("Contact", contact, "email_id")
			supplier_json_object["supplier_name"]=supplier.supplier_name
			supplier_json_object["contact"]=contact
			supplier_json_object["email"]=email
			supplier_full_set.append(supplier_json_object)
		
		frappe.response["suppliers_for_group"] = supplier_full_set
		frappe.response["filtered_items"] =mr_items_filtered
		frappe.response["material_requests"] = mr_list_filtered
	else:
		frappe.response["suppliers_for_group"] = ""
		frappe.response["filtered_items"] = ""
		frappe.response["material_requests"] = ""
@frappe.whitelist()
def send_tqe_action_email(document,rfq, item):
	#frappe.msgprint(doc)
	doc = frappe.get_doc("Tender Quotations Evaluations",document)
	bidders_awarded =frappe.db.get_list("Tender Quotation Evaluation Decision",
			filters={
			 "parent":document
			 } ,
			fields=["bidder"],
			ignore_permissions = True,
			as_list=False
		)
	bidders_list =[]
	for bid in bidders_awarded:
		bidders_list.append(bid.bidder)
	frappe.response["bids"]=bidders_list
	supplier_list = frappe.db.get_list("Supplier Quotation",
			filters={
				"name": ["IN", bidders_list],
				#"docstatus":"1"
			},
			fields=["supplier","contact_person"],
			ignore_permissions = True,
			as_list=False
		)
	supplier_regret_bids = frappe.db.get_list("Supplier Quotation Item",
			filters={
				"parent": ["NOT IN", bidders_list],
				"request_for_quotation": rfq
				#"docstatus":"1"
			},
			fields=["parent"],
			ignore_permissions = True,
			as_list=False
		)
	contacts =[]
	contacts_regret = get_regret_contacts(supplier_regret_bids)
	for supplier in supplier_list:
		contacts.append(supplier.contact_person)
	frappe.response["contacts"]=contacts
	awarded_emails = frappe.db.get_list("Contact",
			filters={
			 "name":["IN", contacts],
			 } ,
			fields=["email_id"],
			ignore_permissions = True,
			as_list=False
		)
	unawarded_emails = frappe.db.get_list("Contact",
			filters={
			 "name":["IN", contacts_regret],
			 } ,
			fields=["email_id"],
			ignore_permissions = True,
			as_list=False
		)
	frappe.response["emails"]=awarded_emails
	item_name = frappe.db.get_value("Item",item,"item_name")
	if not item_name:
		item_name = item
	recipients=[]
	recipients_regret =[]
	for userdata in awarded_emails:
		recipients.append(userdata.email_id)
	for userdata in unawarded_emails:
		recipients_regret.append(userdata.email_id)
	send_notifications(recipients,"Dear sir/madam. We would like to notify you that you have been awarded tender/quotation "+rfq+" for your bid on "+item_name+"\nTHIS IS NOT A PURCHASE ORDER","Notification of Award for "+rfq+"/"+item_name,doc.get("doctype"),document)
	send_notifications(recipients_regret,"Dear sir/madam, we regret to notify you that you have NOT been awarded tender/quotation "+rfq+" for your bid on "+item_name,"Notification of Regret for "+rfq+"/"+item_name,doc.get("doctype"),document)
def get_regret_contacts(supplier_regret_bids):
	supplier_list = frappe.db.get_list("Supplier Quotation",
			filters={
				"name": ["IN", supplier_regret_bids],
				#"docstatus":"1"
			},
			fields=["supplier","contact_person"],
			ignore_permissions = True,
			as_list=False
		)
	contacts =[]
	for supplier in supplier_list:
		contacts.append(supplier.contact_person)
	return contacts
def send_notifications(recipients, message,subject,doctype,docname):
	#template_args = get_common_email_args(None)
	email_args = {
				"recipients": recipients,
				"message": _(message),
				"subject": subject,
				"attachments": [frappe.attach_print(doctype, docname, file_name=docname)],
				"reference_doctype": doctype,
				"reference_name": docname,
				}
	#email_args.update(template_args)
	#frappe.response["response"] = email_args
	enqueue(method=frappe.sendmail, queue='short', timeout=300, **email_args)
@frappe.whitelist()		
def auto_generate_purchase_order_using_cron():
	unattended_requests = frappe.db.get_list("Material Request",
			filters={
				"per_attended": ["<=", 99.99],
				"docstatus":"1",
				"material_request_type":"Purchase"
			},
			fields=["name"],
			ignore_permissions = True,
			as_list=False
		)
	the_list =[]
	for request in unattended_requests:
		material_request_number = request.name
		the_list.append(material_request_number)
		doc = frappe.get_doc ("Material Request", material_request_number)
		auto_generate_purchase_order_by_material_request(doc,"Submitted")
	frappe.response["thelist"] = the_list
#@frappe.whitelist(allow_guest =True)		
def raise_tqe(doc, state):
	#The RFQ tied to this sq
	parent  = doc.request_for_quotation
	if parent:
		#"CHECK IF AN EVALUATION FOR THIS RFQ/TENDER HAS BEEN ENTERED."
		exists = frappe.db.exists({
					"doctype":"Tender Quotation Evaluation",
					"rfq_no": parent,
				})
		if not exists:
			#Do a date comparison to check whether opening date has arrived
			print("Starting...")
@frappe.whitelist()
def dispatch_order(doc, state):
	doc = json.loads(doc)
	supplier_name = doc.get("supplier")
	contact = frappe.db.get_value("Dynamic Link", {"link_doctype":"Supplier", "link_title":supplier_name, "parenttype":"Contact"} ,"parent")
	email = frappe.db.get_value("Contact", contact, "email_id")
	if email:
		if not frappe.db.exists("User", email):
			user = frappe.get_doc({
					'doctype': 'User',
					'send_welcome_email': 1,
					'email': email,
					'first_name': supplier_name,
					'user_type': 'Website User'
					#'redirect_url': link
				})
			user.save(ignore_permissions=True)
		from frappe.utils import get_url, cint
		url = get_url("/purchase-orders/" + doc.get("name"))
		recipients =[email]
		order_expiry = doc.get("schedule_date") or add_days(nowdate(), 30)
		send_notifications(recipients, """Dear {0} please find the attached purchase order for your action. Please click on this link {1} to access the order so that you can fill in your e-delivery. Expiry date of this order is on  {2}. 
						Terms and Conditions apply""".format(supplier_name,url,order_expiry),"You have a new Purchase Order - {0} !".format(doc.get("name")),"Purchase Order", doc.get("name"))
		#send notifications
		frappe.db.set_value("Purchase Order", doc.get("name"), "schedule_date", order_expiry)
		frappe.response["expiry"] = order_expiry
		frappe.response["nowdate"] = nowdate()
		frappe.response["order"] = doc.get("name")
		frappe.msgprint("Order dispatched to {0}".format(supplier_name))
	else:
		recepients =[]
		for user in frappe.db.get_list("User",
			filters={
				"enabled": "1",	
				"email":["NOT IN",["erp@mtrh.go.ke","guest@example.com"]],	
			},
			fields=["email"],
			ignore_permissions = True,
			as_list=False
		):	
			#frappe.msgprint(user.email)
			user = frappe.get_doc("User", user.email)
			if user and "System Manager" in user.get("roles"):
				recepients.append(user.get("email"))
		#if recepients:
		send_notifications(recepients, "The contact details of the following supplier has not been added into the system. Please update the details to facilitate prompt notifications: {0}".format(supplier_name),"URGENT: Supplier Contact Update for {0}".format(supplier_name),"Supplier", supplier_name)
		frappe.throw("The supplier contact e-mail has not been set and therefore the supplier was not alerted. We have alerted the Supply Chain Manager and their team to follow up on the issue")
@frappe.whitelist()
def budget_balance(payload, document_date):
	#RETURNS TRUE IF THERE IS A BUDGET
	#fiscal_year = frappe.form_dict.fiscal_year
	#payload =  frappe.form_dict.payload
	outputArr = []
	department = ""
	balance_valid = ""
	#a Get Fiscal Year parameters
	fiscal_year_dict=frappe.db.sql("""SELECT year, year_start_date, year_end_date FROM `tabFiscal Year` 
									WHERE %s BETWEEN year_start_date AND year_end_date""",(document_date),as_dict=1)
	frappe.response["the_dict"]=fiscal_year_dict
	fiscal_year = fiscal_year_dict[0].year
	fiscal_year_starts = fiscal_year_dict[0].year_start_date
	fiscal_year_ends   = fiscal_year_dict[0].year_end_date
	
	payload_to_use = json.loads(payload)
	for itemrow in payload_to_use:
		department = itemrow["department"]
		expense_account = itemrow["expense_account"]
		amount = itemrow["amount"]
		
		#1 GET BUDGET ID
		budget = frappe.db.get_value('Budget', {'department': department,"fiscal_year": fiscal_year, "docstatus":"1"}, 'name')
		
		#2 GET BUDGET AMOUNT:
		budget_amount = frappe.db.get_value('Budget Account', {'parent':budget, "account":expense_account, "docstatus":"1"}, 'budget_amount')
		
		#3. GET SUM OF ALL APPROVED PURCHASE ORDERS: 
		total_commitments =  frappe.db.sql("""SELECT sum(coalesce(amount,0)) as total_amount FROM `tabPurchase Order Item` 
				WHERE docstatus =%s and department = %s and expense_account =%s and creation between %s and %s""",
				("1", department, expense_account, fiscal_year_starts, fiscal_year_ends), as_dict=1)
		
		"""
		total_commitments = frappe.get_list('Purchase Order Item',
			filters={
				'docstatus': 1,
				'department':department,
				'expense_account':expense_account,
				"creation": [">=", fiscal_year_starts],
				"creation": ["<=", fiscal_year_ends]
				#"docstatus": "==1"
			},
			fields="sum(`tabPurchase Order Item`.amount) as total_amount",
			order_by='creation',
			group_by='expense_account',
			#page_length=2000
			ignore_permissions = True,
			as_list=False
		)
		"""
		frappe.response["Returned commitments for {0} expense: {1} between {2} and  {3}... ".format(department,expense_account,fiscal_year_starts,fiscal_year_ends )]=total_commitments
		commitments = total_commitments[0].total_amount
		if commitments is None:
			commitments =0.0
		if budget_amount is None:
			budget_amount =0.0
		balance = float(budget_amount) - float(commitments)
		
		if(balance < amount ):
			balance_valid = "no"
			#frappe.msgprint("""Sorry, this order will not proceed because requests for Department"""+department+"""Expense account"""+expense_account+""" exceed the current vote which has a balance of """+str(balance)+""".""")
		else:
			balance_valid = "yes"
			
		itemrow["department"] = department
		itemrow["expense_account"] = expense_account
		itemrow["this_amount"] = amount
		itemrow["committed"] = commitments
		itemrow["budget_amount"] = budget_amount
		itemrow["balance"] = balance
		itemrow["balance_valid"] = balance_valid
		outputArr.append(itemrow)
	frappe.response["message"] = outputArr

