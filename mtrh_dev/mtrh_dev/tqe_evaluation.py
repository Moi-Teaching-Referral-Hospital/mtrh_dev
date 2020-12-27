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
from erpnext.controllers.buying_controller import BuyingController
import re
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
	#common_args = get_common_email_args(doc)
	message = "here is the password for adhoc"
	#common_args.pop('message', None)
	for d in users_data:
		email_args = {
			'recipients': d.user_mail,
			'args': {
				#'actions': list(deduplicate_actions(d.get('possible_actions'))),
				'message': message
			},
			'reference_name': rfqno,
			'reference_doctype': rfqno
		}
		#email_args.update(common_args)
		enqueue(method=frappe.sendmail, queue='short', **email_args)
@frappe.whitelist()
def Generate_Purchase_Receipt_Draft(doc, deliverynumber):
	doc1 = json.loads(doc)
	purchase_order_name = doc1.get('name')
	items = doc1.get('items')	
	supplier_name= frappe.db.get_value('Purchase Order', purchase_order_name, 'supplier')
	#frappe.throw(items)
	itemlistarray=[]
	row={}
	items_payload = json.dumps(items)
	payload_to_use = json.loads(items_payload)
	today = str(date.today())
	for item in payload_to_use:		
		row["item_code"]=item.get("item_code")	
		row["item_name"]=item.get("item_name")		
		row["description"]=item.get("item_name")		
		row["received_qty"]=item.get("tosupply")
		row["qty"] = item.get("tosupply")
		row["stock_qty"] = item.get("tosupply")
		row["sample_quantity"] = item.get("tosupply")
		row["conversion_factor"]=1
		row["schedule_date"]= today 
		row["rate"] = item.get("rate")		
		row["amount"] = item.get("amount")	
		row["purchase_order"]=purchase_order_name		
		row["stock_uom"]=item.get("stock_uom")
		row["uom"] =item.get("uom")
		row["brand"]=item.get("brand")	
		row["net_amount"]=item.get("amount")
		row["base_rate"] = item.get("rate") 
		row["base_amount"] = item.get("amount")
		row["department"] = item.get("department")
		row["expense_account"] = item.get("expense_account")
		row["material_request"] = item.get("material_request")
		row["rejected_warehouse"] = item.get("warehouse")	
		itemlistarray.append(row)
		
	
	for item_in in itemlistarray:						
		balance_to_supply = getquantitybalance(purchase_order_name,item_in.get("item_code"))
		#frappe.msgprint("we are here"+str(balance_to_supply))
		itemqtysupplied = item_in.get("received_qty")
		balance_qty=balance_to_supply
		#frappe.throw(itemqtysupplied)
		#frappe.msgprint(str(balance_to_supply))
		if itemqtysupplied > balance_qty:
			frappe.throw("You have exceeded the remaining balance for the item: " + item_in.get("item_code") + " - " + item_in.get("item_name") + " . The remaining balance to be supplied is: "+str(balance_to_supply))
		else:
			#frappe.msgprint("wedddddddddd")
			#frappe.throw(balance_to_supply)
		
			doc = frappe.new_doc('Purchase Receipt')
			doc.update(
					{	
						"naming_series":"MAT-PRE-.YYYY.-",
						"supplier":supplier_name,	
						"supplier_name":supplier_name,
						"posting_date":date.today(),
						"posting_time":datetime.now(),
						"company":frappe.defaults.get_user_default("company"),		
						"supplier_delivery_note":deliverynumber,
						"currency":frappe.defaults.get_user_default("currency"),
						"conversion_rate":"1",
						"items":itemlistarray														
					}
			)
			doc.insert(ignore_permissions = True)	
	#frappe.response['type'] = 'redirect'	
	#frappe.response.location = '/deliverynumber/'
def Check_Procurement_Rate_Estimate(doc, state):
	items = doc.get("procurement_item")
	row={}
	procurementitems=[]	
	for item in items:		
		row["item_code"]=item.get("item_code")	
		row["item_name"]=item.get("item_name")	 
		row["rate"] = item.get("rate")			
		procurementitems.append(row)
	for rate in procurementitems:
		item_rate = rate.get("rate")
		if item_rate==0: 	
			frappe.throw("Rate is zero")

		
@frappe.whitelist()
def make_purchase_invoice_from_portal(purchase_order_name,doc):	
	doc1 = json.loads(doc)	
	#doc = frappe.get_doc('Purchase Order Item', purchase_order_name) 
	form_items=doc1.get("items")
	
	supplier_name= frappe.db.get_value('Purchase Order', purchase_order_name, 'supplier')

	purchaseorderamount = frappe.db.get_list("Purchase Order Item",
			filters={
				"parent": purchase_order_name,
				"docstatus": ["=", 1]			
			},
			fields="sum(`tabPurchase Order Item`.qty) as purchaseorder_qty",			
			ignore_permissions = True,
			as_list=False
		)	
	lpoamount=0	
	for lpo in purchaseorderamount:
		lpoamount = lpo.get("purchaseorder_qty")
	#++++++++get submitted invoice items
	submittedinvoiceitems = frappe.db.get_list("Purchase Invoice Item",
			filters={
			"docstatus": ["!=", 2],		
			"purchase_order": purchase_order_name
			},
			fields="`tabPurchase Invoice Item`.item_code, `tabPurchase Invoice Item`.item_name,sum(`tabPurchase Invoice Item`.qty) as quantity, `tabPurchase Invoice Item`.department,`tabPurchase Invoice Item`.purchase_order,`tabPurchase Invoice Item`.rate",
			ignore_permissions = True,
			as_list=False
		)
	#loop and get the total quanity invoiced
	totalinvoicequantityamount=0	
	for item_10 in submittedinvoiceitems:
		itemcode = item_10.get("item_code")
		itemname = item_10.get("item_name")
		totalinvoicequantityamount = item_10.get("quantity")
		rate = item_10.get("rate")
		department = item_10.get("department")
		purchaseorder = item_10.get("purchase_order")		
	#==========================end of getting total invoiced items
	#frappe.response['totalqty'] = lpoamount
	# #=========================getting submitted purchase receipt items	
	approvedreceiptsnotinvoiced =  frappe.db.get_list("Purchase Receipt Item",
			filters={
				"purchase_order": purchase_order_name,
				"docstatus": ["=", 1],
				"invoiced":["!=", 1]			
			},
			fields="`tabPurchase Receipt Item`.name,`tabPurchase Receipt Item`.item_code, `tabPurchase Receipt Item`.item_name,`tabPurchase Receipt Item`.rejected_qty,sum(`tabPurchase Receipt Item`.rejected_qty) as totalrejectedqty,`tabPurchase Receipt Item`.department,`tabPurchase Receipt Item`.purchase_order,`tabPurchase Receipt Item`.rate,`tabPurchase Receipt Item`.received_qty,`tabPurchase Receipt Item`.amount,`tabPurchase Receipt Item`.qty",
			#fields=["qty","item_code","item_name","rejected_qty","received_qty","rate","amount"]			
			ignore_permissions = True,
			as_list=False
		)
	#frappe.throw(purchase_order_name)	
	rejected_qty=0
	invoiceqty=0
	purchaseinvoiceitemsarray=[]
	row={}			
	for item_30 in approvedreceiptsnotinvoiced:
		##########create child item array
		row["item_code"] = item_30.get("item_code")
		row["item_name"] = item_30.get("item_name")
		row["rejected_qty"] = item_30.get("rejected_qty")
		row["rate"] = item_30.get("rate")		
		row["purchase_order"] = item_30.get("purchase_order")
		row["amount"] = item_30.get("amount")
		totalrejectedquantity= item_30.get("totalrejectedqty")		
		row["qty"] = item_30.get("qty")
		row["purchase_receipt"] = item_30.get("reference_name")
		purchaseinvoiceitemsarray.append(row)		
		#frappe.msgprint(purchaseinvoiceitemsarray)
		##########End of Chid Item array

		itemcode = item_30.get("item_code")
		itemname = item_30.get("item_name")
		rejected_qty = item_30.get("rejected_qty")
		rate = item_30.get("rate")
		purchasereceiptname=item_30.get("parent")
		department = item_30.get("department")
		purchaseorder = item_30.get("purchase_order")
		amount = item_30.get("amount")
		received_qty = item_30.get("received_qty")
		rejectedqty = item_30.get("rejectedqty")
		qty = item_30.get("qty")
		namee = item_30.get("name")		
		submittedinvoiceitems = frappe.db.get_list("Purchase Invoice Item",
			filters={
				"purchase_order": purchase_order_name,
				"item_code":itemcode			
			},
			fields="sum(`tabPurchase Invoice Item`.qty) as qty",						
			ignore_permissions = True,
			as_list=False
		)
		for item_qty in submittedinvoiceitems:
			invoiceqty = item_qty.get("qty")
		#frappe.throw(invoiceqty)
		#balanceafterrejection = invoiceqty-rejectedqty
		#invoiceqty= frappe.db.get_value('Purchase Invoice Item', {'purchase_order':purchase_order_name,'item_code': itemcode}, 'qty')		
		if invoiceqty is None:
			invoiceqty=0
		#frappe.throw(invoiceqty)
		#qty_balance_for_item = qty-totalrejectedquantity	
		if invoiceqty < qty:#Create a Credit note and create and invoice also
			###########create invoice
			#frappe.msgprint("WE ARE HERE")
			#userr = frappe.session.user
			doc = frappe.new_doc('Purchase Invoice')
			doc.update(
					{	
						"naming_series":"ACC-PINV-.YYYY.-",
						"supplier":supplier_name,
						"purchase_receipt_name":purchasereceiptname,						
						"posting_date":date.today(),						
						"posting_time":datetime.now(),
						"company":frappe.defaults.get_user_default("company"),						
						"currency":frappe.defaults.get_user_default("currency"),					
						"items":purchaseinvoiceitemsarray														
					}
			)
			doc.insert(ignore_permissions = True)
			###########end of creating invoice###start of debit note
			########start of creating credit note for this item
			if rejected_qty > 0:				
				doc2 = frappe.new_doc('Credit Note')
				doc2.update(
					{	
						"naming_series":"MAT-CN-.YYYY.-",
						"qty":rejected_qty,
						"purchase_order":purchase_order_name																				
					}
				)
				doc2.insert(ignore_permissions = True)
			updatepurchasereceiptitem =frappe.db.sql("""UPDATE `tabPurchase Receipt Item` set invoiced=1 where name=%s""",(namee))			
       		#start of creating a credit note for this item
			balance_amount = flt(invoiceqty)-flt(qty)	
			frappe.response['totalqty'] = balance_amount
			frappe.msgprint("submitted Sucessfully")#insert the approved purchase to create a draft purchase invoice# Create a Credit note if the there is a rejected amount
		else:
			frappe.msgprint("You have already Invoiced Enough for this approved item"+itemcode)
	
	"""			
	if totalinvoicequantityamount is None:
			totalinvoicequantityamount=0
	if totalinvoicequantityamount < lpoamount:
		balance_amount = flt(lpoamount)-flt(totalinvoicequantityamount-rejected_qty)
		frappe.msgprint("You still have balance to submit")
		frappe.response['totalqty'] = balance_amount
	else:
		frappe.msgprint("You have submitted all the Invoices")	
		"""
	
#	frappe.response.location = '/Supplier-Delivery-Note/Supplier-Delivery-Note/'	
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
	attachments = [frappe.attach_print(doctype, docname, file_name=docname)]
	email_args = {
				"recipients": adhoc_list,
				"message": _(message),
				"subject": subject,
				"attachments": attachments or None,
				"reference_doctype": doctype,
				"reference_name": docname,
				}	
	enqueue(method=frappe.sendmail, queue='short', timeout=300, **email_args)
@frappe.whitelist()
def getquantitybalance(purchase_order_name,itemcode):
	total_qty = frappe.db.sql("""SELECT coalesce(sum(qty),0) FROM `tabPurchase Order Item` WHERE parent=%s""",(purchase_order_name))
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
@frappe.whitelist()
def stage_rfqs(userid):
	'''approved_rfqs = frappe.db.get_list("Request for Quotation",
			filters={
				"docstatus":1,				
			},
			fields=["name"],
			ignore_permissions = True,
			as_list=False
		)'''
	approved_rfqs = frappe.db.sql(f"""SELECT name FROM `tabRequest for Quotation`\
		 WHERE docstatus =1\
			  AND name NOT IN (SELECT reference_name FROM `tabDocument Email Dispatch`)   """, as_dict=True)
	docnames = [x.get("name") for x in approved_rfqs]
	list(map(lambda x: stage_supplier_email(frappe.get_doc("Request for Quotation",x),"submitted"), docnames))
	return
def dispatch_staged_email_cron():
	unsent_q = f"""SELECT name FROM `tabDocument Email Dispatch`\
		WHERE status not in ('On Hold','Sent') """ #status not in ('On Hold','Sent')
	list_unsent  = frappe.db.sql(unsent_q, as_dict=True)
	if list_unsent and len(list_unsent)>0:
		documents = [frappe.get_doc("Document Email Dispatch", x.get("name")) for x in list_unsent]
		list(map(lambda x: dispatch_staged_email(x,"Submitted"), documents))
	########SUPPLIER ACCOUNTS
	sent_q = f"""SELECT name, supplier, supplier_email FROM `tabDocument Email Dispatch`\
		WHERE status in ('Sent') AND account_created ='0' """
	list_sent  = frappe.db.sql(sent_q, as_dict=True)
	sent_docs = [frappe.get_doc("Document Email Dispatch", x.get("name")) for x in list_sent]
	list(map(lambda x: create_supplier_account(x.get("supplier"), x.get("supplier_email")), list_sent))
	list(map(lambda x: account_created(x), sent_docs))
	return
def account_created(doc):###doctype =Document Email Dispatch
	doc.set("account_created", True)
	doc.save()
	return
@frappe.whitelist()
def stage_po(docname):
	doc = frappe.get_doc("Purchase Order", docname)
	stage_supplier_email(doc , "before_submit")
def stage_supplier_email(doc, state):
	if doc.get('doctype')=="Purchase Order":
		po =doc.get("name")
		expiry = doc.get("schedule_date")
		message = f"Dear Sir/Madam,<br/>Please find attached purchase order {po} for your reference.\
			 Please note that the order is valid on or before {expiry}.<br>\
			.The list of items is shown on the attached document.<br/>"
		sq_doc = frappe.get_doc({
					"doctype": "Document Email Dispatch",
					"supplier": doc.get("supplier") or doc.get("supplier_name"),
					"supplier_email": doc.get("contact_email") or get_supplier_email(doc.get("supplier")),
					"message": message,
					"reference_doctype": doc.get("doctype"), 
					"reference_name":doc.get("name")
				})
		sq_doc.flags.ignore_permissions = True
		sq_doc.run_method("set_missing_values")
		sq_doc.insert()
	else: #RFQ
		suppliers = doc.get("suppliers")
		for row in suppliers:
			sq_doc = frappe.get_doc({
					"doctype": "Document Email Dispatch",
					"supplier": row.get("supplier"),
					"supplier_email": row.get("email_id")  or get_supplier_email(row.get("supplier")),
					"message": doc.get("message_for_supplier"),
					"reference_doctype": doc.get("doctype"), 
					"reference_name":doc.get("name")
				})
			sq_doc.flags.ignore_permissions = True
			sq_doc.run_method("set_missing_values")
			sq_doc.insert()
def dispatch_staged_email(doc , state):
	if '-EX-'  in doc.get("reference_name"):
		actual_doc = frappe.get_doc("Purchase Order",doc.get("reference_name"))
		doc_actual_ref = actual_doc.get("items")[0].externally_generated_order
		if frappe.get_value("Externally Generated Order", doc_actual_ref,'is_approved'):
			doc.db_set("status","Not to be sent")
			return
		#doc.save()
	if doc.get("status") not in ["Sent"]:
		dispatch_transaction(doc)
@frappe.whitelist()
def dispatch_transaction(document=None, docname =None):
	doc = document or frappe.get_doc("Document Email Dispatch", docname)
	doc2send = frappe.get_doc(doc.get("reference_doctype"), doc.get("reference_name"))
	doc.flags.ignore_permissions = True
	doc.run_method("set_missing_values")
	documenttype = doc2send.get("doctype")
	documentname = doc2send.get("name")
	supplier_email = doc.get("supplier_email")
	#regex = '^[a-z0-9]+[\._]?[a-z0-9]+[@]\w+[.]\w{2,3}$'
	message = doc.get("message")	
	if supplier_email and message:
		#if re.search(regex, supplier_email.strip()):
		if '@' in supplier_email and '.' in supplier_email:
			doc.set("status", "Sent")
			doc.set("supplier_email", supplier_email.strip())
			doc.save()			
			send_notifications([supplier_email.strip()], f"{message}",\
					f"{documenttype} - {documentname}",
						doc2send.get("doctype"),doc2send.get("name"))
			update_supplier_contact_custom(doc.get("supplier"), supplier_email.strip(), None)
		else:
			doc.set("status","Failed")
			doc.save()
	else:
		doc.set("status","Failed")
		doc.save()
	return
def create_supplier_account(supplier_name, email):
	if '@' in email and '.' in email:
		if not frappe.db.exists("User", email):
				user = frappe.get_doc({
						'doctype': 'User',
						'send_welcome_email': 1,
						'email': email,
						'first_name': supplier_name,
						'user_type': 'Website User'
						#'redirect_url': link
					})
				user.role_profile_name = 'Supplier Profile'
				user.save(ignore_permissions=True)
		else:
			user = frappe.get_doc("User", email)
			if(user.get("role_profile_name") != 'Supplier Profile'):
				user.role_profile_name = 'Supplier Profile'
				user.save(ignore_permissions=True)
def set_supplier_profile(doc, state):
	links =doc.get("links")
	if links:
		link_doctypes = [links[i].link_doctype for i in range(len(links))]
		userid = doc.get("user") or doc.get("email_id")
		supplier_name = doc.get("first_name") or "" +" "+doc.get("last_name") or ""
		if "Supplier" in link_doctypes and userid:
			create_supplier_account(supplier_name, userid)
			doc.set("user",userid)
			#doc.flags.ignore_permissions=True
			#doc.save
def update_supplier_contact_link_cron():
	rfqs_on_dispatch = frappe.db.sql(f"""SELECT reference_doctype, reference_name\
		 FROM `tabDocument Email Dispatch`\
			 WHERE status in ('Sent') AND reference_doctype='Request for Quotation'""", as_dict=True)
	docs =[frappe.get_doc(x.get("reference_doctype"), x.get("reference_name"))\
		for x in rfqs_on_dispatch]
	list(map(lambda x: update_supplier_contact_link(x), docs))

#
def update_supplier_contact(doc, rfq_supplier, link):
	'''Create a new user for the supplier if not set in contact'''
	update_password_link = get_link(doc)

	if frappe.db.exists("User", rfq_supplier.email_id):
		user = frappe.get_doc("User", rfq_supplier.email_id)
	else:
		create_supplier_account(rfq_supplier.supplier,  rfq_supplier.email_id)
	update_contact_of_supplier(rfq_supplier, user)
	
	return update_password_link 

def update_contact_of_supplier(rfq_supplier, user):
	if rfq_supplier.contact:
		contact = frappe.get_doc("Contact", rfq_supplier.contact)
	else:
		contact = frappe.new_doc("Contact")
		contact.first_name = rfq_supplier.supplier_name or rfq_supplier.supplier
		contact.append('links', {
			'link_doctype': 'Supplier',
			'link_name': rfq_supplier.supplier
		})

	if not contact.email_id and not contact.user:
		contact.email_id = user.name
		contact.user = user.name

	contact.save(ignore_permissions=True)
#
def update_supplier_contact_link(doc):
	link = get_link(doc)
	for rfq_supplier in doc.get('suppliers'):
		update_supplier_contact(doc, rfq_supplier, link)
def get_link(doc):
	from frappe.utils import get_url, cint
	# RFQ link for supplier portal
	return get_url("/rfq/" + doc.name)
def update_supplier_contact_custom(supplier, email=None, phone=None):
	contact = frappe.db.get_value("Dynamic Link", {"link_doctype":"Supplier", "link_title":supplier, "parenttype":"Contact"} ,"parent")
	if email:
		frappe.db.set_value("Contact", contact, "email_id", email)
	if phone:
		frappe.db.set_value("Contact", contact, "phone", phone)	
	return
def update_prequalification_list_cron():
	unflagged_rfqs = frappe.db.sql(f"""SELECT name FROM `tabRequest for Quotation`\
				WHERE prequalification_updated = 0  and docstatus='1'\
					 """,as_dict=True)
	doclist = [x.get("name") for x in unflagged_rfqs]
	if doclist:
		list(map(lambda x: update_prequalification_list_shorthand(x), doclist))
	return
@frappe.whitelist()
def update_prequalification_list_shorthand(docname):
	doc = frappe.get_doc("Request for Quotation", docname)
	if doc.get("docstatus")!=1:
		frappe.throw(f"Sorry, {docname} is not approved1")
	if doc.get("prequalification_updated") != True:
		update_prequalification_list(doc, "on_submit")
	return
def update_prequalification_list(doc, state):
	try:
		item_group = doc.get("buyer_section")
		supplier_list =[x.get("supplier") for x in doc.get("suppliers") if x.get("suppliers")!="Open Tender"]
		if supplier_list:
			prequalification_document = frappe.db.sql(f"""SELECT name FROM `tabPrequalification`\
				WHERE item_group ='{item_group}' and docstatus='1'\
					 """,as_dict=True)
			if not prequalification_document:
				create_new_preq(item_group, supplier_list) 
			else:
				doc2append = frappe.get_doc("Prequalification", prequalification_document[0].get("name"))
				doc2append = append_preq_supplier_list(doc2append,item_group, supplier_list)
				doc2append.flags.ignore_permissions=True
				doc2append.run_method("set_missing_values")
				doc2append.save()
			#user = frappe.session.user
			doc.add_comment('Comment', 'Updated list of prequalified bidders')
			frappe.db.set_value(doc.get("doctype"), doc.get("name"),"prequalification_updated",True)
			doc.notify_update()
	except Exception as e:
		frappe.throw(f"Sorry an error occured because {e}")
def create_new_preq(item_group, supplier_list):
	sq_doc = frappe.get_doc({
			"doctype": "Prequalification",
			"item_group": item_group,			
		})	
	sq_doc = append_preq_supplier_list(sq_doc ,item_group, supplier_list)
	sq_doc.flags.ignore_permissions = True
	sq_doc.run_method("set_missing_values")
	sq_doc.save()
	sq_doc.submit() 
def append_preq_supplier_list(doc2append, item_group, supplier_list):
	suppliers_in_list = [x.get('supplier_name') for x in doc2append.get('supplier_name')]
	for supplier in supplier_list:
		if not supplier in suppliers_in_list:
			doc2append.append('supplier_name',{"supplier_name": supplier,
												"item_group_name":item_group})
	return doc2append 
def get_supplier_email(supplier):
	dynamic_link = frappe.db.get_value("Dynamic Link", {"link_name":supplier, "link_doctype":"Supplier", "parenttype":"Contact"},"parent")
	email =frappe.db.get_value("Contact Email", {"is_primary":"1", "parenttype":"Contact", "parent":dynamic_link}, "email_id")
	return email
def create_grn_qualityinspectioncert_debitnote_creditnote(doc, state):
	docname=doc.name
	purchasereceipt_num = doc.get("reference_name")
	itemcode = doc.get("item_code")
	Receivedquantity = doc.get("total_sample_size")
	Acceptedquantity=doc.get("sample_size")
	Rejectedquantity=0.0
	Rejectedquantity=flt(Receivedquantity)-flt(Acceptedquantity)
	purchasereceiptitemname = frappe.get_value("Purchase Receipt Item", {"item_code": itemcode, "parent":purchasereceipt_num},"name")
	#purchasereceiptitemname = frappe.db.get_value("Purchase Receipt Item","parent":purchasereceipt_num,"name")
	#frappe.msgprint(str(Rejectedquantity))	
	frappe.db.sql("""UPDATE `tabPurchase Receipt Item` set rejected_qty=%s,qty=%s where parent=%s and item_code=%s""",(Rejectedquantity,Acceptedquantity,purchasereceipt_num,itemcode))
	if Rejectedquantity > 0:
		#frappe.msgprint("We are generating debit note now")
		docc = frappe.new_doc('Debit Note')
		docc.update({
			"naming_series":"MAT-DN-.YYYY.-",
			"quantity":Rejectedquantity,
			"purchase_receipt_number":purchasereceipt_num			
		})
		docc.insert(ignore_permissions = True)
		#frappe.db.sql("""UPDATE `tabPurchase Receipt` set bill_date=now(),status="To Bill",docstatus=1 where name=%s""",(docname))				
		#frappe.db.sql("""UPDATE `tabPurchase Receipt Item` set docstatus=1 where name=%s""",(purchasereceiptitemname))
	'''else:
		#frappe.msgprint("We are generating grn")
		updatepurchasereceiptstatus2 =frappe.db.sql("""UPDATE `tabPurchase Receipt` set bill_date=now(),status="To Bill",docstatus=1 where name=%s""",(docname))
		updatepurchasereceiptitem2 =frappe.db.sql("""UPDATE `tabPurchase Receipt Item` set docstatus=1 where name=%s""",(purchasereceiptitemname))
	'''
def update_member_list_on_opening_drafts(doc , state):
	opening_members = doc.get("adhoc_members")
	import random , string
	if opening_members:
		#letters = string.ascii_lowercase
		#random_id =''.join(random.choice(letters) for i in range(8)) 
		#opening_members.name = random_id
		#opening_members.user_password=opening_members.user
		#GET ALL DRAFT OPENING DOCS
		pending_sql =f"""SELECT name FROM `tabTender Quotation Opening` WHERE\
			docstatus = 0"""
		pending_docs = frappe.db.sql(pending_sql , as_dict=True)
		if pending_docs:
			documents = [frappe.get_doc("Tender Quotation Opening", x.get("name")) for x in pending_docs]
			list(map(lambda x: clear_and_update_drafts(x,opening_members), documents))
def clear_and_update_drafts(doc, new_members):
	#CONTEXT: TQ Opening
	doc.flags.ignore_permissions = True
	#doc.db_set('adhoc_members', [])
	the_new_members = [x.get("employee_name") for x in new_members]
	#memberlist = doc.append("adhoc_members",{})
	for d in doc.get("adhoc_members"):
		if d.get("employee_name") in the_new_members or d.get("logged_in")==False:
			rowid = d.get("name")
			frappe.db.sql(f"DELETE FROM `tabRequest For Quotation Adhoc Committee`\
				 WHERE name ='{rowid}'")
	for m in new_members:
		memberlist = doc.append("adhoc_members",{})
		memberlist.user = m.get("user")
		memberlist.employee_name = m.get("employee_name")
		memberlist.user_mail = m.get("user_mail")
		memberlist.logged_in = False
		memberlist.user_password = m.get("user")
	docname = doc.get("name")
	doc.save()
	doc = frappe.get_doc("Tender Quotation Opening", docname)
	idx =1
	for m in doc.get("adhoc_members"):
		if not m.get("user"):
			rowid = m.get("name")
			frappe.db.sql(f"DELETE FROM `tabRequest For Quotation Adhoc Committee`\
				 WHERE name ='{rowid}'")
		else:
			m.idx = idx
			idx+=1
	doc.save()
	doc.notify_update()
	
	