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
from datetime import date, timedelta
from frappe.core.doctype.communication.email import make
from mtrh_dev.mtrh_dev.workflow_custom_action import send_tqe_action_email
STANDARD_USERS = ("Guest", "Administrator")
from frappe.utils import nowdate, getdate, add_days, add_years, cstr, get_url,get_fullname, get_datetime, flt, get_date_str, format_datetime, fmt_money, money_in_words, get_url
from mtrh_dev.mtrh_dev.workflow_custom_action import send_notifications
from frappe.model.workflow import get_workflow_name, get_workflow_state_field
from mtrh_dev.mtrh_dev.utilities import get_doc_workflow_state,get_link_to_form_new_tab,get_attachment_urls


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
		sq_doc.respondents=number_of_bids
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
	#doc.flags.ignore_permissions =True
	#doc.save()
	#doc.submit()
@frappe.whitelist()
def perform_sq_submit_operations_cron():
	"""This code automatically submits."""
	unsubmitted_sqs = f"""SELECT name FROM `tabSupplier Quotation` WHERE docstatus = "0" and status = 'Draft' ;"""
	unsubmitted_quotes = frappe.db.sql(unsubmitted_sqs, as_dict=True)
	if unsubmitted_quotes:
		documents = [frappe.get_doc("Supplier Quotation", x.get("name")) for x in unsubmitted_quotes]
		list(map(lambda x: x.submit(), documents))
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
	
def create_tqa(doc, document_type, item_filter = None):
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
			{'reference_number':rfq_in_question,"docstatus":0, 'item_code':d.get("item_code")})
		if count < 1:
			sq_doc = frappe.get_doc({
				"doctype": "Tender Quotation Award",
				"item_code": d.get('item_code'),
				"item_name": d.get("item_name"),
				"reference_number": rfq_in_question,
				"procurement_method": mode_of_purchase,	
				"is_internal": True
			})
			sq_doc.append('suppliers', {

				"supplier_name": doc.get('supplier'),
				"item_uom": d.get('stock_uom'),
				"unit_price": d.get('rate'),
				"quantity": d.get('qty'),
				"amount":d.get('amount')
			})
			sq_doc.flags.ignore_permissions = True
			sq_doc.run_method("set_missing_values")
			sq_doc.save()
		else:
			award_no = frappe.db.get_value("Tender Quotation Award",\
				{'reference_number':rfq_in_question,"docstatus":0,'item_code':d.get("item_code")}\
					,'name')
			if award_no:
				tqa_doc = frappe.get_doc("Tender Quotation Award", award_no)
				tqa_doc.append('suppliers', {
					"supplier_name": doc.get('supplier'),
					"item_uom": d.get('stock_uom'),
					"unit_price": d.get('rate'),
					"quantity": d.get('qty'),
					"amount": d.get('amount'),
					"awarded_bidder": False		
				}) 
				tqa_doc.flags.ignore_permissions = True
				tqa_doc.run_method("set_missing_values")
				tqa_doc.save()
	return
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
	logged_in = [x for x in ad_hoc_members if x.logged_in ==True]
	if (len(logged_in) == len(ad_hoc_members)):
		doc.status="Opened"
		#doc.save()
		#doc.notify_update()				
		#send_opening_passwords_alert(doc)
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
	to_return =""
	#member_email = [user]
	for m in doc.get("adhoc_members"):
		username = m.get("user")
		mail = m.get("user_mail")
		if mail == user:
			to_return = username 
		frappe.db.sql(f"""UPDATE `tabRequest For Quotation Adhoc Committee` \
					SET user_password = '{username}'\
						WHERE parent ='{docname}' AND user_mail = '{mail}'""")
				
	'''member_passwords = [x.get("user_password") for x in doc.get("adhoc_members") if x.get("user_mail")==user]
	if not member_passwords:	
		doc = update_empty_passwords(doc)
		member_passwords = [x.get("user_password") for x in doc.get("adhoc_members") if x.get("user_mail")==user]	'''

	'''send_notifications(member_email, "You are reminded to use this password {0} \
		to open supplier quotations for {1} ".format(member_passwords[0] , doc.get("name")),\
			"Reminder: Ad Hoc Committee Password - {0}".format(docname),\
				doc.get("doctype"),doc.get("name"))'''
	
	frappe.response["message"]=to_return
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
	#empty_passwords = [x.get("user_mail")\
	#	for x in ad_hoc_members if not x.get("user_password")]
	#Update the password fields
	for m in ad_hoc_members:
		user = m.get("user")
		mail = m.get("user_mail")
		frappe.db.sql(f"""UPDATE `tabRequest For Quotation Adhoc Committee` \
				SET user_password = '{user}'\
					WHERE parent ='{docname}' AND user_mail = '{mail}'""")
	#letters = string.ascii_lowercase
	'''for n in empty_passwords:
		#randompwd =''.join(random.choice(letters) for i in range(8)) 
		randompwd = n.get("user")#frappe.db.get_value("Employee", {"user_id" : n.get("user")},"name")
		frappe.db.sql(f"""UPDATE \
			SET user_password = '{randompwd}'\
				 WHERE parent ='{docname}' AND user_mail = '{n}'""")'''
	
	doc = frappe.get_doc("Tender Quotation Opening", docname)
	#doc.flags.ignore_permissions = True
	#doc.save()
	doc.notify_update()
	return doc
def return_unopened_passwords(doc):
	unopened_passwords = [x.get("employee_name") for x in doc.get("adhoc_members") if x.get("logged_in")!=True]
	return unopened_passwords
def perform_tqo_submit_operations_cron():
	unposted_tqas =frappe.db.sql(f"""SELECT name FROM `tabTender Quotation Opening`\
		 WHERE docstatus = 1 and\
		 opening_status ='Sealed' """,as_dict=True)
	if unposted_tqas:
		documents =[frappe.get_doc("Tender Quotation Opening", x.get("name"))\
			 for x in unposted_tqas]
		list(map(lambda x: create_schedules(x), documents))
def create_schedules(doc): #CONTEXT Tender Quotation Opening Document

	doc.db_set('opening_status', "Opened")
	doc.db_set('status', "Opened")
	docname = doc.get("name")
	add_bidding_schedule(docname)
	return
@frappe.whitelist()
def add_bidding_schedule(docname):
	if not frappe.db.exists({'doctype': 'Procurement Professional Opinion',"reference_number": docname}):
		document = frappe.get_doc("Tender Quotation Opening", docname)
		create_bidding_schedule(document)
	else:
		frappe.throw("Sorry, there is an existing award schedule in progress")
def get_material_requests_purpose(material_reqs):
	reason ="<h2>Purpose of Request(s)</h2>"
	if len(material_reqs)>0:
		for mr in material_reqs:
			document = frappe.get_doc("Material Request", mr)
			purpose = document.get("reason_for_this_request") or "unspecified"
			mr_link = get_link_to_form_new_tab("Material Request", mr)
			requester = document.get("requester") or get_fullname(document.get("owner"))
			reason+=f"<h3>{mr_link}:</h3> <p>Reason from User Request: {purpose} - <b>User: {requester}</b></p>"
	return reason
def create_bidding_schedule(doc):
	try:
		bids_so_far = doc.get("bids")
		respondents = len(bids_so_far)
		bidders_invited = len(doc.get("invited_bidders"))
		if bids_so_far:
			bid_numbers = [bid.get("bid_number") for bid in bids_so_far]
			rfq = frappe.get_doc("Request for Quotation", doc.get("rfq_no"))
			material_reqs =[x.get("material_request") for x in rfq.get("items") if x.get("material_request")]
			unique_mrs = list(dict.fromkeys(material_reqs))

			material_request_reason = get_material_requests_purpose(unique_mrs) or "-"
			bid_doc = frappe.get_doc({
				"doctype":"Procurement Professional Opinion",
				"reference_number":doc.get("name"),
				"request_for_quotation": rfq.get("name"),
				"purpose_of_request": material_request_reason,
				"rfq_approval": rfq.get("modified"),
				"number_of_rfqs_issued":bidders_invited,
				"number_of_rfqs_received":respondents
			})	
			#frappe.throw(bid_doc.doctype)
			bid_doc = append_bid_schedule_items(bid_numbers , bid_doc)
			
			votebook_details = get_votebook_details(rfq.get("buyer_section"))
			bid_doc.set("vote_balance", votebook_details.get("balance"))
			bid_doc.set("votebook_information", votebook_details.get("account"))
			bid_doc.flags.ignore_permissions = True
			bid_doc.run_method("set_missing_values")
			bid_doc.save()
			docname2 = bid_doc.get("name")
			frappe.msgprint(f"Bid Schedule {docname2} has been created for your professional opinion")
	except Exception as e:
		frappe.throw(f"The transaction could not complete because {e}")
def get_votebook_details(item_group):
	from mtrh_dev.mtrh_dev.utilities import return_budget_all_dict
	item_defaults = frappe.db.get_all("Item Default", filters = {"parent": item_group}, fields = {"expense_account"})
	if(item_defaults):
		account = item_defaults[0].get("expense_account")
		balance = return_budget_all_dict(account).get("t_balance")
	else:
		account = "No Vote Assigned"
		balance = 0.0
	toreturn = {"account": account, "balance": balance}
	return toreturn 
@frappe.whitelist()
def publish_template_on_bid_schedule(bid_schedule_docname, template_name):
	doc = frappe.get_doc("Procurement Professional Opinion", bid_schedule_docname)
	template = frappe.get_doc("Document Template", template_name)
	opening_doc = frappe.get_doc("Tender Quotation Opening", doc.get("reference_number"))
	procuring_entity = frappe.defaults.get_user_default("Company")
	quotation_no = doc.get("request_for_quotation")
	date_invite = format_datetime(get_date_str(doc.get("rfq_approval")), "MMMM dd, yyyy")
	date_opened = format_datetime(get_date_str(doc.get("creation")), "MMMM dd, yyyy")
	adhoc_members = "<h4>Members of Quotation Opening Committee</h4><table style='width:100%;border:1px;padding: 0;margin: 0;border-collapse: collapse;border-spacing:0;'><tr><td>Name</td><td>Designation</td><td>Position</td></tr>"
	opening_members = "<h4>Members of the Technical Evaluation Committee</h4><table style='width:100%;border:1px;padding: 0;margin: 0;border-collapse: collapse;border-spacing:0;'><tr><td>Name</td><td>Designation</td><td>Position</td></tr>"
	all_members = opening_doc.get("adhoc_members")
	the_members = ""
	for member in all_members:
		member_name = member.get("employee_name")
		the_members += f"<tr><td>{member_name}</td><td>-</td><td>-</td></tr>"
	the_members += "</table>"
	adhoc_members+=the_members
	opening_members+=the_members
	items = doc.get("bidding_schedule")
	first_item_code = items[0].get("item_code")
	departmentqry = frappe.db.sql(f"""SELECT department FROM `tabMaterial Request`\
			WHERE name = (SELECT material_request FROM `tabRequest for Quotation Item` WHERE \
				parent ='{quotation_no}' and item_code = '{first_item_code}' ) """, as_dict=True) 
	department = departmentqry[0].get("department")
	awarded_table = doc.get("award_schedule")
	awarded_bidder = "Awarded Bidder"
	if awarded_table:
		awarded_bidder = awarded_table[0].get("bidder")
	rfq_approval_date = format_datetime(get_date_str(doc.get("rfq_approval")), "MMMM dd, yyyy")
	opening_date = format_datetime(get_date_str(opening_doc.get("opening_date")), "MMMM dd, yyyy")
	budget_amount = fmt_money(doc.get("vote_balance"))
	vote_name = doc.get("votebook_information")
	item_name = "Item Name"
	if items:
		item_name = items[0].get("item_name")
	cummulative_sum = fmt_money(doc.get("procurement_value"))
	registered_bidders_num = len(opening_doc.get("invited_bidders"))
	registered_bidders_words = money_in_words(registered_bidders_num).replace('KES ', '').replace(' only.', '')
	registered_bidders = f"{registered_bidders_words} ({registered_bidders_num})"
	no_of_bidders_num = opening_doc.get("respondents")
	no_of_bidders_words = money_in_words(no_of_bidders_num).replace('KES ', '').replace(' only.', '')
	no_of_bidders = f"{no_of_bidders_words} ({no_of_bidders_num})"

	#SPECIAL VARIABLES
	tabspace = "<span style='display:inline-block; width: 150px;'></span>"
	text = template.get("part_a")
	text2 = eval(f"f'{text}'")
	return text2
def append_bid_schedule_items(bid_numbers , bid_doc):
	#
	for bid in bid_numbers:
		#frappe.msgprint(bid)
		sq_doc = frappe.get_doc("Supplier Quotation", bid)
		supplier, supplier_items = None, None
		supplier_items = sq_doc.get("items")
		supplier = sq_doc.get("supplier")
		supplier_quotation = sq_doc.get("name")
		itemcount = len(supplier_items)
		frappe.response["items"] = itemcount
		#return
		#child = frappe.new_doc("Procurement Professional Opinion Item")
		for d in supplier_items:
			bid_doc.append("bidding_schedule",{
				"item_code": d.get("item_code"),
				"item_name": d.get("item_name"),
				"description": d.get("description"),
				"uom": d.get("uom"),
				"stock_uom": d.get("stock_uom"),
				"supplier_quotation": supplier_quotation,
				"stock_qty": d.get("stock_qty"),
				"brand": d.get("brand"),
				"bidder": supplier,
				"conversion_factor": d.get('conversion_factor'),
				"rate": d.get('rate'),
				"qty": d.get('qty'),
				"amount": d.get('amount'),
				"parent": bid_doc.get("name")
			})
			'''child.update({
				"item_code": d.get("item_code"),
				"item_name": d.get("item_name"),
				"description": d.get("description"),
				"uom": d.get("uom"),
				"stock_uom": d.get("stock_uom"),
				"supplier_quotation": supplier_quotation,
				"stock_qty": d.get("stock_qty"),
				"brand": d.get("brand"),
				"bidder": supplier,
				"conversion_factor": d.get('conversion_factor'),
				"rate": d.get('rate'),
				"qty": d.get('qty'),
				"amount": d.get('amount'),
				"parent": bid_doc.get("name")
			})'''
	#bid_doc.append("bidding_schedule",child)
	return bid_doc
def perform_bid_schedule_save_operations(doc , state):
	to_award = validate_award_schedule(doc)
	validate_refloating(doc)
	validate_renegotiation(doc)
	total = 0.0
	for d in to_award:
		doc.append("award_schedule",{
			"item_code": d.get("item_code"),
			"item_name": d.get("item_name"),
			"rate": d.get('rate'),
			"qty": d.get('qty'),
			"uom": d.get("uom"),
			"bidder": d.get("bidder"),
			"amount": d.get('amount'),
			"sample_provided": d.get("sample_provided"),
			"brand": d.get("brand"),
			"award_type": d.get("award_type"),
			"supplier_quotation": d.get("supplier_quotation"),
			"supplier_part_no": d.get("supplier_part_no")
		})
	
	for item in doc.get("award_schedule"):
		if item.get("award_type") =="Awarded":
			total+=flt(item.get('amount'))
	doc.set("procurement_value", total)
def validate_refloating(doc):
	items = doc.get("bidding_schedule")
	unique_items =[x.get("item_code") for x in items  if x.get("award_type")=="Re-Tender or Refloat Quotations"]
	for d in items:
		if d.get("item_code") in unique_items:
			d.set("award_type", "Re-Tender or Refloat Quotations")
def validate_renegotiation(doc):
	bids = int(doc.get("number_of_rfqs_received"))
	items = doc.get("bidding_schedule")
	unique_items =[x.get("item_code") for x in items  if x.get("award_type")=="Send for Renegotiation"]
	if bids > 1 and  unique_items:
		frappe.throw(_(f"Sorry you cannot select 'Send for Renegotiation' for a document with multiple bidders.\
			 Hint: You could select 'Re-Tender or Refloat Quotations' for the specific items."))
def validate_award_schedule(doc):
	items = doc.get("bidding_schedule")
	unique_items =[x.get("item_code") for x in items]
	unique_items= list(dict.fromkeys(unique_items))
	safety_status = True
	for d in unique_items:
		awarded = [x for x in items if x.get("item_code")==d and x.get("award_type")=="Awarded"]
		if len(awarded) > 1:
			safety_status = False
	if not safety_status:
		frappe.throw("<p>Sorry, please check your entries as some items have been awarded more than once.</p> <p>Hint: It is advised to select as an alternative bidder instead of awarding two suppliers</p>")
	awarded_items = doc.get("award_schedule")
	
	unique_quotations = [x.get("supplier_quotation") for x in awarded_items]
	unique_quotations= list(dict.fromkeys(unique_quotations))
	
	unique_awarded_items = [x.get("item_code") for x in awarded_items]
	unique_awarded_items= list(dict.fromkeys(unique_awarded_items))
	the_dict =[x for x in items\
		 if (x.get("supplier_quotation") not in unique_quotations)\
			  and (x.get("item_code") not in unique_awarded_items) and (x.get("award_type"))]
	return the_dict
def professional_opinion_to_award_cron():
	from datetime import datetime 
	last_approved_opinions = frappe.db.get_all('Procurement Professional Opinion',
		filters={
			#'modified': [">", datetime.now() - timedelta(hours=10)],
			'docstatus': 1,
			'evaluated' : 0
		},
		fields=['name'],
		as_list=False
	)
	for d in last_approved_opinions:
		doc = frappe.get_doc("Procurement Professional Opinion", d.get("name"))
		perform_bid_schedule_submit_operations(doc, "Approved")
@frappe.whitelist()
def re_evaluate_submitted_professional_opinion(docname):
	doc = frappe.get_doc("Procurement Professional Opinion", docname)
	perform_bid_schedule_submit_operations(doc, "Approved")
	#frappe.response["message"] = doc
def get_supplier_quotation_from_tqo(supplier,opening_doc):
	opening_doc = frappe.get_doc("Tender Quotation Opening", opening_doc)
	sq_to_return =""
	for d in opening_doc.get("bids"):
		interim_sq = None
		sq = d.get("bid_number")
		interim_sq = frappe.db.get_value("Supplier Quotation",sq,["name","supplier"],as_dict=True) 
		if interim_sq.get("supplier") ==supplier:
			sq_to_return = interim_sq.name
	return sq_to_return
def perform_bid_schedule_submit_operations(doc , state):
	try:
		award_schedule= doc.get("award_schedule")
		awards2submit =[]
		docname = doc.get("name")
		for d in award_schedule:
			supplier_quotation_doc = None
			bidder = d.get("bidder")
			supplier_quotation = d.get("supplier_quotation") or \
				 get_supplier_quotation_from_tqo(d.get("bidder"), doc.get("reference_number"))
			#######
			frappe.db.sql(f"UPDATE `tabBid Price Schedule Item` SET supplier_quotation ='{supplier_quotation}'\
				WHERE parent ='{docname}' and bidder ='{bidder}'")
			frappe.db.sql(f"UPDATE `tabAward Price Schedule Item` SET supplier_quotation ='{supplier_quotation}'\
				WHERE parent ='{docname}' and bidder ='{bidder}'")
			#######
			supplier_quotation_doc = frappe.get_doc("Supplier Quotation",supplier_quotation)
			document_type = supplier_quotation_doc.get("type")
			#supplier = d.get("bidder")
			rfq_in_question =  supplier_quotation_doc.get("external_reference_id")
			if (document_type and (document_type =="IsReturned Price Schedule" or document_type =="IsReturned Price Schedule (External)")):
				rfq_in_question =  supplier_quotation_doc.get("reference_procurement_id")
			mode_of_purchase = frappe.db.get_value("Request for Quotation",rfq_in_question,'mode_of_purchase')\
				or frappe.db.get_value("Tender Quotation Opening",{'rfq_no': rfq_in_question, 'docstatus':['!=',"2"]},\
					'procurement_method')
			item_code =d.get("item_code")
			
			department = frappe.db.sql(f"""SELECT department FROM `tabMaterial Request`\
				WHERE name = (SELECT material_request FROM `tabRequest for Quotation Item` WHERE \
					parent ='{rfq_in_question}' and item_code = '{item_code}' ) """, as_dict=True) 
			thedepartment = department[0].get("department")

			frappe.msgprint(f"Consumer department is {thedepartment}")
			if not frappe.db.exists("Tender Number",rfq_in_question):
				create_tender_number(rfq_in_question)

			count = frappe.db.count('Tender Quotation Award', \
				{'reference_number':rfq_in_question,"docstatus":0,'item_code':d.get("item_code")})
			award_exists = frappe.db.exists({"doctype":"Tender Quotation Award",\
				 "item_code":item_code,"reference_number":rfq_in_question})
			if not award_exists:
				sq_doc = frappe.get_doc({
					"doctype": "Tender Quotation Award",
					"item_code": d.get('item_code'),
					"item_name": d.get("item_name"),
					"reference_number": rfq_in_question,
					"procurement_method": mode_of_purchase,	
					"is_internal": True,
					"department": thedepartment
				})
				sq_doc.append('suppliers', {
					"supplier_name": d.get('bidder'),
					"item_uom": d.get('uom'),
					"unit_price": d.get('rate'),
					"quantity": d.get('qty'),
					"amount":d.get('amount'),
					"supplier_quotation": d.get("supplier_quotation"),
					"awarded_bidder": True	#if d.get("award_type") == Awarded else False
				})
				#if department:
				#	sq_doc.set("department", department[0].get("department"))
				sq_doc.flags.ignore_permissions = True
				sq_doc.run_method("set_missing_values")
				sq_doc.insert()
				awards2submit.append(sq_doc.get("name"))
			else:
				award_no = frappe.db.get_value("Tender Quotation Award",\
					{'reference_number':rfq_in_question,"docstatus":0,'item_code':d.get("item_code")}\
						,'name')
				if award_no:
					tqa_doc = frappe.get_doc("Tender Quotation Award", award_no)
					tqa_doc.append('suppliers', {
						"supplier_name": d.get('bidder'),
						"item_uom": d.get('uom'),
						"unit_price": d.get('rate'),
						"quantity": d.get('qty'),
						"amount": d.get('amount'),
						"awarded_bidder": False,
						"supplier_quotation": d.get("supplier_quotation")
					}) 
					tqa_doc.flags.ignore_permissions = True
					tqa_doc.run_method("set_missing_values")
					tqa_doc.save()
					if  tqa_doc.get("name") not in awards2submit:
						awards2submit.append(tqa_doc.get("name"))
		if awards2submit:				
			documents =[frappe.get_doc("Tender Quotation Award", x) for x in awards2submit]
			list(map(lambda x: x.submit(), documents))
		#Now Raise POs 
		items = doc.get("award_schedule")
		to_refloat = [x.get("item_code") for x in items  if x.get("award_type")=="Re-Tender or Refloat Quotations"]
		to_renegotiate = [x.get("item_code") for x in items  if x.get("award_type")=="Send for Renegotiation"]
		
		to_refloat = list(dict.fromkeys(to_refloat))
		to_renegotiate = list(dict.fromkeys(to_renegotiate))
	
		new_rfq_operations(doc, to_refloat, to_renegotiate)
		raise_po_on_professional_opinion_submit(doc)
		doc.db_set("evaluated", True)
		return
	except Exception as e:
		frappe.throw(f"{e}")
def new_rfq_operations(doc , to_refloat= None, to_renegotiate= None):
	if to_renegotiate: doc.send_for_renegotiation(to_renegotiate)
	if to_refloat: doc.refloat_quotation(to_refloat)
	return
def perform_tqo_submit_operations(doc, state):
	unopened_passwords = return_unopened_passwords(doc)
	#frappe.throw(formatted_string)
	appointed_members = frappe.get_doc("Bid Evaluation Committee")
	if appointed_members.get("login_required")==True:
		if len(unopened_passwords) > 1:
			formatted_string = ', '.join(unopened_passwords)
			frappe.throw(f"Sorry, the following have not digitally\
				signed this document and as such it cannot be submitted {formatted_string}")
			return
	if doc.get("opening_date") and doc.get("time_of_opening")\
		 and doc.get("procurement_method")!="-":
		bids_so_far = doc.get("bids")
		members_so_far = doc.get("adhoc_members")
		adhoc = len(members_so_far)
		count = len(bids_so_far)
		if count < 1 or adhoc < 1:
			frappe.throw("Sorry you cannot proceed without entered bids or adhoc members")
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
	total_invited = len(filtered_list)
	tqo_doc.set("bidders_invited", total_invited)
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
	these_members =[x.get("user_mail") for x in this_doc.get("adhoc_members")]
	payload ={}
	for j in ad_hoc_members:
		if these_members and j.get("user_mail") not in these_members:
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
		rfq_doc = frappe.get_doc("Request for Quotation", rfq)
		items = rfq_doc.get("items")
		material_request_in_question = rfq_doc.get("")[0].material_request 
def update_respondents():
	opened_docs =frappe.db.sql("SELECT name FROM `tabTender Quotation Opening`\
		 WHERE opening_status in ('Opened', 'Sealed')", as_dict=True)
	documents =[frappe.get_doc("Tender Quotation Opening", x.get("name")) for x in opened_docs]

	for d in documents:
		reference = d.get("name")
		invited_bidders = len(d.get("invited_bidders"))
		bids = len(d.get("bids"))
		percent_response = (bids/invited_bidders)*100
		frappe.db.sql(f"""UPDATE `tabBid Price Schedule` SET number_of_rfqs_issued ={invited_bidders}, \
			number_of_rfqs_received ={bids} WHERE reference_number='{reference}'""")
		frappe.db.sql(f"""UPDATE `tabTender Quotation Opening Bid` SET bidders_invited ={invited_bidders}, \
			respondents ={bids}, response ={percent_response} WHERE name='{reference}'""")
def alert_opening_members():
	pending  = frappe.db.sql("SELECT name FROM `tabTender Quotation Opening`\
		 WHERE docstatus = 0", as_dict=True)
	
	documents =[frappe.get_doc("Tender Quotation Opening", x.get("name")) for x in pending]

	for d in documents:
		mails = [x.get("employee_name") for x in d.get("adhoc_members")]
		t = d.get("modified")
		list(map(lambda x: d.add_comment('Shared', text =f"{x} Digitally signed on {t}"), mails))

@frappe.whitelist()
def document_dashboard(doctype, docname):
	to_return =""
	document = frappe.get_doc(doctype, docname)
	if doctype =="Procurement Professional Opinion":
		to_return ="<h3>Attachments and Linked Documents</h3>"
		opening_report = get_link_to_form_new_tab("Tender Quotation Opening", document.get("reference_number"))
		authority_to_procure = get_link_to_form_new_tab("Request for Quotation",document.get("request_for_quotation"))
		rfq = document.get("request_for_quotation")
		material_req_q = frappe.db.sql(f"SELECT distinct material_request FROM `tabRequest for Quotation Item`\
			WHERE parent ='{rfq}'", as_dict=True)
		material_request_docs =[get_link_to_form_new_tab("Material Request", x.get("material_request")) for x in material_req_q]
		
		material_rq_links = ''+', '.join("'{0}'".format(i) for i in material_request_docs)+''
		#reference_number
		to_return+= "<table border='1' width='100%' >"
		to_return += "<th>Document</th><th>Link</th>"

		to_return+= f"<tr><td>Material Requests:</td><td>{material_rq_links}</td></tr>"

		to_return+= f"<tr><td>Authority to Procure: </td><td>{authority_to_procure}</td></tr>"
		to_return+= f"<tr><td>Opening Report</td><td>{opening_report}</td></tr>"
		to_return+= "</table>"
	elif doctype == "Purchase Order":
		to_return = ""
		supplier_quotations = [x.get("supplier_quotation") for x in document.get("items") if x.get("supplier_quotation")]
		#frappe.throw(supplier_quotations)
		
		if len(supplier_quotations) > 0:
			sq_q = '('+','.join("'{0}'".format(i) for i in supplier_quotations)+')'
			quotations_q = frappe.db.sql(f"""SELECT DISTINCT request_for_quotation FROM \
				`tabSupplier Quotation` WHERE name in {sq_q}""", as_dict=True)
			rfqs_arr = [x.get("request_for_quotation") for x in quotations_q]
			rfq_q = '('+','.join("'{0}'".format(i) for i in rfqs_arr)+')'
			professional_opinion_q = frappe.db.sql(f"""SELECT name FROM `tabProcurement Professional Opinion`\
				 WHERE request_for_quotation IN {rfq_q} """,as_dict =True)
			to_return+= "<h3>Attachments and Linked Documents</h3><table border='1' width='100%' >"
			to_return += "<th>Document</th><th>Link</th>"

			rfq_links  =[get_link_to_form_new_tab("Request for Quotation", x.get("request_for_quotation")) for x in quotations_q]
			professional_opinion_links = [get_link_to_form_new_tab("Procurement Professional Opinion", x.get("name")) for x in professional_opinion_q]
			to_return+= f"<tr><td>Authority to Procure: </td><td>{rfq_links}</td></tr>"
			to_return+= f"<tr><td>Award Report:	</td><td>{professional_opinion_links}</td></tr>"
			
			to_return+= "</table>"
		else: 
			externally_generated_ids = [x.get("externally_generated_order")\
				for x in document.get("items") if x.get("externally_generated_order")]
			#frappe.throw(externally_generated_ids)
			if isinstance(externally_generated_ids, list) and externally_generated_ids:
				externally_generated_ids = list(dict.fromkeys(externally_generated_ids))
				attachments = get_attachment_urls(externally_generated_ids)
				to_return+= "<h3>Attachments and Linked Documents</h3><table border='1' width='100%' >"
				to_return += "<th>Document</th><th>Link</th>"
				to_return+= f"<tr><td>Scanned (Externally generated order) Document Attachments:	</td><td>{attachments}</td></tr>"
				to_return+= "</table>"
	elif doctype == "Request for Quotation":
		to_return ="<h3>Attachments and Linked Documents</h3>"
		rfq = document.get("name")
		
		#GET PROFESSIONAL OPIONIONS
		professional_opinion_q = frappe.db.sql(f"""SELECT name FROM `tabProcurement Professional Opinion`\
				 WHERE request_for_quotation = '{rfq}' """,as_dict =True)
		professional_opinion_links = [get_link_to_form_new_tab("Procurement Professional Opinion", x.get("name")) for x in professional_opinion_q] or "QUOTATIONS NOT OPENED YET!"
		
		#GET LINKED MATERIAL REQUESTS
		material_req_q = frappe.db.sql(f"SELECT distinct material_request FROM `tabRequest for Quotation Item`\
			WHERE parent ='{rfq}'", as_dict=True)
		material_request_docs =[get_link_to_form_new_tab("Material Request", x.get("material_request")) for x in material_req_q]
		material_rq_links = ''+', '.join("'{0}'".format(i) for i in material_request_docs)+''

		#GET QUOTATIONS OPENING DOCUMENT AND INFO SUCH AS NUMBER OF INVITED AND SUBMITTED QUOTES
		opening_document = frappe.db.sql(f"SELECT `name`, `bidders_invited`, `respondents`, `response`, `opening_status` FROM `tabTender Quotation Opening`\
			WHERE rfq_no ='{rfq}'", as_dict=True)
		opening_doc_link =[get_link_to_form_new_tab("Tender Quotation Opening", x.get("name")) for x in opening_document] or "NO SUBMISSIONS FROM VENDORS/SUPPLIERS"
		opening_doc_info = ""
		if opening_document and opening_document[0]:
			no_responded = opening_document[0].get("respondents")
			response_rate = int(opening_document[0].get("response"))
			no_invited = opening_document[0].get("bidders_invited")
			open_status = opening_document[0].get("opening_status")
			opening_doc_info = f" - Vendors Invited: <b>{no_invited}</b> | No. Responded: <b>{no_responded}</b> | Response Rate: <b>{response_rate}%</b> - <b>{open_status}</b>"

		to_return+= "<table border='1' width='100%' >"
		to_return += "<th>Document</th><th>Link</th>"

		to_return+= f"<tr><td>Material Requests:</td><td>{material_rq_links}</td></tr>"
		to_return+= f"<tr><td>Opening Report</td><td>{opening_doc_link} {opening_doc_info} </td></tr>"
		to_return+= f"<tr><td>Procurement Professional Opinion: </td><td>{professional_opinion_links}</td></tr>"
		
		to_return+= "</table>"
	elif doctype == "Purchase Invoice":
		#LINKED PURCHASE RECEIPTS.
		all_linked_documents= []
		this_invoice_no = document.get("name")
		#purchase_receipts = frappe.db.sql(f"""SELECT `purchase_receipt` FROM `tabPurchase Invoice Item`\
		#		 WHERE name = '{this_invoice_no}';""",as_dict =True)
		purchase_receipts_a = [x.get("purchase_receipt") for x in document.get("items")]
		purchase_receipts = list(dict.fromkeys(purchase_receipts_a))
		linked_purchase_receipts = [get_link_to_form_new_tab("Purchase Receipt", x) for x in purchase_receipts]
		#LINKED INSPECTION DOCUMENTS
		purchase_receipts_arr = [x for x in purchase_receipts]
		all_linked_documents.extend(purchase_receipts_arr)
		pr_q = '('+','.join("'{0}'".format(i) for i in purchase_receipts_arr)+')'
		quality_inspection_q = frappe.db.sql(f"""SELECT name FROM `tabQuality Inspection`\
				 WHERE reference_name IN {pr_q} """,as_dict =True)
		linked_quality_inspections = [get_link_to_form_new_tab("Quality Inspection", x.get("name")) for x in quality_inspection_q]
		quality_inspection_arr =[x.get("name") for x in quality_inspection_q]
		all_linked_documents.extend(quality_inspection_arr)
		#LINKED PURCHASE ORDERS
		purchase_orders_list = [x.get("purchase_order") for x in document.get("items")]
		purchase_orders = list(dict.fromkeys(purchase_orders_list))
		linked_purchase_orders = [get_link_to_form_new_tab("Purchase Order", x) for x in purchase_orders]
		print(purchase_orders)
		linked_material_requests=[]
		#LINKED MATERIAL REQUESTS
		if purchase_orders:
			all_linked_documents.extend(purchase_orders)
			purchase_order_q_str = '('+','.join("'{0}'".format(i) for i in purchase_orders)+')'
			mrs = frappe.db.sql(f"""SELECT DISTINCT material_request\
				FROM `tabPurchase Order Item`\
					WHERE parent IN {purchase_order_q_str}""", as_dict=True)
			if isinstance(mrs, list) and mrs[0].get("material_request"):
				material_requests = [x.get("material_request") for x in mrs]
				linked_material_requests =  [get_link_to_form_new_tab("Material Request", x.get("material_request")) for x in mrs]
				all_linked_documents.extend(material_requests)
		d = get_attachment_urls(all_linked_documents)

		if not linked_material_requests: linked_material_requests =  "Check Uploaded Documents. This request was generated outside this system."
		to_return ="<h3>Attachments and Linked Documents</h3>"
		to_return+= "<table border='1' width='100%' >"
		to_return += "<th>Document</th><th>Link</th>"

		to_return+= f"<tr><td style='white-space: nowrap; font-weight: bold;'>Material Requests (PRQs):</td><td>{linked_material_requests}</td></tr>"
		to_return+= f"<tr><td style='white-space: nowrap; font-weight: bold;'>Purchase/Service Orders (LPO/LSO)</td><td>{linked_purchase_orders} </td></tr>"
		to_return+= f"<tr><td style='white-space: nowrap; font-weight: bold;'>Goods Received Notes (GRNs): </td><td>{linked_purchase_receipts}</td></tr>"
		to_return+= f"<tr><td style='white-space: nowrap; font-weight: bold;'>Inspection & Acceptance Certs: </td><td>{linked_quality_inspections}</td></tr>"
		to_return+= f"<tr><td style='white-space: nowrap; font-weight: bold;'>Uploaded Documents (External): </td><td>{d}</td></tr>"
		
		to_return+= "</table>"

	elif doctype == "Payment Request":
		#LINKS APPLY FOR PURCHASE INVOICE REFERENCE DOCUMENTS. REMEMBER TO ADD FOR THE OTHER REFERENCE TYPE DOCUMENTS.
		if document.get("reference_doctype") == "Purchase Invoice":
			#LINED PURCHASE INVOICE
			this_invoice_no = document.get("reference_name")
			this_invoice = frappe.get_doc("Purchase Invoice", this_invoice_no)
			all_linked_documents= []
			linked_purchase_invoice = get_link_to_form_new_tab("Purchase Invoice", this_invoice_no)
			
			purchase_receipts_a = [x.get("purchase_receipt") for x in this_invoice.get("items")]
			purchase_receipts = list(dict.fromkeys(purchase_receipts_a))
			linked_purchase_receipts = [get_link_to_form_new_tab("Purchase Receipt", x) for x in purchase_receipts]
			
			#LINKED INSPECTION DOCUMENTS
			purchase_receipts_arr = [x for x in purchase_receipts]
			all_linked_documents.extend(purchase_receipts_arr)
			pr_q = '('+','.join("'{0}'".format(i) for i in purchase_receipts_arr)+')'
			quality_inspection_q = frappe.db.sql(f"""SELECT name FROM `tabQuality Inspection`\
					WHERE reference_name IN {pr_q} """,as_dict =True)
			linked_quality_inspections = [get_link_to_form_new_tab("Quality Inspection", x.get("name")) for x in quality_inspection_q]
			quality_inspection_arr =[x.get("name") for x in quality_inspection_q]
			all_linked_documents.extend(quality_inspection_arr)
			
			#LINKED PURCHASE ORDERS
			purchase_orders_list = [x.get("purchase_order") for x in this_invoice.get("items")]
			purchase_orders = list(dict.fromkeys(purchase_orders_list))
			linked_purchase_orders = [get_link_to_form_new_tab("Purchase Order", x) for x in purchase_orders]
			print(purchase_orders)
			linked_material_requests=[]
			
			#LINKED MATERIAL REQUESTS
			if purchase_orders:
				all_linked_documents.extend(purchase_orders)
				purchase_order_q_str = '('+','.join("'{0}'".format(i) for i in purchase_orders)+')'
				mrs = frappe.db.sql(f"""SELECT DISTINCT material_request\
					FROM `tabPurchase Order Item`\
						WHERE parent IN {purchase_order_q_str}""", as_dict=True)
				if isinstance(mrs, list) and mrs[0].get("material_request"):
					material_requests = [x.get("material_request") for x in mrs]
					linked_material_requests =  [get_link_to_form_new_tab("Material Request", x.get("material_request")) for x in mrs]
					all_linked_documents.extend(material_requests)
			d = get_attachment_urls(all_linked_documents)

			if not linked_material_requests: linked_material_requests =  "Check Uploaded Documents. This request was generated outside this system."
			to_return ="<h3>Attachments and Linked Documents</h3>"
			to_return+= "<table border='1' width='100%' >"
			to_return += "<th>Document</th><th>Link</th>"

			to_return+= f"<tr><td style='white-space: nowrap; font-weight: bold;'>Material Requests (PRQs):</td><td>{linked_material_requests}</td></tr>"
			to_return+= f"<tr><td style='white-space: nowrap; font-weight: bold;'>Purchase/Service Orders (LPO/LSO)</td><td>{linked_purchase_orders} </td></tr>"
			to_return+= f"<tr><td style='white-space: nowrap; font-weight: bold;'>Goods Received Notes (GRNs): </td><td>{linked_purchase_receipts}</td></tr>"
			to_return+= f"<tr><td style='white-space: nowrap; font-weight: bold;'>Inspection & Acceptance Certs: </td><td>{linked_quality_inspections}</td></tr>"
			to_return+= f"<tr><td style='white-space: nowrap; font-weight: bold;'>Vendor Invoice Details: </td><td>{linked_purchase_invoice}</td></tr>"
			to_return+= f"<tr><td style='white-space: nowrap; font-weight: bold;'>Uploaded Documents (External): </td><td>{d}</td></tr>"
			
			to_return+= "</table>"
	elif doctype == "Purchase Receipt":
		to_return ="<h3>Attachments and Linked Documents</h3>"
	return to_return
def sq_item_in_po(item, sq):
	'''return frappe.db.sql(f"SELECT name FROM `tabPurchase Order Item` WHERE item_code='{item}'\
		 AND supplier_quotation='{sq}'",as_dict=True)'''
	return frappe.db.exists({'doctype': 'Purchase Order Item',"item_code": item,"supplier_quotation":sq})
def raise_po_on_professional_opinion_submit(doc):
	try:	
		rfq = frappe.get_doc("Request for Quotation", doc.get("request_for_quotation"))
		opening_doc = doc.get("reference_number")
		if "Tender" in [rfq.get("mode_of_purchase")]:
			return
		else:
			for d in doc.get("award_schedule"):	
				already_ordered =[]
				already_ordered = sq_item_in_po(d.get("item"), d.get("supplier_quotation"))
				if already_ordered:  #and already_ordered[0].get("name"):
					pass		
				else:
					if d.get("award_type") == "Awarded":
						supplier = d.get("bidder")
						sq = d.get("supplier_quotation") or \
							get_supplier_quotation_from_tqo(supplier,opening_doc)	
						if  frappe.db.exists({'doctype': 'Purchase Order',"supplier":supplier,\
							"workflow_state":"Draft"}):
							po_d =frappe.db.sql(f"SELECT name FROM `tabPurchase Order` WHERE supplier ='{supplier}'\
								and workflow_state='Draft' order by creation desc limit 1", as_dict=True)
							po = po_d[0].get("name")
							po_doc = frappe.get_doc("Purchase Order", po)
							po_doc = append_order_items(po_doc, d, rfq.get("name"), sq)
							po_doc.flags.ignore_permissions = True
							po_doc.run_method("set_missing_values")
							po_doc.save()
							po_doc.add_comment("Shared", text=f"{supplier} was awarded based on Reference {sq}")
						else:
							raise_order(d, rfq.get("name"), opening_doc)
							
	except Exception as e:
		frappe.response["Exception"] = e
		frappe.throw(f"Error in Transaction because {e}")
def raise_order(award_item_dict, rfq, opening_doc =None):
	#CONTEXT Procurement Professional Opinion
	actual_name = award_item_dict.get("bidder")
	supplier = actual_name
	request_for_quotation = rfq
	item_code = award_item_dict.get("item_code")
	item_category = frappe.db.get_value("Item",item_code,'item_group')
	doc = frappe.get_doc(
			{
				"doctype":"Purchase Order",
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
				
			}
		)
	sq = award_item_dict.get("supplier_quotation") or \
		get_supplier_quotation_from_tqo(supplier,opening_doc)	
	doc = append_order_items(doc, award_item_dict, request_for_quotation, sq)
	
	doc.flags.ignore_permissions=True
	doc.run_method("set_missing_values")
	doc.save()
	doc.add_comment("Shared", text=f"{actual_name} was awarded based on Reference {sq}")
	po = doc.get("name")
	frappe.msgprint(f"Purchase Order {po}\
		has been drafted successfully and posted in this system for further action.")
def append_order_items(po_doc, items, request_for_quotation, sq = None):
	#Reference is the Request for Quotation
	from mtrh_dev.mtrh_dev.stock_utils import get_item_default_expense_account
	item_code = items.get("item_code")
	departmentqry = frappe.db.sql(f"""SELECT department,name FROM `tabMaterial Request`\
		WHERE name = (SELECT material_request FROM `tabRequest for Quotation Item` WHERE \
			parent ='{request_for_quotation}' and item_code = '{item_code}' ) """, as_dict=True) 
	department = departmentqry[0].get("department")
	supplier_quotation = items.get("supplier_quotation") or sq
	material_request = departmentqry[0].get("name")
	doc = frappe.get_doc("Item", item_code)
	item_group = doc.get("item_group")
	default_warehouse = frappe.db.get_value("Item Default",\
		{"parent":item_code,"parenttype":"Item"},'default_warehouse') \
			or \
			frappe.db.get_value("Item Default",\
				{"parent":item_group,"parenttype":"Item Group"},'default_warehouse')
	
	qty = items.get("qty") or 1
	rate = items.get("rate")
	amount = float(qty) * float(rate)
	schedule_date = po_doc.get("items")[0].get("schedule_date") if po_doc.get("items") else add_days(nowdate(), 30)
	items_in_order = [x for x in po_doc.get("items")] or []
	if item_code not in items_in_order:
		po_doc.append("items",{
			"item_code": item_code,
			"item_name": items.get("item_name"),
			"description": items.get("description"),
			"rate": rate,
			"warehouse": default_warehouse,
			"schedule_date": schedule_date,
			"qty": qty,
			"stock_uom": items.get("uom"),
			"uom":items.get("uom"),
			"conversion_factor": 1,
			"amount": amount,
			"net_amount": amount,
			"base_rate":rate,
			"base_amount":amount,
			"base_net_rate": rate,
			"base_net_amount":amount,
			"expense_account": get_item_default_expense_account(item_code),
			"department": department,
			"supplier_quotation": supplier_quotation,
			"material_request": material_request
		})
		'''from mtrh_dev.mtrh_dev.utilities import get_votehead_balance
		vote_info = get_votehead_balance("Purchase Order", po_doc.get("name"))
		po_doc.vote_statement = vote_info'''
	return po_doc