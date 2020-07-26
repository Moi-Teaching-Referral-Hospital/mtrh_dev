# -*- coding: utf-8 -*-
# Copyright (c) 2020, MTRH and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe import _
from frappe import msgprint
from frappe.utils.user import get_user_fullname
from frappe.model.document import Document
import datetime
from datetime import date
from frappe.core.doctype.communication.email import make
from mtrh_dev.mtrh_dev.workflow_custom_action import send_tqe_action_email
STANDARD_USERS = ("Guest", "Administrator")


class TQESubmitOperations(Document):
	pass
#https://discuss.erpnext.com/t/popup-message-using-frappe-publish-realtime/37286/2
def apply_tqe_operation(doc, state):
	docname= doc.name
	rfq_in_question = doc.rfq_no
	contract_terms = """<div>Legally binding terms</div>"""
	method =  frappe.db.get_value('Request for Quotation', rfq_in_question, 'mode_of_procurement')
	item_code =doc.item_name
	#winning_bidder_code = frappe.db.sql("""SELECT bidder FROM `tabTender Quotation Evaluation Decision` where parent=%s and idx=1""",(docname))
	winning_bidder_code = frappe.db.get_value('Tender Quotation Evaluation Decision', {"parent":docname,"idx":"1"}, 'bidder')
	actual_name = frappe.db.get_value('Supplier Quotation', winning_bidder_code, 'supplier_name')
	itemdict = frappe.db.get_value('Supplier Quotation Item',  {"item_code":item_code,"parent":winning_bidder_code}, ['rate', 'item_name', 'qty'], as_dict=1)
	#bidding_price = frappe.db.get_value('Supplier Quotation Item', {"item_code":item_code,"parent":winning_bidder_code}, 'rate')
	bidding_price = itemdict.rate
	item_name = itemdict.item_name
	#quantity=itemdict.qty
	schedule_date = frappe.db.sql("""SELECT date_add(current_date, INTERVAL 30 DAY);""")
	user = frappe.session.user
	item_uom_brand=frappe.db.get_value('Item', item_code, ['stock_uom','brand','deferred_expense_account'],as_dict=1)
	uom=item_uom_brand.stock_uom
	brand = item_uom_brand.brand
	#expense_account = item_uom_brand.deferred_expense_account
	
	#material_request_in_question = frappe.db.get_value('Request Quotation Item', {"item_code":item_code,"parent":rfq_in_question}, 'supplier_name')
	if  method =="Closed Tender":
		#Algorithm for closed tender
		"""
		1. We already have the winning bid, so:
			a) Create a new Price List name with the rfqin question
			b) Add items to create a new Item Price list
			c) set the pricelist as default for this item
		2)Create draft contracts for each bidder
			a)Get a list of all awarded bidders.
			b)Loop through the list to get actual supplier name and send the contracts 
		"""
		#1 a,b,c ==> see the function
		update_price_list(actual_name,item_code,rfq_in_question,item_name,bidding_price,user,"","")
		frappe.msgprint("You approved "+docname+" under RFQ "+rfq_in_question+" Supplier "+actual_name+" bidding_price "+str(bidding_price)+"\n\n\nObjective achieved: A new Price list(Tender Award) has been submitted.")
		#2a
		bidders_awarded_dict = frappe.db.get_list('Tender Quotation Evaluation Decision',
														filters={
															'parent': docname
														},
														fields=['bidder'],
														order_by='creation desc',
														as_list=False
													)
		#2b
		for awarded_bidder in bidders_awarded_dict:
			the_supplier = frappe.db.get_value('Supplier Quotation', awarded_bidder.bidder, 'supplier_name')
			contract_exists = frappe.db.exists({
				"doctype":"Contract",
				"party_name": the_supplier,
				"document_name": rfq_in_question 
			})
			if not contract_exists:		
				#Create draft contracts
				doc = frappe.new_doc('Contract')
				doc.update(
							{
								"party_type":"Supplier",
								"party_name": the_supplier,
								"party_user":"dsmwaura@gmail.ir.ke",
								"contract_terms":contract_terms,
								"document_type":"Request for Quotation",
								"document_name":rfq_in_question
							}
									)
				doc.insert()
	else:
		#Algorithm for other modes of purchase(besides tender) tied to this procurement(RFQ)
		"""
		1. Get material requests in question (based on the RFQ) in an array
		2. Filter out material requests in which this item exist and, 
		3. Obtain respective departments and quantities requested for this item
		4. Raise orders to the awarded bidder for each material request.
		5. Raise draft contract to that bidder
		"""
		#1
		material_requests_in_question = frappe.db.get_list('RFQ Material Requests',
														filters={
															'parent': rfq_in_question
														},
														fields=['material_request'],
														order_by='creation desc',
														as_list=False
													)
		lis_material_requests=[]
		lis_valid_material_requests=[]
		#2
		for mrq in material_requests_in_question:
			lis_material_requests.append(str(mrq.material_request))
			valid = frappe.db.exists({
						'doctype': 'Material Request Item',
						'item_code': item_code,
						'parent': mrq.material_request
					})
			if(valid):
				lis_valid_material_requests.append(str(mrq.material_request))
		#3
		for valid_mrq in lis_valid_material_requests:
			mr_request_dict = frappe.db.get_value('Material Request Item',  {"item_code":item_code,"parent":valid_mrq}, ['department', 'qty', 'expense_account'], as_dict=1)
			#4
			mr_qty = mr_request_dict.qty
			mr_department = mr_request_dict.department
			total_amount=  float(mr_qty)*float(bidding_price)
			mr_expense_account =mr_request_dict.expense_account
			doc = frappe.new_doc('Purchase Order')
			doc.update(
				{
					"supplier_name":actual_name,
					"supplier": actual_name,
					"supplier_test":actual_name,
					"company": frappe.defaults.get_user_default("company"),
					"conversion_rate":1,
					"currency":frappe.defaults.get_user_default("currency"),
					"naming_series": "PUR-ORD-.YYYY.-",
					"transaction_date" : date.today(),
					"total":total_amount,
					"net_total":total_amount,
					"grand_total":total_amount,
					"base_grand_total":total_amount,
					"items":[
								{
									"item_code" : item_code,
									"item_name": item_name,
									"description":item_name,
									"rate": bidding_price,
									"schedule_date": schedule_date[0][0],
									"qty":mr_qty,
									"stock_uom": uom,
									"uom":uom,
									"brand": brand,
									"conversion_factor":1.0,
									"material_request":valid_mrq,
									"amount": total_amount,
									"net_amount": total_amount,
									"base_rate": bidding_price,
									"base_amount": total_amount,
									"expense_account": mr_expense_account,
									"department": mr_department
								}
					]
				}
			)
			doc.insert()
			contract_exists = frappe.db.exists({
					'doctype': 'Contract',
					'party_name': actual_name,
					'document_name': rfq_in_question
				})
			#5
			if not contract_exists:	
				doc = frappe.new_doc('Contract')
				doc.update(
							{
								"party_type":"Supplier",
								"party_name": actual_name,
								"party_user":"dsmwaura@gmail.ir.ke",
								"contract_terms":contract_terms,
								"document_type":"Request for Quotation",
								"document_name":rfq_in_question
							}
						)
				doc.insert()
			frappe.msgprint("You approved the opinion to award "+rfq_in_question+"\n to bidder "+actual_name+"\n\n\nObjective achieved: Draft Purchase orders have been created")
	#Finally send notification
	send_tqe_action_email(docname,rfq_in_question, item_code)
@frappe.whitelist()
def update_price_list(suppname,itemcode,bidder,itemname,itemprice,user,uom,brand):
       	supplierdefault =frappe.db.sql("""UPDATE `tabItem Default` set default_supplier=%s where parent=%s""",(suppname,itemcode))
       	pricelist =frappe.db.sql("""INSERT INTO  `tabPrice List` (name,creation,modified,modified_by,owner,docstatus,currency,price_list_name,enabled,buying) values(%s,now(),now(),%s,%s,'0','KES',%s,1,1)""",(bidder,user,user,bidder))
       	itempriceinsert=frappe.db.sql("""INSERT INTO  `tabItem Price` (name,creation,modified,modified_by,owner,docstatus,currency,item_description,lead_time_days,buying,selling,
	item_name,valid_from,brand,price_list,item_code,price_list_rate) values(uuid_short(),now(),now(),%s,%s,'0','KES',%s,'0','1','0',%s,now(),%s,%s,%s,%s)""",(user,user,itemname,itemname,brand,bidder,itemcode,itemprice))
       	setdefaultpricelist =frappe.db.sql("""UPDATE `tabItem Default` set default_price_list=%s where parent=%s""",(bidder,itemcode))
def send_notifications(docname):
	lis_awarded_arr =[]
	lis_not_awarded_arr=[]
	#Get the list of awarded bidders
	lis_awarded = frappe.db.get_list('Tender Quotation Evaluation Decision',
														filters={
															'parent': docname
														},
														fields=['bidder'],
														order_by='creation desc',
														as_list=False
													)
	for winner in lis_awarded:
		name_of_supplier = frappe.db.get_value('Supplier Quotation', winner.bidder, 'supplier_name')
		lis_awarded_arr.append(str(name_of_supplier))
	#Get the list of unawarded bidders i.e everyone except the ones who won. 
	lis_not_awarded = frappe.db.get_list('Requests For Quotations',
														filters={
															'parent': docname,
															'bidder': ["NOT IN", lis_awarded_arr]
														},
														fields=['bidder'],
														order_by='creation desc',
														as_list=False
													)
	for regret in lis_not_awarded:
		name_of_supplier = frappe.db.get_value('Supplier Quotation', regret.bidder, 'supplier_name')
		lis_not_awarded_arr.append(str(name_of_supplier))
	#Send notifications to suppliers
	tqe = frappe.get_doc("Tender Quotations Evaluations", docname)
	if tqe.docstatus==1:
		tqe.send_to_suppliers(lis_awarded_arr,lis_not_awarded,docname)

def send_to_suppliers(self, winners, losers, docname):
	for rfq_supplier in winners:
		dynamic_link = frappe.db.get_value("Dynamic Link", {"link_name":rfq_supplier, "link_doctype":"Supplier", "parent_type":"Contact"},"parent")
		email =frappe.db.get_value("Contact Email", {"is_primary":"1", "parent_type":"Contact", "parent":dynamic_link}, "email_id")
		#update_password_link = self.update_supplier_contact(rfq_supplier, self.get_link())
		message ="Dear "+rfq_supplier+"\n We would like to notify yo that you passed the evaluation of your quotation"+docname+"\n Please reply to this email to accept or deny the terms and parameters set in the request for quotation/tender. NB: THIS IS NOT AN ORDER for goods."
		self.supplier_tqe_mail(rfq_supplier, email,"Notification of award", message)
	for rfq_supplier in losers:
		dynamic_link = frappe.db.get_value("Dynamic Link", {"link_name":rfq_supplier, "link_doctype":"Supplier", "parent_type":"Contact"},"parent")
		email =frappe.db.get_value("Contact Email", {"is_primary":"1", "parent_type":"Contact", "parent":dynamic_link}, "email_id")
		#update_password_link = self.update_supplier_contact(rfq_supplier, self.get_link())
		message ="Dear "+rfq_supplier+"\n We would like to notify yo that you DID NOT pass the evaluation of your quotation"+docname+"\n. You have 14 days from the receipt of this letter to appeal.\n You are invited to bid for other requests for quotation/tenders where you are eligible.\n NB: THIS IS NOT AN ORDER for goods."
		self.supplier_tqe_mail(rfq_supplier, email,"Letter of regret", message)

def supplier_tqe_mail(self, email, update_password_link, subject,message):
		full_name = get_user_fullname(frappe.session['user'])
		if full_name == "Guest":
			full_name = "Administrator"

		subject = _(subject)
		#template = "templates/emails/request_for_quotation.html"
		sender = frappe.session.user not in STANDARD_USERS and frappe.session.user or None
		attachments = None
		self.send_email(email, sender, subject, message, attachments)

def send_email(self, email, sender, subject, message, attachments):
	make(subject = subject, content=message,recipients=email,
		sender=sender,attachments = attachments, send_email=True,
			doctype=self.doctype, name=self.name)["name"]

	frappe.msgprint(_("Email sent to suppliers"))

def update_supplier_contact(self, rfq_supplier, link):
	'''Create a new user for the supplier if not set in contact'''
	update_password_link = ''

	if frappe.db.exists("User", rfq_supplier.email_id):
		user = frappe.get_doc("User", rfq_supplier.email_id)
	else:
		user, update_password_link = self.create_user(rfq_supplier, link)

	self.update_contact_of_supplier(rfq_supplier, user)

	return update_password_link
def update_contact_of_supplier(self, rfq_supplier, user):
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
def raise_po_based_on_direct_purchase(rfq):
	isDirectProcurement = frappe.db.exists({
		'doctype': 'Request for Quotation',
		'name': rfq,
		'mode_of_procurement': "Direct Procurement"
	})
	#ONLY RAISE ORDERS IF IT IS DIRECT PROCUREMENT
	if isDirectProcurement:
		doc = frappe.new_doc('Purchase Order')
		suppliers  = frappe.db.get_list('Request for Quotation Supplier',
														filters={
															'parent': rfq,
														},
														fields=['supplier'],
														order_by='creation desc',
														page_length=1,
														as_list=False
													)
		actual_name  = suppliers[0].supplier
		material_rq  = frappe.db.get_list('RFQ Material Requests',
														filters={
															'parent': rfq,
														},
														fields=['material_request'],
														order_by='creation desc',
														page_length=1,
														as_list=False
													)
		material_request_no = material_rq[0].material_request

		material_request_items  = frappe.db.get_list('Material Request Item',
														filters={
															'parent': material_request_no,
														},
														fields=['item_code'],
														order_by='creation desc',
														page_length=1,
														as_list=False
													)
		purchase_order_items = []
		row ={}
		total_amount =0.0
		for supplier_item in material_request_items:
			row["item_code"]=supplier_item.item_code
			item_dict = frappe.db.get_value('Material Request Item', {"parent":material_request_no,"item_code":supplier_item.item_code}, ["item_code",  "item_name",  "description",  "item_group","brand","qty","uom", "conversion_factor", "stock_uom", "warehouse", "schedule_date", "expense_account","department"], as_dict=1)
			qty = item_dict.qty
			default_pricelist = frappe.db.get_value('Item Default', {'parent': item_dict.item_code}, 'default_price_list')
			rate = frappe.db.get_value('Item Price',  {'item_code': item_dict.item_code,'price_list': default_pricelist}, 'price_list_rate')
			amount = float(qty) * float(rate)
			total_amount  = total_amount + amount
			row["item_name"]=item_dict.item_name
			row["description"]=item_dict.item_name
			row["rate"] = rate
			row["warehouse"] = item_dict.warehouse
			row["schedule_date"] = item_dict.schedule_date
			#Rate we have to get the current rate
			row["qty"]= item_dict.qty
			row["stock_uom"]=item_dict.stock_uom
			row["uom"] =item_dict.stock_uom
			row["brand"]=item_dict.brand
			row["conversion_factor"]=item_dict.conversion_factor #To be revised: what if a supplier packaging changes from what we have?
			row["material_request"] = material_request_no
			row["amount"] = amount #calculated
			row["net_amount"]=amount
			row["base_rate"] = rate 
			row["base_amount"] = amount
			row["expense_account"] = item_dict.expense_account
			row["department"] = item_dict.department
			#Let's add this row to the items array
			purchase_order_items.append(row)
			#exit loop when your'e done, execute the order below and start all over for the next supplier
		doc.update(
			{
				"supplier_name":actual_name,
				"supplier": actual_name,
				"supplier_test":actual_name,
				"company": frappe.defaults.get_user_default("company"),
				"conversion_rate":1,
				"currency":frappe.defaults.get_user_default("currency"),
				"naming_series": "PUR-ORD-.YYYY.-",
				"transaction_date" : date.today(),
				"total":total_amount,
				"net_total":total_amount,
				"grand_total":total_amount,
				"base_grand_total":total_amount,
				"items": purchase_order_items
			}
		)
		doc.insert()