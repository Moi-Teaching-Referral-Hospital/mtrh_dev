# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

# ERPNext - web based ERP (http://erpnext.com)
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe, json
from frappe import _
from frappe.model.mapper import get_mapped_doc
from frappe.utils import get_url, cint
from frappe.utils.background_jobs import enqueue
from frappe import msgprint
from frappe.model.document import Document
import datetime
from frappe.utils import cint, flt, cstr, now
from datetime import date, datetime
from erpnext.buying.doctype.request_for_quotation.request_for_quotation import send_supplier_emails
from erpnext.stock.utils import get_stock_balance
class TQE(Document):
	pass
@frappe.whitelist()
def rfq_send_emails_suppliers(rfqno):
	userlist = frappe.db.get_list("Request For Quotation Adhoc Committee",
			filters={
				"parent": rfqno,				
			},
			fields=["user_mail","employee_name","user_password"],
			ignore_permissions = True,
			as_list=False
		)			
	lis_users =[]
	send_email_to_adhoc(userlist,rfqno)
	frappe.response["usermails"] =lis_users
@frappe.whitelist()
def send_email_to_adhoc(users_data,rfqno):
	message = "here is the password for adhoc"
	for d in users_data:
		email_args = {
			'recipients': d.user_mail,
			'args': {
				'message': message
			},
			'reference_name': rfqno,
			'reference_doctype': rfqno
		}
		enqueue(method=frappe.sendmail, queue='short', **email_args)
@frappe.whitelist()
def Generate_Task(doc, state):	
	doc_name = doc.get('name')
	user_existslist =frappe.db.get_list("ToDo", 
		filters={
			 "reference_name":doc_name
			 } ,
			fields=["owner"],
			ignore_permissions = True,
			as_list=False
		)
	for ownerr in user_existslist:
		ownr = ownerr.get("owner")	
	allocatedto = ownr	
	startdate=date.today()		
	taskdoc = frappe.new_doc('Task')	
	taskdoc.update(
				{	"name":"TASK-.YYYY.-",
					"subject":doc.get("subject"),	
					"issue":doc.get("name"),
					"status":doc.get("status"),
					"completed_by":allocatedto,
					"exp_start_date":startdate,
					"company":frappe.defaults.get_user_default("company")																			
				}
			)
	taskdoc.insert()
		
@frappe.whitelist()
def make_purchase_invoice_from_portal(purchase_order_name):		
	#doc = frappe.get_doc('Purchase Order Item', purchase_order_name) 
	#itemcode=doc.item_codess
	
	itemslist = frappe.db.get_list("Purchase Order Item",
			filters={
				"parent": purchase_order_name,				
			},
			fields=["item_code","item_name","qty"],
			ignore_permissions = True,
			as_list=False
		)
	itemlistarray=[]	
	for item in itemslist:
		itemlistarray.append(item.item_code)	
	frappe.throw(itemslist)
	frappe.response['type'] = 'redirect'	
	frappe.response.location = '/Supplier-Delivery-Note/Supplier-Delivery-Note/'	
	#frappe.response['delivey']=	deliverynotelist 

@frappe.whitelist()
def send_adhoc_members_emails(doc, state):	#method to send emails to adhoc members
	docname = doc.get('name')	
	adhocmembers =frappe.db.get_list("Request For Quotation Adhoc Committee", #get the list
		filters={
			 "parent":docname
			 } ,
			fields=["employee_name","user_mail","user_password"],
			ignore_permissions = True,
			as_list=False
		)
	adhoc_list =[]	
	for usermail in adhocmembers: #loop and get the mail array and create the arguments
		adhoc_list.append(usermail.user_mail)	
		send_notifications(adhoc_list,"Your password for Tender/Quotation Evaluation is:"+usermail.user_password,"Tender/Quotation Evaluation Credentials for::"+docname,doc.get("doctype"),docname)	
	frappe.response["mem"]=adhoc_list	

def send_notifications(adhoc_list, message,subject,doctype,docname):
	#template_args = get_common_email_args(None)
	email_args = {
				"recipients": adhoc_list,
				"message": _(message),
				"subject": subject,
				#"attachments": [frappe.attach_print(self.doctype, self.name, file_name=self.name)],
				"reference_doctype": doctype,
				"reference_name": docname,
				}	
	enqueue(method=frappe.sendmail, queue='short', timeout=300, **email_args)
@frappe.whitelist()
def getquantitybalance(purchase_order_name,itemcode):
	total_qty=frappe.db.sql("""SELECT coalesce(sum(qty),0) FROM `tabPurchase Order Item` WHERE parent=%s""",(purchase_order_name))
	total_amount_supplied=frappe.db.sql("""SELECT coalesce(sum(qty),0) FROM `tabPurchase Receipt Item` where purchase_order=%s and item_code=%s and docstatus !=2""",(purchase_order_name,itemcode))
	total_amount_inspected=frappe.db.sql("""SELECT coalesce(sum(sample_size),0) FROM `tabQuality Inspection` where reference_name in (select parent from `tabPurchase Receipt Item` where purchase_order=%s and item_code=%s) and docstatus='1'""",(purchase_order_name,itemcode))
	total_amount_inspected_rejected=frappe.db.sql("""SELECT coalesce(sum(sample_size),0) FROM `tabQuality Inspection` where  status LIKE %s and  reference_name in (select parent from `tabPurchase Receipt Item` where purchase_order=%s and item_code=%s) """,('%Rejected%',purchase_order_name,itemcode))
	
	quantity_balance = (total_qty [0][0])-(total_amount_supplied[0][0])
	bal_in_inspection=(total_amount_inspected[0][0])-(total_amount_inspected_rejected[0][0])
	total_bal = (quantity_balance)-(bal_in_inspection)
	#-(total_amount_inspected[0][0])))	
	#balance_amount=(total_amount_supplied[0][0])-((total_amount_supplied[0][0])-(total_amount_inspected[0][0]))
	#bal_amnt = (quantity_balance[0][0])-(balance_amount[0][0])
	#return total_qty[0][0] if total_qty[0][0] else 0.
	#return total_amount_inspected if total_amount_inspected else 0
	return quantity_balance if quantity_balance else 0

def Onsubmit_Of_Purchase_Receipt(doc, state):
	docname = doc.name
	itemdetails = frappe.db.get_list("Purchase Receipt Item",
			filters={
				"parent": docname,				
			},
			fields=["item_code","item_name","amount"],
			ignore_permissions = True,
			as_list=False
		)	
	
	for specificitem in itemdetails:
		itemcode=specificitem.get("item_code")
		itemname=specificitem.get("item_name")
		amount=specificitem.get("amount")
		itemtemplate = frappe.db.get_list("Item",
			filters={
				"name":itemcode,				
			},
			fields=["quality_inspection_template"],
			ignore_permissions = True,
			as_list=False
		)
		for template in itemtemplate:
			template_name=template.get("quality_inspection_template")	
	frappe.throw(template_name)	
	doc = frappe.new_doc('Quality Inspection')
	doc.update(
				{	
					"naming_series":"MAT-QA-.YYYY.-",
					"report_date":date.today(),	
					"inspection_type":"Incoming",
					"status":"Accepted",
					"item_code":"",
					"item_name":"",
					"quality_inspection_template":"",						
					"readings":itemlistarray														
				}
			)
	doc.insert(ignore_permissions = True)
def send_rfq_supplier_emails(doc, state):
	rfq = doc.get("name")
	send_supplier_emails(rfq)
def raise_task_materials(doc,state):
	if doc.issue_item and doc.status =="Raised bill of materials(BOM)":
		#proceed if there are items and status is working
		task_number = doc.name
		for item in doc.issue_item:
			#raise individual material requests for each item because, besides purpose, the item_groups may be different
			#in future the items can be grouped into group and mode_of purchase:
			#in short I am simplifying my work for today 12/06/2020 01:28
			#1. Check if items are in Material request
			item_code = item.item_code
			items = frappe.db.get_list("Material Request Item",
				filters={
					"task_no": task_number,
					"item_code": item_code,
					#"parent":["!=",task_number]				
				},
				fields=["item_code"],
				ignore_permissions = True,
				as_list=False
			)
			#2. Proceed if there are no material request items tied to this task number
			if not items:	
				preferred_purpose = item.description	
				qty_requested = float(item.qty)
				unit_price =1.0
				
				if item.rate:
					unit_price = float(item.rate)
				grand_total = float(qty_requested * unit_price)
				issue_raised_by = frappe.db.get_value("Issue", doc.issue,"raised_by")
				department = ""
				#IF ISSUE WAS RAISED BY AN EMPLOYEE, BILL THE BOM TO DEPARTMENT OF THE EMPLOYEE
				#ELSE BILL THE DEPARTMENT OF THE PERSON RAISING THIS TASK
				if issue_raised_by and frappe.db.get_value("Employee",issue_raised_by,"user_id"):
					department = frappe.db.get_value("Employee",issue_raised_by,"department")
				else:
					department = frappe.db.get_value("Employee",{"user_id":frappe.session.user},"department")
				##code to compare quantity requested vs available balances in the hopital soon
				rowdict ={}
				rowdict["item_code"] = item.item_code
				rowdict["item_name"] = item.item_code
				rowdict["qty"] = item.qty
				rowdict["brand"] = item.brand
				rowdict["stock_uom"] = item.stock_uom
				rowdict["uom"] = item.uom
				rowdict["rate"] = unit_price
				rowdict["amount"] = grand_total
				rowdict["conversion_factor"] = item.conversion_factor
				rowdict["schedule_date"] = item.schedule_date
				rowdict["expense_account"] = item.expense_account
				rowdict["department"] = department
				rowdict["warehouse"] = item.warehouse
				rowdict["stock_qty"] = item.stock_qty
				rowdict["task_no"] = item.task_no
				material_request_items = [frappe._dict(rowdict)]
				#3. CREATE MATERIAL REQUEST DOCUMENT
				material_request_doc = frappe.new_doc('Material Request')
				material_request_doc.update(
							{	
								"naming_series":"MAT-MR-.YYYY.-",
								"material_request_type":preferred_purpose,	
								"company":frappe.defaults.get_user_default("company"),
								"item_category":item.item_group,
								"department":department,
								"set_warehouse":item.warehouse,
								"transaction_date":date.today(),
								"requested_by":frappe.session.user,	
								"requester": frappe.session.user,					
								"items":material_request_items,
								"grand_total": grand_total,
								"total_request_value":grand_total,
							}
						)
				material_request_doc.insert(ignore_permissions = True)
				if preferred_purpose == "Material Issue" and item.surplus > 0:
					rowdict ={}
					rowdict["item_code"] = item.item_code
					rowdict["item_name"] = item.item_code
					rowdict["qty"] = item.surplus
					rowdict["brand"] = item.brand
					rowdict["stock_uom"] = item.stock_uom
					rowdict["uom"] = item.uom
					rowdict["rate"] = unit_price
					rowdict["amount"] = grand_total
					rowdict["conversion_factor"] = item.conversion_factor
					rowdict["schedule_date"] = item.schedule_date
					rowdict["expense_account"] = item.expense_account
					rowdict["department"] = department
					rowdict["warehouse"] = item.warehouse
					rowdict["stock_qty"] = item.stock_qty
					rowdict["task_no"] = item.task_no
					material_request_items = [frappe._dict(rowdict)]
					#3. CREATE PURCHASE MATERIAL REQUEST DOCUMENT
					material_request_doc = frappe.new_doc('Material Request')
					material_request_doc.update(
								{	
									"naming_series":"MAT-MR-.YYYY.-",
									"material_request_type":"Purchase",	
									"company":frappe.defaults.get_user_default("company"),
									"item_category":item.item_group,
									"department":department,
									"set_warehouse":item.warehouse,
									"transaction_date":date.today(),
									"requested_by":frappe.session.user,	
									"requester": frappe.session.user,					
									"items":material_request_items,
									"grand_total": grand_total,
									"total_request_value":grand_total,
								}
							)
					material_request_doc.insert(ignore_permissions = True)
		material_requests_raised = frappe.db.get_list("Material Request Item",
					filters={
						"task_no": task_number,
						},
						fields=["parent"],
						ignore_permissions = True,
						as_list=False
					)
		mreqlist =[]
		for mreq in material_requests_raised:
			mreqlist.append(mreq.parent)
		if mreqlist:
			humanreadable_list = ", ".join(mreqlist)
			frappe.msgprint("The following material requests have been raised for this task:\n "+str(humanreadable_list))
@frappe.whitelist()
def material_requests_per_task(task_number):
	material_requests_raised = frappe.db.get_list("Material Request Item",
					filters={
						"task_no": task_number,
						},
						fields=["parent"],
						ignore_permissions = True,
						as_list=False
					)
	mreqlist =[]
	for mreq in material_requests_raised:
		mreqlist.append(mreq.parent)
	frappe.response["material_requests"]=mreqlist