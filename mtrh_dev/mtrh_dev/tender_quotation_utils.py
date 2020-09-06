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
from frappe.utils import nowdate, getdate, add_days, add_years, cstr, get_url, get_datetime
from mtrh_dev.mtrh_dev.workflow_custom_action import send_notifications



class TenderQuotationUtils(Document):
	pass
#https://discuss.erpnext.com/t/popup-message-using-frappe-publish-realtime/37286/2
def create_tq_opening_doc(doc, state):
	rfq = doc.get("request_for_quotation")\
		or doc.get("reference_procurement_id")\
			or doc.get("external_reference_id")
				
	count_quotations = frappe.db.count('Tender Quotation Opening', {'rfq_no': rfq, 'docstatus':['!=',"2"]})
	
	count_supplier_quotations =  frappe.db.count('Supplier Quotation', {'reference_procurement_id': rfq}) or 0

	if count_quotations and count_quotations > 0:
		opening_id = frappe.db.get_value('Tender Quotation Opening', \
			{'rfq_no': rfq, 'docstatus':['!=',"2"]},'name')
		opening_doc = frappe.get_doc('Tender Quotation Opening',opening_id)
		bids_so_far = opening_doc.get("bids")
		#bids_list =[bid for bid in bids_so_far]
		bids_list =[bid.get("bid_number") for bid in bids_so_far]
		
		if doc.get("name") not in bids_list:
			number_of_bids = str(len(bids_list)+1)
			opening_doc.append('bids',{"bid_number":doc.get("name")})
			opening_doc.set('respondents', number_of_bids )
			opening_doc.flags.ignore_permissions = True
			opening_doc.run_method("set_missing_values")
			opening_doc.save()
		fetch_awarded_bidders(rfq, opening_id)
		fetch_ad_hoc_members(rfq, opening_id)
	else:
		procurement_method, opening_date = frappe.db.get_value("Request for Quotation",\
			 rfq, ['mode_of_purchase', 'transaction_date']) or ["-", "-"]
		bid =[]
		bid.append({"bid_number":doc.get("name")})
		sq_doc = frappe.get_doc({
				"doctype": "Tender Quotation Opening",
				"rfq_no": rfq,
				"procurement_method": procurement_method,
				"opening_date": opening_date,
				"respondents": count_supplier_quotations, 
				"bids":bid
			})
		bids_so_far = sq_doc.get("bids")
		number_of_bids = len([bid.get("bid_number") for bid in bids_so_far])
		sq_doc["respondents"]=number_of_bids
		sq_doc.flags.ignore_permissions = True
		sq_doc.run_method("set_missing_values")
		sq_doc.save()
		fetch_awarded_bidders(rfq, sq_doc.get("name"))
		fetch_ad_hoc_members(rfq, sq_doc.get("name"))
	return
def perform_sq_save_operations(doc , state):
	if doc.get("type") == "IsReturned Price Schedule":
		doc.external_reference_id =""
		doc.request_for_quotation = doc.get("reference_procurement_id")
		for d in doc.get("items"):
			d.request_for_quotation = doc.get("reference_procurement_id")
	else:
		return
def perform_sq_submit_operations(doc , state):
	'''
	PUR-SQTN-.YYYY.- RETURNED QUOTATIONS
	PUR-IMPREST-.YYYY.- IMPREST PURCHASE
	PUR-PROFINV-.YYYY.- PROFORMA INVOICES
	'''
	
	document_type = doc.get("type")
	#frappe.throw("document_type")
	if (document_type and (document_type =="IsReturned Price Schedule"\
		or document_type =="IsReturned Price Schedule (External)")):#NEEDS OPENING AND PRELIMIANRY EVALUATION BEFORE ITEM AWARD
		create_tq_opening_doc(doc, "Submitted")

	elif (document_type and document_type =="IsProforma Invoice"):#GO STRAIGHT TO ITEM PURCHASE EVALUATION/AWARD
		create_tqa(doc, document_type)
	elif (document_type and document_type =="IsImprest Purchase"):#GO STRAIGHT TO ITEM PURCHASE EVALUATION/AWARD
		create_tqa(doc, document_type)
	else:
		return
	
def create_tqa(doc, document_type):
	document_type = doc.get("type")
	#frappe.msgprint("Document Type: {0} - {1} - {2}".format(document_type, doc.get("rfq_no"), doc.get("reference_procurement_id")))
	rfq_in_question =  doc.get("external_reference_id")
	if (document_type and (document_type =="IsReturned Price Schedule" or document_type =="IsReturned Price Schedule (External)")):
		rfq_in_question =  doc.get("reference_procurement_id")
	mode_of_purchase = frappe.db.get_value("Request for Quotation",rfq_in_question,'mode_of_purchase')\
		or frappe.db.get_value("Tender Quotation Opening",{'rfq_no': rfq_in_question, 'docstatus':['!=',"2"]},\
			'procurement_method')

	if not frappe.db.exists("Tender Number",rfq_in_question):
		create_tender_number(rfq_in_question)
	for d in doc.get("items"):							
		count = frappe.db.count('Tender Quotation Award', \
			{'reference_number':rfq_in_question,'item_code':d.get("item_code")})
		if count < 1:
			sq_doc = frappe.get_doc({
				"doctype": "Tender Quotation Award",
				"item_code": d.get('item_code'),
				"item_name": d.get("item_name"),
				"reference_number": rfq_in_question,
				"procurement_method": mode_of_purchase	
			})
			sq_doc.append('suppliers', {
				"supplier_name": doc.get('supplier'),
				"item_uom": d.get('stock_uom'),
				"unit_price": d.get('rate'),	
			})
			sq_doc.flags.ignore_permissions = True
			sq_doc.run_method("set_missing_values")
			sq_doc.save()
		else:
			award_no = frappe.db.get_value("Tender Quotation Award",\
				{'reference_number':rfq_in_question,'item_code':d.get("item_code")}\
					,'name')
			tqa_doc = frappe.get_doc("Tender Quotation Award", award_no)
			tqa_doc.append('suppliers', {
				"supplier_name": doc.get('supplier'),
				"item_uom": d.get('stock_uom'),
				"unit_price": d.get('rate'),
				"awarded_bidder": False		
			}) 
			tqa_doc.flags.ignore_permissions = True
			tqa_doc.run_method("set_missing_values")
			tqa_doc.save()

def create_tender_number(rfq):
	sq_doc = frappe.get_doc({
			"doctype": "Tender Number",
			"tender_number":rfq
		})
	sq_doc.flags.ignore_permissions = True
	sq_doc.run_method("set_missing_values")
	sq_doc.save()
def perform_tqo_save_operations(doc, state):
	'''Generate passwords if need be and alert members appropriately.'''
	ad_hoc_members = doc.get("adhoc_members")
	if ad_hoc_members:
		update_empty_passwords(doc)				
		send_opening_passwords_alert(doc)
def send_opening_passwords_alert(doc):
	doc = update_empty_passwords(doc)
	ad_hoc_members = [x for x in doc.get("adhoc_members") if x.get("logged_in")!="1"] #only members who 
	#have not logged in
	#(recipients, message, subject, doctype,docname):
	list(map(lambda x: send_notifications([x.get("user_mail")], "You are reminded to use this password {0} \
		to open supplier quotations for {1} ".format(x.get("user_password"),doc.get("name")),\
			"Reminder: Ad Hoc Committee Password",\
				doc.get("doctype"),doc.get("name")), ad_hoc_members))
@frappe.whitelist()
def send_opening_password_to_user(user,docname):
	doc = frappe.get_doc("Tender Quotation Opening", docname)
	member_email = [user]
	member_passwords = [x.get("user_password") for x in doc.get("adhoc_members") if x.get("user_mail")==user]
	if not member_passwords:	
		doc = update_empty_passwords(doc)
		member_passwords = [x.get("user_password") for x in doc.get("adhoc_members") if x.get("user_mail")==user]	

	send_notifications(member_email, "You are reminded to use this password {0} \
		to open supplier quotations for {1} ".format(member_passwords[0] , doc.get("name")),\
			"Reminder: Ad Hoc Committee Password - {0}".format(docname),\
				doc.get("doctype"),doc.get("name"))
	frappe.response["message"]=member_passwords
	return
@frappe.whitelist()
def update_empty_passwords_shorthand(docname):
	doc = frappe.get_doc("Tender Quotation Opening", docname)
	doc = update_empty_passwords(doc)
	return
def update_empty_passwords(doc):
	import random
	import string
	docname = doc.get("name")
	ad_hoc_members = doc.get("adhoc_members")
	#Get empty password fields
	empty_passwords = [x.get("user_mail")\
		for x in ad_hoc_members if not x.get("user_password")]
	#Update the password fields
	
	letters = string.ascii_lowercase
	for n in empty_passwords:
		randompwd =''.join(random.choice(letters) for i in range(8)) 
		frappe.db.sql(f"""UPDATE `tabRequest For Quotation Adhoc Committee`\
			SET user_password = '{randompwd}'\
				 WHERE parent ='{docname}' AND user_mail = '{n}'""")
	
	doc.flags.ignore_permissions = True
	doc.notify_update()
	return doc
def return_unopened_passwords(doc):
	unopened_passwords = [x.get("employee_name") for x in doc.get("adhoc_members") if x.get("logged_in")!=True]
	return unopened_passwords
def perform_tqo_submit_operations(doc, state):
	unopened_passwords = return_unopened_passwords(doc)
	#frappe.throw(formatted_string)
	if len(unopened_passwords) > 1:
		formatted_string = ', '.join(unopened_passwords)
		frappe.throw(f"Sorry, the following have not digitally\
			 signed this document and as such it cannot be submitted {formatted_string}")
		return
	if doc.get("opening_date") and doc.get("time_of_opening") and\
		 doc.get("opening_report") and doc.get("procurement_method")!="-":
		bids_so_far = doc.get("bids")
		bids_list =[bid.get("bid_number") for bid in bids_so_far]
		count =0
		for bid in bids_list:
			if doc.get("recommendation")=="Proceed With Evaluation":
				sq_doq = frappe.get_doc("Supplier Quotation", bid)
				create_tqa(sq_doq, "")
				count+= 1
		frappe.msgprint("{0} bids opened successfully".format(count),"Bids opened")
	else:
		frappe.throw("Sorry,You cannot proceed without the Opening minutes, all e-signatures\
			 and appropriate procurement method, opening date and time")
	return
@frappe.whitelist()
def fetch_awarded_bidders(reference, opening_no):
	tqo_doc = frappe.get_doc("Tender Quotation Opening",opening_no)
	rfq_doc = frappe.get_doc("Request for Quotation",reference)
	rfq_doc.flags.ignore_permissions = True
	tqo_doc.flags.ignore_permissions = True
	invited_supplier_dict = rfq_doc.get("suppliers")
	tqo_dict = tqo_doc.get("invited_bidders")

	rfq = [row.supplier for row in invited_supplier_dict]
	tqo =[row.supplier_name for row in tqo_dict]

	filtered_list = [x for x in rfq if x not in tqo] #avoid duplicates
	
	payload =  list(map(lambda x: tqo_doc.append('invited_bidders',{"supplier_name": x}), filtered_list))
	tqo_doc.save()
	frappe.response["bidders"] = payload
	
	return
@frappe.whitelist()
def fetch_ad_hoc_members(reference, opening_no):
	most_recent_tqo = frappe.db.sql('''SELECT name, rfq_no\
		 FROM `tabTender Quotation Opening`\
			  WHERE docstatus = 1\
				  AND name !=%s\
					  ORDER BY creation DESC\
					    LIMIT 1''',(opening_no))[0][0]
	tqo_doc = frappe.get_doc("Tender Quotation Opening",most_recent_tqo)

	ad_hoc_members = tqo_doc.get("adhoc_members")

	fields =["user","employee_name","user_mail"]

	this_doc = frappe.get_doc("Tender Quotation Opening",opening_no)
	payload ={}
	for j in ad_hoc_members:
		list(map(lambda x: payload.update({x : j.get(x)}), fields))
		this_doc.append('adhoc_members',payload.copy())
		payload.clear()
	#this_doc.append('adhoc_members', [payload])
	this_doc.save()
	frappe.response["thedoc"]=this_doc
	return
@frappe.whitelist()
def flag_opening_password_as_entered(document_name):
	userid = frappe.session.user
	frappe.db.sql("""UPDATE `tabRequest For Quotation Adhoc Committee`\
		SET logged_in = 1\
			WHERE parent ='{0}' AND user_mail ='{1}' """.format(document_name, userid))
	return
def retender_quotation_process(doc):
	'''
	This routes a non-responsive document to be retendered/refloated a-fresh 
	when legal requirements were not met but the items need to be procured anyway.
	It is executed on submit of a TQO - Opening
	'''
	if doc.get("recommendation")=="Retender Entire Process":
		rfq = doc.get("rfq")
		rfq_doq = frappe.get_doc("Request for Quotation", rfq)
		items = rfq_doc.get("items")
		material_request_in_question = rfq_doq.get("")[0].material_request 
	