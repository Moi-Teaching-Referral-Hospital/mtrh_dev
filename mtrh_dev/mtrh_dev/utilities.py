import frappe, json
from frappe import _
from frappe.utils.file_manager import check_max_file_size, get_content_hash, get_file_name, get_file_data_from_hash
from frappe.utils import get_files_path,cstr ,get_hook_method, call_hook_method, random_string, get_fullname, today, cint, flt
import os, base64
from six import text_type, string_types
import mimetypes
from copy import copy
from mtrh_dev.mtrh_dev.tqe_on_submit_operations import raise_po_based_on_direct_purchase
from mtrh_dev.mtrh_dev.sms_api import send_sms_alert
from frappe.core.doctype.sms_settings.sms_settings import send_sms
from frappe.model.workflow import get_workflow_name, get_workflow_state_field

from erpnext.accounts.utils import get_fiscal_year
from datetime import date, datetime
from frappe.core.doctype.user_permission.user_permission import clear_user_permissions
from frappe.core.doctype.user.user import extract_mentions
from frappe.desk.doctype.notification_log.notification_log import enqueue_create_notification, get_title, get_title_html
from frappe.utils.background_jobs import enqueue

@frappe.whitelist()
def attach_file_to_doc(filedata, doc_type, doc_name, file_name):
	if filedata:
		file_path = get_files_path(is_private = 0)
		folder = doc_name + "-" + random_string(7)
		frappe.create_folder(file_path + "/" + folder)
		#folder = get_files_path(folder, is_private = 1) #"/private/files/" + folder + "/"
		fd_json = json.loads(filedata)
		fd_list = list(fd_json["files_data"])
		for fd in fd_list:
			content_type = mimetypes.guess_type(fd["filename"])[0]
			filedoc = save_file_on_filesystem(fd["filename"], fd["dataurl"], folder= folder, content_type=content_type, is_private=0)
		#frappe.msgprint(filedoc)	
	return filedoc

def save_file_on_filesystem(fname, content, folder=None, content_type=None, is_private=0):
	fpath = write_file(content, fname, folder, is_private)
	#frappe.msgprint(_("Path: " + fpath + ", Folder: " + folder)
	#frappe.msgprint(fpath)
	if folder:
		if is_private:
			file_url = "/private/files/{0}/{1}".format(folder, fname)
		else:
			file_url = "/files/{0}/{1}".format(folder, fname)
	else:
		if is_private:
			file_url = "/private/files/{0}".format(fname)
		else:
			file_url = "/files/{0}".format(fname)
			
	return file_url
	#return {
	#	'file_name': os.path.basename(fpath),
	#	'file_url': file_url
	#}

def write_file(content, fname, folder=None, is_private=0):
	"""write file to disk with a random name (to compare)"""
	file_path = get_files_path(folder, is_private=is_private)

	# create directory (if not exists)
	frappe.create_folder(file_path)
	# write the file
	#if isinstance(content, text_type):
	#content = content.encode()
	#content = base64.b64decode(content)
	if isinstance(content, text_type):
		content = content.encode("utf-8")

	if b"," in content:
		content = content.split(b",")[1]
	content = base64.b64decode(content)
	
	with open(os.path.join(file_path.encode('utf-8'), fname.encode('utf-8')), 'wb+') as f:
		f.write(content)

	return get_files_path(folder, fname, is_private=is_private)
	
#====================================================================================================================================================
#SUPPLIER QUOTATION GENERATION
#====================================================================================================================================================

# This method is used to make supplier quotation from supplier's portal.
@frappe.whitelist()
def create_supplier_quotation(doc):
	if isinstance(doc, string_types):
		doc = json.loads(doc)
	rfq = doc.get('items')[0].get("parent")
	
	#try:
	#DELETE ANY PREVIOUSLY SUBMITTED QUOTATIONS FROM THE SAME SUPPLIER FOR THE SAME RFQ.
	this_rfq_quotes_for_supplier = frappe.db.get_all('Supplier Quotation',
		filters={
			"supplier": doc.get('supplier'),
			"reference_procurement_id": rfq
		},
		fields=['name'],
		as_list=False
	)
	quotes_to_delete =[frappe.get_doc("Supplier Quotation", x.get("name"))\
		for x in this_rfq_quotes_for_supplier if this_rfq_quotes_for_supplier]
	list(map(lambda x: x.delete(), quotes_to_delete))

	#PREPARE AND INSERT NEW QUOTATION
	sq_doc = frappe.get_doc({
		"doctype": "Supplier Quotation",
		"supplier": doc.get('supplier'),
		"type" : "IsReturned Price Schedule",
		"terms": doc.get("terms"),
		"company": doc.get("company"),
		"external_reference_id": rfq,
		"reference_procurement_id": rfq,
		#ADDED REQUEST FOR QUOTATION FIELD TO ENSURE PARENT SQ IS TIED TO AN RFQ JUST AS ITS CHILD IS:
		"request_for_quotation":rfq,
		"currency": doc.get('currency'), # or get_party_account_currency('Supplier', doc.get('supplier'), doc.get('company')),
		"buying_price_list": doc.get('buying_price_list') or frappe.db.get_value('Buying Settings', None, 'buying_price_list')
	})
	add_items(sq_doc, doc.get('supplier'), doc.get('items'))
	sq_doc.flags.ignore_permissions = True
	sq_doc.run_method("set_missing_values")
	ref = sq_doc.get("external_reference_id")
	#return frappe.msgprint(_(f"This is to be inserted: {ref}"))
	sq_doc.insert()
	raise_po_based_on_direct_purchase(rfq)
	#frappe.msgprint(_("Your submission of Quotation {0} was successful. You will be alerted once it is opened and evaluated.").format(sq_doc.name))
	return sq_doc.name
	#except Exception:
	#	frappe.msgprint(_("An error occurred while trying to submit your quote: {Exception}"))
	#	return None

def add_items(sq_doc, supplier, items):
	for data in items:
		if data.get("qty") > 0:
			if isinstance(data, dict):
				data = frappe._dict(data)

			create_rfq_items(sq_doc, supplier, data)

def create_rfq_items(sq_doc, supplier, data):
	sq_doc.append('items', {
		"item_code": data.item_code,
		"item_name": data.item_name,
		"description": data.description,
		"qty": data.qty,
		"rate": data.rate,
		"attachments": data.attachments,
		"files": data.attachments,
		"supplier_part_no": frappe.db.get_value("Item Supplier", {'parent': data.item_code, 'supplier': supplier}, "supplier_part_no"),
		"warehouse": data.warehouse or '',
		"request_for_quotation_item": data.name,
		"request_for_quotation": data.parent
	})
#====================================================================================================================================================
# ADD IMPORTANT ACTION LOGS TO DOCUMENTS. THESE LOGS CAN THEN BE AVAILABLE ON PRINT MODE TO TRACK APPROVALS AND DECISIONS ON DOCUMENTS.
#====================================================================================================================================================
def process_workflow_log(doc, state): 
	this_doc_workflow_state = ""
	if state == "before_save":
		workflow = get_workflow_name(doc.get('doctype'))
		if not workflow: 
			this_doc_workflow_state ="Draft"
		else:
			this_doc_workflow_state = get_doc_workflow_state(doc)
			if is_workflow_action_already_created(doc):
				#CLEAR ALL WORKFLOW ACTIONS THAT HAVE ALREADY BEEN COMPLETED ON THIS DOCUMENT IF THE NEW WORKFLOW ACTION IS DRAFT
				if this_doc_workflow_state == "Draft":
					doc_name = doc.get("name")
					frappe.db.sql(f"""DELETE FROM `tabWorkflow Action` WHERE reference_name = '{doc_name}' AND name != '1'""")
				return
			if not this_doc_workflow_state:
				this_doc_workflow_state ="Draft"
		the_decision = "Actioned To: " + this_doc_workflow_state
		
	elif state == "before_submit":
		the_decision = "Document Approved!"
		
		#LET THE USER GIVE A MEMO FOR APPROVING DOCUMENT.
		comment_on_action(doc, state)
	elif state == "on_cancel":
		the_decision = "Document Cancelled/Revoked!"
		
		#LET THE USER GIVE A MEMO FOR CANCELLING DOCUMENT.
		comment_on_action(doc, state)
	#------------------------------------------------------------------------------------------------------------------
	#ONLY LOG THE DECISION IF THE MOST RECENT DECISION IS NULL OR IS NOT EQUAL TO THE_DECISION WE WANT TO LOG - SALIM@21/7/2020
	#------------------------------------------------------------------------------------------------------------------
	decision = most_recent_decision(doc.get("name"))
	if((not decision or decision != the_decision) and (this_doc_workflow_state != "Draft")):
		log_actions(doc, the_decision)
		#================Generation of Quality Inspection========================
		if doc.get('doctype')=="Purchase Receipt" and state == "before_save" and get_doc_workflow_state(doc) =="Pending Inspection":
			#function to insert into Quality Inspection
			#frappe.msgprint("Logging: " + get_doc_workflow_state(doc))
			if is_workflow_action_already_created(doc): return
			else:	create_quality_inspection(doc)
	if this_doc_workflow_state == "Draft":
		#REMOVE ALL WORKFLOW ACTION STATES.
		doc_name = doc.get("name")
		frappe.db.sql(f"""DELETE FROM `tabWorkflow Action` WHERE reference_name = '{doc_name}' AND name != '1'""")
def most_recent_decision(docname):
	decision = frappe.db.sql("""SELECT decision FROM `tabApproval Log` where parent = %s ORDER BY creation DESC LIMIT 1""",(docname))
	decision_to_return = ""
	if decision and decision[0][0]:
		decision_to_return = decision[0][0]
	return decision_to_return	

def clean_up_rfq(doc, state):
	#RECALCULATE PROCUREMENT VALUE
	doc.set("value_of_procurement", sum(item.get('amount') for item in doc.get("items")))
	if  get_doc_workflow_state(doc) =="Pending SCM Approval":
		#if doc.get("mode_of_purchase_opinion") is None:
	# doc.get('doctype')=="Request for Quotation":# and state == "before_save" and get_doc_workflow_state(doc) =="Pending Contract Approval" and doc.get("mode_of_purchase_opinion")=="":
		#num = len(doc.get("mode_of_purchase_opinion"))
		if not doc.get("mode_of_purchase"):
			frappe.throw("You have not picked a specific procurement method to be approved for these items.")
		if not doc.get("mode_of_purchase_opinion"):
			frappe.throw("Mode of Purchase Opinion is Mandatory")
	if doc.get("message_for_supplier") == "Please provide a quote the items attached":
		new_message_to_supplier = "Please find attached, a list of item/items for your response via a quotation. We now only accept responses to the quotation via our portal. \
			Responses by replying via email or via paper based methods are NOT accepted for this quote. Please login to the portal using your credentials here: https://portal.mtrh.go.ke. Then click on 'Request for Quotations', pick this RFQ/Tender and fill in your unit price inclusive of tax."
		doc.set("message_for_supplier", new_message_to_supplier)
	if doc.get("suppliers"):
		for rfq_supplier in doc.get("suppliers"):
			#if not rfq_supplier.email_id:
			thesupplier = rfq_supplier.get("supplier")
			contact = frappe.db.get_value("Dynamic Link",\
			{"link_doctype":"Supplier", "link_title":thesupplier, "parenttype":"Contact"}\
				 ,"parent")
			#if contact:
			rfq_supplier.contact = contact
			rfq_supplier.email_id = None if not rfq_supplier.contact else  frappe.db.get_value("Contact", contact, "user")\
				or frappe.db.get_value("Contact", contact, "email_id")
			
def reassign_ownership(doc, state):
	if doc.get('doctype')=="Purchase Order" or doc.get('doctype')=="Request for Quotation":
		old_workflow_state = frappe.db.get_value(doc.get('doctype'), doc.get('name'), 'workflow_state')
		new_workflow_state = get_doc_workflow_state(doc)
		if (old_workflow_state == "Draft") and old_workflow_state != new_workflow_state:
			#WE ARE ABOUT TO TRANSITION THE DOCUMENT FROM DRAFT. ASSIGN OWNERSHIPT TO THIS OFFICER. 
			doc.set("owner", frappe.session.user)

def create_quality_inspection(doc):
	#frappe.throw(doc.name)
	docname=doc.name	
	attachments_list =  frappe.db.get_all("File",
								filters={
										"attached_to_doctype": "Purchase Receipt" ,
										"attached_to_name": docname ,					
									},
									fields=["file_url"],
									ignore_permissions = True,
									#as_list=False
								)
	urls =[]
	if not attachments_list:
		frappe.throw("There are no attachments to this Delivery, operation aborted\
			Please use the Attachments field on the Left side of this window ")
	else:
		for attachment in attachments_list:
			urls.append(attachment.get("file_url"))
		itemlist = frappe.db.get_all("Purchase Receipt Item",
			filters={
					"parent":docname,				
				},
				fields=["item_code","item_name","qty","amount"],
				ignore_permissions = True,
				as_list=False
			)
		for item in itemlist:		
			itemcode=item.get("item_code")	
			itemname=item.get("item_name")
			count_inspection = frappe.db.count('Quality Inspection', {'reference_name': docname,'item_code':itemcode})

			if count_inspection > 0:
				frappe.throw("Item {0} {1} was already forwarded for inspection  under delivery {2}".format(itemcode,itemname,docname))
			else:		
				qty=item.get("qty")		
				amount= item.get("amount")		
				template_name= frappe.db.get_value('Item', item.get("item_code"), 'quality_inspection_template')	
				today = str(date.today())
				user = frappe.session.user
				doc_type = doc.get('doctype')
				technical_user = frappe.db.get_value('Employee', doc.get('technical_evaluation_user'), 'user_id')
				#frappe.throw(doc_type)	
				docc = frappe.new_doc('Quality Inspection')
				docc.update({
					"naming_series":"MAT-QA-.YYYY.-",
					"report_date":today,	
					"inspection_type":"Incoming",
					"total_sample_size":qty,
					"sample_size":qty,
					"status":"Draft",
					"inspected_by": technical_user,
					"item_code":itemcode,
					"item_name":itemname,
					"reference_type":doc_type,
					"reference_name":docname,
					"quality_inspection_template":template_name,
					"technical_inspection": "<h2>Technical/User Inspection Report</h2>",
					"chair_inspection_report": "<h2>Chair Inspection Committee Report</h2>"
				})
				docc.insert(ignore_permissions = True)
				frappe.share.add('Quality Inspection', docc.get('name'), user = technical_user, read = 1, write = 1)
				from frappe.utils.file_manager import save_url
				for url in urls:
					filedict = frappe.db.get_value("File",{"attached_to_name":docname,"file_url": url}\
						,['file_name','folder'],as_dict=1)
					save_url(url, filedict.get("file_name"), docc.get("doctype"),\
						docc.get("name"), filedict.get("folder"),True,None)
def log_actions(doc, action_taken):
	logged_in_user = frappe.session.user
	child = frappe.new_doc("Approval Log")
	action_user = get_fullname(logged_in_user)

	if "Employee" not in frappe.get_roles(frappe.session.user):
		action_user ="System Generated"
	action_user_signature = None
	if frappe.db.exists("Signatures", logged_in_user):
		action_user_signature = frappe.get_cached_value("Signatures", logged_in_user, "signature")
	child.update({
		"doctype": "Approval Log",
		"parenttype": doc.get('doctype'),
		"parent": doc.get('name'),
		"parentfield": "action_log",
		"action_time": frappe.utils.data.now_datetime(),
		"decision": action_taken,
		"action_user": action_user,
		"signature": action_user_signature,
		"idx": len(doc.action_log) + 1
	})
	doc.action_log.append(child)

def is_workflow_action_already_created(doc):
	return frappe.db.exists({
		'doctype': 'Workflow Action',
		'reference_doctype': doc.get('doctype'),
		'reference_name': doc.get('name'),
		'workflow_state': get_doc_workflow_state(doc)
	})

def get_doc_workflow_state(doc):
	workflow_name = get_workflow_name(doc.get('doctype'))
	workflow_state_field = get_workflow_state_field(workflow_name)
	return doc.get(workflow_state_field)

def get_next_possible_transitions(workflow_name, state, doc=None):
	transitions = frappe.get_all('Workflow Transition',
		fields=['allowed', 'action', 'state', 'allow_self_approval', 'next_state', '`condition`'],
		filters=[['parent', '=', workflow_name],
		['state', '=', state]])

	transitions_to_return = []

	for transition in transitions:
		is_next_state_optional = get_state_optional_field_value(workflow_name, transition.next_state)
		# skip transition if next state of the transition is optional
		if transition.condition and not frappe.safe_eval(transition.condition, None, {'doc': doc.as_dict()}):
			continue
		if is_next_state_optional:
			continue
		transitions_to_return.append(transition)

	return transitions_to_return

def get_state_optional_field_value(workflow_name, state):
	return frappe.get_cached_value('Workflow Document State', {
		'parent': workflow_name,
		'state': state
	}, 'is_optional_state')

#====================================================================================================================================================
# ON IMPORTANT ACTIONS ON DOCUMENT, PUBLISH A CALL TO UTILITIES.JS SO THAT THE USER CAN BE FORCED TO ENTER A COMMENT/MEMO.
#====================================================================================================================================================
def comment_on_action(doc, state):
	decision = """Saved document"""
	if state == "on_cancel":
		decision = """Cancel document"""
	elif state == "before_submit":
		decision = """Approve document"""
	
	frappe.publish_realtime('doc_comment'+doc.get('name'), {"doc": doc, 'doc_type': doc.get('doctype'),'doc_name': doc.get('name'), 'decision': decision}, user=frappe.session.user)
	#frappe.msgprint("""The doctype ={0} and the docname = {1} """.format(doc.get('doctype'), doc.get('name')))
	#this_doctype = """{{0}}""".format(doc.get('doctype'))
	#this_docname = """{{0}}""".format(doc.get('name'))
	#msgvar = """
	#var docType = '""" + doc.get('doctype') + """';
	#var docName = '""" + doc.get('name') + """';
	#frappe.prompt([
	#	{
	#		label: 'Enter narative for your decision',
	#		fieldtype: 'Small Text',
	#		reqd: true,
	#		fieldname: 'reason'
	#	}],
	#	function(args){
	#		console.log('Reason: ' + args.reason);
	#		//INSERT COMMENT.
	#		//frappe.get_doc(docType, docName).add_comment(frappe.session.user + ' - Document Action Memo : ' + args.reason);
	#		var commentStr = frappe.session.user + ' - Document Action Memo : ' + args.reason;
	#		var comment  = [];
	#		comment["comment"] = commentStr;
	#		comment["comment_by"] = frappe.session.user;
	#		
	#		frappe.publish_realtime('new_comment', comment, doctype = docType, docname = docName)
	#	}
	#);
	#"""
	
	#frappe.msgprint(msgvar)
	 
	#frappe.publish_realtime(event='eval_js', message=msgvar, user=frappe.session.user, doctype = doc.get('doctype'), docname = doc.get('name'))
#====================================================================================================================================================
# VALIDATE THE BUDGET ON SUBMIT AND ALERT IF BUDGET NOT AVAILABLE.
#====================================================================================================================================================

def validate_budget(doc, state):
	purchase_order_items = doc.get("items")
	unique_departments = []
	unique_expense_accounts = []
	payload = []
	row = {}
	
	#GET FISCAL YEAR DETAILS
	fiscal_year_details = get_fiscal_year(today())
	fiscal_year = fiscal_year_details[0]
	fiscal_year_starts = fiscal_year_details[1]
	fiscal_year_ends = fiscal_year_details[2]
	
	for itemrow in purchase_order_items:
		expense_account = itemrow.expense_account
		this_department = itemrow.department
		#GET UNIQUE LIST OF EXPENSE ACCOUNTS
		if expense_account not in unique_expense_accounts:
			unique_expense_accounts.append(expense_account)
		#GET UNIQUE LIST OF DEPARTMENTS
		if this_department not in unique_departments:
			unique_departments.append(this_department)
	
	for department in unique_departments:
		for expense_account in unique_expense_accounts:
			total = 0.0
			for itemrow in purchase_order_items:
				if expense_account and expense_account == itemrow.expense_account and department and itemrow.department == department:
					total = total + itemrow.amount
			row['department'] = department
			row['expense_account'] = expense_account
			row['amount'] = total
			payload.append(row)
		
	for itemrow in payload:
		department = itemrow['department']
		expense_account = itemrow['expense_account']
		amount = itemrow['amount']
		
		#1 GET BUDGET ID
		budget = frappe.db.get_value('Budget', {'department': department,"fiscal_year": fiscal_year, "docstatus":"1"}, 'name')
		
		#2 GET BUDGET AMOUNT:
		budget_amount = frappe.db.get_value('Budget Account', {'parent':budget, "account":expense_account, "docstatus":"1"}, 'budget_amount')
		#============expired lpos
		#total_amount=0.0
		#total_expired_amount =frappe.db.sql("""SELECT  sum(amount*((a.per_received)/100)) as total FROM `tabPurchase Order Item` as b,`tabPurchase Order` as a""")
		total_expired_amount =frappe.db.sql("""SELECT  SUM(amount*((a.per_received)/100)) as total FROM `tabPurchase Order Item` as b,`tabPurchase Order` as a WHERE b.creation BETWEEN %s AND %s AND a.name=b.parent AND a.schedule_date < now()
		#AND b.expense_account= %s AND b.docstatus=1""",(fiscal_year_starts,fiscal_year_ends,expense_account))
		#frappe.throw(total_expired_amount)
		#==========end of expired lpos
		
		#3. GET SUM OF ALL APPROVED PURCHASE ORDERS:
		total_commitments = frappe.get_all('Purchase Order Item',
			filters = {
				'department':department,
				'expense_account':expense_account,
				 "creation": [">=", fiscal_year_starts],
				 "creation": ["<", fiscal_year_ends],
				 "docstatus": ["=", 1]
			},
			fields = "sum(`tabPurchase Order Item`.amount) as total_amount",
			order_by = 'creation',
			group_by='department',
			#page_length=2000
			ignore_permissions = True,
			#as_list=False
		)
		#commitments = total_commitments[0].total_amount 
		sql_department_expense_amount = _("""SELECT SUM(amount) as total_amount from `tabPurchase Order Item` WHERE department = '{0}' AND expense_account = '{1}' AND creation >= '{2}' AND creation < '{3}' AND  docstatus = 1""").format(department, expense_account, fiscal_year_starts, fiscal_year_ends)
		#frappe.msgprint(sql_department_expense_amount)
		total_commitments = frappe.db.sql(sql_department_expense_amount)
		commitments = 0.0
		if total_commitments and total_commitments[0][0]:
			commitments = total_commitments[0][0]
		if commitments is None:
			commitments = 0.0
		if budget_amount is None:
			budget_amount = 0.0
		balance = float(budget_amount)-(float(commitments))
		#balance=(balance)+(total_expired_amount)
		#frappe.msgprint("""Budget Amount: """ + str(budget_amount) + """,  Total Committments: """ + str(commitments) + """, fiscal_year_starts: """ + str(fiscal_year_starts) )
		if(float(balance) < float(amount) ):
			frappe.throw("""Sorry, this order will not proceed because requests for Department [<b>"""+department+"""</b>] Expense account [<b>"""+expense_account+"""</b>] exceed the current vote balance. <br><br> Vote Balance: [<b>"""+str(balance)+"""</b>]<br>Needed Amount:[<b>"""+str(amount)+"""</b>] """, title = """Budget Exceeded!""")
	process_workflow_log(doc, state)

#====================================================================================================================================================
# FORCEFULLY UPDATE STATUS OF A DOCUMENT E.G. CANCEL AT DRAFT STAGE...
#====================================================================================================================================================
@frappe.whitelist()
def forcefully_update_doc_field(doc_type, doc_name, field, data):
	sql_to_run = """UPDATE `tab""" + doc_type + """` SET `""" + field + """` = '{0}' WHERE `name` = '{1}'""".format(data, doc_name)
	frappe.db.sql(sql_to_run)

#====================================================================================================================================================
# ON A NEW MESSAGE, ALERT A LOGGED IN USER.
#====================================================================================================================================================	
def alert_user_on_message(doc, state):
	userlist = frappe.db.get_all("Chat Room User",
		filters={
				"parent": doc.get('room'),
				"parentfield": 'users'
			},
			fields=["user", "owner"],
			ignore_permissions = True,
			as_list=False
		)
	for user in userlist:		
		#for each user in the room, alert them.
		source_user = get_fullname(frappe.session.user)
		target_user = get_fullname(user.get("user"))
		the_message = _("""Dear {0} You have a new message from {1}: {2}. Continue the chat under the chat window to respond""").format(target_user, source_user, doc.get("content"))
		frappe.publish_realtime(event='msgprint',message = the_message, user = user.get("user"))
		if(source_user == "Administrator"):
			message_out = _("""Dear {0}, You have a message from MTRH Enterprise Portal: {1}.""").format(target_user, doc.get("content"))
			schedule_sms_to_user(user.get("user"), message_out)
		
#====================================================================================================================================================
# RETURNS A PHONE NUMBER OF A USER WHEN THEIR USER ID/EMAIL IS PASSED.																				=
#====================================================================================================================================================
def get_user_phonenumber(userid):
	the_employee_sql = _("""select cell_number from `tabEmployee`\
		 where (personal_email LIKE '{0}' or company_email LIKE '{1}')""").\
			 format(userid, userid)
	the_employee = frappe.db.sql(the_employee_sql)
	the_phone = ""
	if the_employee and the_employee[0][0]:
		the_phone = the_employee[0][0]
	"""if(len(the_phone) < 11 and len(the_phone) > 0):
		if the_phone[0] != "0":
			the_phone = "0" + the_phone"""
	if not the_phone:
		the_phone = fetch_contact(userid)
	return the_phone
def fetch_contact(userid):
	sql_to_run =f"""SELECT mobile_no FROM `tabContact` WHERE mobile_no\
		IS NOT NULL and email_id ='{userid}' LIMIT 1 """
	mobile_no = frappe.db.sql(sql_to_run,as_dict=True)
	return mobile_no[0].get("mobile_no") if mobile_no else ""
#====================================================================================================================================================
# SEND A USER SMS GIVEN A USER ID/EMAIL		
#====================================================================================================================================================
@frappe.whitelist()
def send_sms_to_user(userid, message):
	if cint(frappe.defaults.get_defaults().get("hold_queue"))==1:
		return
	incoming_payload =[]
	phone = get_user_phonenumber(userid)
	#frappe.response["phone"] = phone
	if phone:
		data = {
			"phone": phone,
			"message": message
		}
		#frappe.response["data"] = data
		incoming_payload.append(data.copy())
		send_sms_alert(json.dumps(incoming_payload))
		#print(_("""User {0} has been alerted through SMS""").format(userid))
		frappe.msgprint(_("""User {0} has been alerted through SMS""").format(userid))
	return

@frappe.whitelist()
def schedule_sms_to_user(userid, sms_message):
	phone = get_user_phonenumber(userid)
	sms_log = frappe.get_doc({
		"doctype": "SMS Log",
		"sender_name": "MTRH Bulk SMS",
		"message":sms_message,	
		"requested_numbers":phone,
		"no_of_requested_sms": 0,
		"no_of_sent_sms":0,
		"status": "Scheduled",
		"is_not_from_sms_center":True
	})
	sms_log.flags.ignore_permissions=True
	sms_log.flags.ignore_links=True
	sms_log.insert()
	frappe.msgprint(_(f"""User {userid} will be alerted through SMS"""))
	return
def mark_sms_center_document_as_scheduled(doc, state):
	if not doc.get("is_not_from_sms_center"):
		doc.set("status", "Scheduled")
		doc.flags.ignore_permissions = True
		doc.run_method("set_missing_values")
		doc.save()
def send_scheduled_sms_cron():
	scheduled_sms = frappe.db.get_all("SMS Log",
		filters={
				"status": 'Scheduled'
			},
			fields=["requested_numbers", "message", "name"],
			ignore_permissions = True,
			as_list=False
		)
	for sms in scheduled_sms:
		incoming_payload =[]
		all_contacts = str(sms.get("requested_numbers"))
		delimiter ="\n"
		contacts_arr = all_contacts.split(delimiter)
		message = sms.get("message")
		incoming_payload = [
		 {
			"phone": x,
			"message": message
		} for x in contacts_arr]
		#incoming_payload.append(data.copy())
		send_sms_alert(json.dumps(incoming_payload))
		#print(_("""User {0} has been alerted through SMS""").format(userid))
		#frappe.msgprint(_("""User {0} has been alerted through SMS""").format(userid))
	#SET ALL SMS TO SENT.
	sms_names = [x.get("name") for x in scheduled_sms]
	sms_names_str = '('+','.join("'{0}'".format(i) for i in sms_names)+')'
	sql_upd_sms = f"UPDATE `tabSMS Log` SET status = 'Processed' WHERE `name` IN {sms_names_str}"
	frappe.db.sql(sql_upd_sms)
	return
def queue_bulk_sms_docs_cron():
	doclist = frappe.db.sql(f"""SELECT name FROM `tabBulk SMS Dispatch`\
		 WHERE evaluated = 0 and docstatus = 1""", as_dict=True)
	if doclist:
		documents = [frappe.get_doc("Bulk SMS Dispatch",x.get("name")) for x in doclist]
		list(map(lambda x: schedule_sms_dispatch(x), documents))
def schedule_sms_dispatch(doc):
	doc.send_sms()
	doc.db_set("evaluated", 1)
	return
#====================================================================================================================================================
# ALERT USERS ON A NEW WORKFLOW ACTION CREATED.	
#====================================================================================================================================================
def alert_user_on_workflowaction(doc, state):
	theuser = doc.get('user')
	reference_doctype = doc.get('reference_doctype')
	reference_name = doc.get('reference_name')
	workflow_state = doc.get('workflow_state')
	if(workflow_state != "Approved"):
		message_out = _("""A document {0} - {1} has been forwarded to you to action on MTRH Enterprise Portal. Check all your pending work here: https://bit.ly/2F8E18L""").format(reference_doctype, reference_name)
		#schedule_sms_to_user(theuser, message_out)
	return
@frappe.whitelist()
def return_approval_routes(department):
	#GET LIST OF DEPARTMENT WITH THE TREE
	if not frappe.db.exists("Department", department) or not department:
		frappe.response["message"]="Department {0} does not exist".format(department)
	else:
		department_tree = frappe.db.get_all("Department", fields=('name', 'parent_department'))
		department_level_pointer = department
		department_level = 0
		hod_reports_to_ceo = False
		hod_reports_to_sd = False
		director_reports_to_ceo = False
		senor_director_found = -1
		directorate_found = -1 
		while(department_level_pointer != "All Departments"):
			for this_department in department_tree:
				if department_level_pointer in this_department['name']:
					department_level += 1
					#CHECK IF WE ARE GOING TRHOUGH A SENIOR DIRECTOR. IF NOT, THEN DIRECTOR IS REPORTING TO CEO
					if(senor_director_found == -1):
						senor_director_found = this_department['name'].lower().find('senior')
					if(directorate_found == -1):
						directorate_found = this_department['name'].lower().find('directorate')
					if(senor_director_found > -1 and directorate_found == -1):
						#WE HAVE GONE TRHOUGH SENIOR DIRECTOR WITHOUT A DIRECTORATE. SO THIS DEPARTMENT REPORTS TO SENIOR DIRECTOR
						hod_reports_to_sd = True
					department_level_pointer = this_department['parent_department']
					break
		if department_level == 2:
			hod_reports_to_ceo = True
		if(senor_director_found == -1 and directorate_found > -1):
			director_reports_to_ceo = True
		frappe.response['hod_reports_to_ceo'] = hod_reports_to_ceo
		frappe.response['hod_reports_to_sd'] = hod_reports_to_sd
		frappe.response['director_reports_to_ceo'] = director_reports_to_ceo
		return hod_reports_to_ceo,hod_reports_to_sd,director_reports_to_ceo
def assign_department_permissions(doc,state):
	userid = doc.get("user_id")
	clear_user_permissions(userid,"Department")
	department = doc.get("department")
	fullname = doc.get("employee_name")
	if department:
		if userid:
			frappe.permissions.add_user_permission("Department",department, userid)
			frappe.msgprint("User {0} - {1} has been assigned to {2}".format(userid, fullname, department))
		else:
			frappe.msgprint("Department permissions have not been applied since the user does not have a log in account.")
	else:
		frappe.throw("Please ensure that user has log in credentials and is allocated to a department")
def send_comment_sms(doc,state):
	if doc.reference_doctype and doc.reference_name and doc.content:
		mentions = extract_mentions(doc.content)

		if not mentions:
			return
		sender_fullname = get_fullname(frappe.session.user)
		#title = get_title(doc.reference_doctype, doc.reference_name)
		reference_document = frappe.get_doc(doc.reference_doctype, doc.reference_name)
		recipients = [frappe.db.get_value("User", {"enabled": 1, "name": name, "user_type": "System User", "allowed_in_mentions": 1}, "email")
			for name in mentions]
		"""notification_message = _('''{0} mentioned you in a comment in {1} [{2}] please log in to your portal or corporate email account view and respond to the comment''')\
			.format(sender_fullname, doc.reference_doctype, title)"""
		data = doc.content
		import re
		nosp = re.compile('\ufeff.*\ufeff')#REMOVES SPECIAL CHARACTERS @TAGS
		p_data = re.sub(nosp, '', data)
		clean = re.compile('<(.*?)>') #REMOVES ALL HTML LIKE TAGS I.E <>
		filtered_content = re.sub(clean, '', p_data)
		content_to_send =  (filtered_content[:720] + '...') if len(filtered_content) > 720 else filtered_content

		notification_message = _('''{0}:  REF: [{1} - {2}]\n{3}''')\
			.format(sender_fullname, doc.reference_doctype, reference_document.get("name"),\
				 content_to_send)
		for recipient in recipients:
			#frappe.msgprint(f"User {recipient} notified via SMS. - {notification_message}")
			schedule_sms_to_user(recipient, notification_message)
def check_purchase_receipt_before_save(doc, state):
	if is_workflow_action_already_created(doc): return
	else:
		supplier_delivery = doc.get("supplier_delivery_note")
		if supplier_delivery and doc.get("items"):
			for d in doc.get("items"):
				count_inspection = frappe.db.count('Quality Inspection', {'reference_name': doc.get("name"),'item_code':d.get("item_code")})
				if count_inspection and count_inspection > 0:
					return
					#frappe.throw("Item {0} => [{1}] was already forwarded for inspection  under delivery {2} \
					#	count: {3}".format(d.get("item_code"),d.get("item_name"),doc.get("name"),count_inspection))
				else:
					purchase_order = d.get("purchase_order")
					if purchase_order:
						purchase_order_maximum =  frappe.db.sql("""SELECT sum(coalesce(qty,0)) as qty FROM `tabPurchase Order Item` 
							WHERE docstatus =%s and parent = %s and item_code =%s """,
							("1", purchase_order, d.get("item_code")), as_dict=1)
						purchase_receipts = frappe.db.sql("""SELECT sum(coalesce(received_qty-rejected_qty,0)) as qty FROM `tabPurchase Receipt Item` 
							WHERE  purchase_order = %s and item_code =%s and parent !=%s""",
							(purchase_order, d.get("item_code"), doc.get("name")), as_dict=1)
						receipts_total = 0 if not purchase_receipts[0].qty else float(purchase_receipts[0].qty)
						balance_to_receive = float(purchase_order_maximum[0].qty) - receipts_total
						
						'''Check if received qty exceeds PO balance'''

						if float(d.get('received_qty')) > balance_to_receive:
							frappe.throw("You cannot receive quantities exceeding the Purchase Order Balance. Current Balance for {0} is {1}"\
								.format(d.get("item_code"), balance_to_receive))
					else:
						frappe.throw("Item {0} has not been captured in any purchase order. Please use the 'Get Items From' button".format(d.get("item_name")))
		else :
			frappe.throw("Please ensure you enter and attach supplier delivery, and the relevant items")
@frappe.whitelist()
def user_detail(user_id, field_to_return):
	field_value = frappe.db.get_value("Employee",{'user_id':user_id},field_to_return) or ""
	frappe.response["message"] = field_value
	return field_value
def sync_purchase_receipt_attachments(doc,state):
	if doc.get("attached_to_doctype")=="Purchase Receipt":
		related_doctypes =["Quality Inspection","Purchase Invoice"]
		catered_for_docs = frappe.db.get_all("File",
								filters={
										"attached_to_doctype": ['IN',related_doctypes],
										"file_url" : doc.get("file_url")				
									},
									fields=["attached_to_name"],
									ignore_permissions = True,
									#as_list=False
								)
		docs_with_file_url =[]
		for docname in catered_for_docs:
			docs_with_file_url.append(docname.get("attached_to_name"))
		documents =[]
		
		for doctype in related_doctypes:
			if doctype == "Quality Inspection":
				docs = frappe.db.get_all(doctype,
								filters={
										"reference_name":doc.get("attached_to_name"),
										"name":["NOT IN", docs_with_file_url]				
									},
									fields=["name"],
									ignore_permissions = True,
									#as_list=False
								)
						
				for d in docs:
					jsonobj ={}
					jsonobj["doctype"]=doctype
					jsonobj["docname"]=d.get("name")
					documents.append(jsonobj)
				
					#documents.append({'doctype':doctype,'docname':d.get("name")})
			elif doctype == "Purchase Invoice":
				docs = frappe.db.get_all("Purchase Invoice Item",
								filters={
										"purchase_receipt":doc.get("attached_to_name"),
										"parent":["NOT IN", docs_with_file_url]				
									},
									fields=["parent"],
									group_by='parent',
									ignore_permissions = True,
								#	as_list=False
								)
				for d in docs:
					jsonobj ={}
					jsonobj["doctype"]=doctype
					jsonobj["docname"]=d.get("parent")
					documents.append(jsonobj)
					#documents.append({'doctype':doctype,'docname':d.get("parent")})
		
		for this_document in documents:
			#frappe.msgprint("Updating {0} - {1}".format(this_document.get('doctype'),this_document.get('docname')))
			document = frappe.copy_doc(doc)
			document.attached_to_doctype = this_document.get('doctype')
			document.attached_to_name = this_document.get('docname')
			document.flags.ignore_permissions = True
			document.run_method("set_missing_values")
			document.insert()
		return documents, docs
def update_pinv_attachments_before_save(doc , state):
	purchase_receipt = doc.get("items")[0].purchase_receipt
	purchase_invoice = doc.get("name")
	if purchase_receipt:
		
		attachments_list_query =f"""SELECT file_url FROM `tabFile`\
			 WHERE attached_to_doctype='Purchase Receipt'\
				  AND attached_to_name= '{purchase_receipt}'\
					   AND file_url\
						    NOT IN (SELECT file_url FROM `tabFile` WHERE attached_to_doctype ='Purchase Invoice'\
								AND attached_to_name='{purchase_invoice}') """

		attachments_list = frappe.db.sql(attachments_list_query, as_dict=True)
		urls =[x.get("file_url") for x in attachments_list]
		#for attachment in attachments_list:
		#	urls.append(attachment.get("file_url"))
		from frappe.utils.file_manager import save_url
		if urls:
			for url in urls:
				filedict = frappe.db.get_value("File",{"attached_to_name":purchase_receipt,"file_url": url}\
					,['file_name','folder'],as_dict=1)

				save_url(url, filedict.get("file_name"), doc.get("doctype"),\
					doc.get("name"), filedict.get("folder"),True,None)
	return	
@frappe.whitelist()
def return_budget_dict(dimension,dimension_name,account):
	from frappe.desk.query_report import run
	report_name ="Vote Balance Report"
	filters ={
		"from_fiscal_year":frappe.defaults.get_user_default("fiscal_year"),
		"to_fiscal_year":frappe.defaults.get_user_default("fiscal_year"),
		"period":"Quarterly",
		"company":frappe.defaults.get_user_default("Company"),
		"budget_against":dimension,#ths
		"budget_against_filter":[dimension_name]
		}
	pl = run(report_name, filters)
	need  = [b for b in pl.get('result') if b[1]==account] #[[...]]
	from datetime import datetime
	year_start_month = datetime.strptime(frappe.defaults.get_user_default("year_start_date"), "%Y-%m-%d").month
	this_month = datetime.today().month
	month_diff = this_month - year_start_month
	if ((month_diff) <0): month_diff = month_diff * -1
	#FOR THE RESPECTIVE QUARTERS, DATA IS need[0] - | 2, 3, 4, 5 | 6, 7, 8, 9 | 10, 11, 12, 13| 14, 15, 16, 17| THEN TOTAL 18, 19, 20, 21
	quarter_budget, quarter_actual, quarter_commit, quarter_balance = 2, 3, 4, 5
	if month_diff < 3 :
		quarter_budget, quarter_actual, quarter_commit, quarter_balance = 2, 3, 4, 5
	elif month_diff < 6 :
		quarter_budget, quarter_actual, quarter_commit, quarter_balance = 6, 7, 8, 9
	elif month_diff < 9 :
		quarter_budget, quarter_actual, quarter_commit, quarter_balance = 10, 11, 12, 13
	else :
		quarter_budget, quarter_actual, quarter_commit, quarter_balance = 14, 15, 16, 17
	data_to_return = {}
	if need and need[0]:
		single_row = need[0]
		data_to_return['q_budget'] = single_row[quarter_budget]
		data_to_return['q_actual'] = single_row[quarter_actual]
		data_to_return['q_commit'] = single_row[quarter_commit]
		data_to_return['q_balance'] = single_row[quarter_balance]
		data_to_return['t_budget'] = single_row[18]
		data_to_return['t_actual'] = single_row[19]
		data_to_return['t_commit'] = single_row[20]
		data_to_return['t_balance'] = single_row[21]
	return data_to_return

@frappe.whitelist()
def return_budget_all_dict(account):
	from frappe.desk.query_report import run
	report_name ="Vote Balance Report"
	filters ={
		"from_fiscal_year":frappe.defaults.get_user_default("fiscal_year"),
		"to_fiscal_year":frappe.defaults.get_user_default("fiscal_year"),
		"period":"Quarterly",
		"company":frappe.defaults.get_user_default("Company"),
		"budget_against": "Department"
		}
	pl = run(report_name, filters)
	need  = [b for b in pl.get('result') if b[1]==account] #[[...]]
	from datetime import datetime
	year_start_month = datetime.strptime(frappe.defaults.get_user_default("year_start_date"), "%Y-%m-%d").month
	this_month = datetime.today().month
	month_diff = this_month - year_start_month
	if ((month_diff) <0): month_diff = month_diff * -1
	#FOR THE RESPECTIVE QUARTERS, DATA IS need[0] - | 2, 3, 4, 5 | 6, 7, 8, 9 | 10, 11, 12, 13| 14, 15, 16, 17| THEN TOTAL 18, 19, 20, 21
	quarter_budget, quarter_actual, quarter_commit, quarter_balance = 2, 3, 4, 5
	if month_diff < 3 :
		quarter_budget, quarter_actual, quarter_commit, quarter_balance = 2, 3, 4, 5
	elif month_diff < 6 :
		quarter_budget, quarter_actual, quarter_commit, quarter_balance = 6, 7, 8, 9
	elif month_diff < 9 :
		quarter_budget, quarter_actual, quarter_commit, quarter_balance = 10, 11, 12, 13
	else :
		quarter_budget, quarter_actual, quarter_commit, quarter_balance = 14, 15, 16, 17
	data_to_return = {}
	if need and need[0]:
		single_row = need[0]
		data_to_return['q_budget'] = single_row[quarter_budget]
		data_to_return['q_actual'] = single_row[quarter_actual]
		data_to_return['q_commit'] = single_row[quarter_commit]
		data_to_return['q_balance'] = single_row[quarter_balance]
		data_to_return['t_budget'] = single_row[18]
		data_to_return['t_actual'] = single_row[19]
		data_to_return['t_commit'] = single_row[20]
		data_to_return['t_balance'] = single_row[21]
	return data_to_return

@frappe.whitelist()
def get_votehead_balance(document_type, document_name):
	doc = frappe.get_doc(document_type, document_name)
	doc.flags.ignore_permissions = True
	dimension, dimension_name ="",""
	if doc.get("doctype") == "Purchase Order":
		department = doc.get("items")[0].department
		account = doc.get("items")[0].expense_account
		amount = doc.get("grand_total")
		dimension,dimension_name ="Department", department
		if doc.get("items")[0].project:
			dimension, dimension_name = None, None
			dimension, dimension_name ="Project",doc.get("items")[0].project
		vote = return_budget_dict(dimension, dimension_name, account)
		
		#CALCULATE AMOUNT FOR ALL PURCHASE ORDERS CREATED AFTER THIS ONE. SO WE CAN REMOVE THEM FROM TOTOL COMMITMENT
		total_amount_older_pos = frappe.db.get_all('Purchase Order Item', 
			filters={
				'creation': [">", doc.get("creation")],
				'expense_account': account,
				'department': department
			},
			fields="sum(`tabPurchase Order Item`.amount) as total", ignore_permissions=True)[0].total or 0.0
		#BUDGET BALANCES
		quarter_budget, annual_budget = frappe.format(vote.get("q_budget") or 0.0, 'Currency'), frappe.format(vote.get("t_budget") or 0.0, 'Currency')

		real_quarter_commitment = vote.get("q_balance") or 0 + total_amount_older_pos + amount
		real_annual_commitment = vote.get("t_balance") or 0 + total_amount_older_pos + amount
		
		
		#FORMAT THE VOTE BALANCE STATEMENT
		vote_statement = "<b>Vote Balance Statement - {0} - {1}</b></hr><br/><table border='1' width='100%' >".format(department, account)
		vote_statement += "<tr><td><b>Item</b></td><td>Quarter</td><td>Annual</td></tr>"
		vote_statement += "<tr><td><b>Allocation</b></td><td align='right'>{0}</td><td align='right'>{1}</td></tr>".format(quarter_budget, annual_budget)
		vote_statement += "<tr><td><b>Balance Before</b></td><td align='right'>{0}</td><td align='right'>{1}</td></tr>".format(frappe.format(real_quarter_commitment, 'Currency'), frappe.format(real_annual_commitment, 'Currency'))
		vote_statement += "<tr><td><b>This Commitment</b></td><td align='right'>{0}</td><td align='right'>{1}</td></tr>".format(frappe.format(amount, 'Currency'), frappe.format(amount, 'Currency'))
		vote_statement += "<tr><td><b>Balance After</b></td><td align='right'>{0}</td><td align='right'>{1}</td></tr>".format(frappe.format(real_quarter_commitment - amount, 'Currency'), frappe.format(real_annual_commitment - amount, 'Currency'))
		vote_statement += "</table>"
		#forcefully_update_doc_field("Purchase Order", doc.get("name"), "vote_balance", vote_statement)
		if not doc.get("vote_statement") and doc.get("docstatus") == 0:
			doc.set("vote_statement", vote_statement)
			doc.flags.ignore_permissions = True
			doc.save()
			doc.notify_update()
		from mtrh_dev.mtrh_dev.tender_quotation_utils import document_dashboard
		vote_statement+= document_dashboard(document_type, document_name)
		return vote_statement
	elif document_type=="Payment Request":
		#GET ASSOCIATED PURCHASE ORDER.
		doc = frappe.get_doc(document_type, document_name)
		associated_invoice = frappe.get_doc("Purchase Invoice", doc.get("reference_name"))
		associated_po = frappe.get_doc("Purchase Order", associated_invoice.get("items")[0].purchase_order)

		department = associated_po.get("items")[0].department
		account = associated_po.get("items")[0].expense_account
		amount = associated_po.get("grand_total")
		dimension,dimension_name ="Department", department
		this_entry_amount = flt(doc.get("grand_total"))
		if associated_po.get("items")[0].project:
			dimension, dimension_name = None, None
			dimension, dimension_name ="Project",associated_po.get("items")[0].project
		vote = return_budget_dict(dimension, dimension_name, account)
		#BUDGET BALANCES
		flt_quarter_budget, flt_annual_budget = flt(vote.get("q_budget")) or 0.0, flt(vote.get("t_budget")) or 0.0
		flt_quarter_commitment, flt_annual_commitment = flt(vote.get("q_commit")) or 0.0, flt(vote.get("q_commit")) or 0.0
		flt_quarter_actual, flt_annual_actual = flt(vote.get("q_actual")) or 0.0, flt(vote.get("t_actual")) or 0.0
		flt_quarter_aggregated, flt_annual_aggregated = flt_quarter_commitment + flt_quarter_actual - this_entry_amount,\
			flt_annual_commitment + flt_annual_actual - this_entry_amount
		flt_quarter_balance_before, flt_annual_balance_before = flt_quarter_budget - flt_quarter_aggregated, \
			flt_annual_budget - flt_annual_aggregated, 
		flt_quarter_balance_after, flt_annual_balance_after = flt_quarter_balance_before - this_entry_amount, \
			flt_annual_balance_before - this_entry_amount, 

		quarter_budget, annual_budget = frappe.format(flt_quarter_budget, 'Currency'), frappe.format(flt_annual_budget, 'Currency')
		#quarter_commitment, annual_commitment = frappe.format(flt_quarter_commitment, 'Currency'), frappe.format(flt_annual_commitment, 'Currency')
		#quarter_actual, annual_actual = frappe.format(flt_quarter_actual, 'Currency'), frappe.format(flt_annual_actual, 'Currency')
		quarter_aggregated, annual_aggregated = frappe.format(flt_quarter_aggregated, 'Currency'), frappe.format(flt_annual_aggregated, 'Currency')
		quarter_balance_before, annual_balance_before = frappe.format(flt_quarter_balance_before, 'Currency'), frappe.format(flt_annual_balance_before, 'Currency')
		quarter_balance_after, annual_balance_after = frappe.format(flt_quarter_balance_after, 'Currency'), frappe.format(flt_annual_balance_after, 'Currency')
		this_entry_formatted = frappe.format(this_entry_amount, 'Currency')
		
		#FORMAT THE VOTE BALANCE STATEMENT
		vote_statement = "<b>Vote Balance Statement - {0} - {1}</b></hr><br/><table border='1' width='100%' >".format(department, account)
		vote_statement += "<tr><td><b>Item</b></td><td>Quarter</td><td>Annual</td></tr>"
		vote_statement += "<tr><td><b>Allocation</b></td><td align='right'>{0}</td><td align='right'>{1}</td></tr>".format(quarter_budget, annual_budget)
		vote_statement += "<tr><td><b>Commitments and Expenditure</b></td><td align='right'>{0}</td><td align='right'>{1}</td></tr>".format(quarter_aggregated, annual_aggregated)
		vote_statement += "<tr><td><b>Balance Before</b></td><td align='right'>{0}</td><td align='right'>{1}</td></tr>".format(quarter_balance_before, annual_balance_before)
		vote_statement += "<tr><td><b>This Entry</b></td><td align='right'>{0}</td><td align='right'>{1}</td></tr>".format(this_entry_formatted, this_entry_formatted)
		vote_statement += "<tr><td><b>Balance After</b></td><td align='right'>{0}</td><td align='right'>{1}</td></tr>".format(quarter_balance_after, annual_balance_after)
		vote_statement += "</table>"
		#forcefully_update_doc_field("Purchase Order", doc.get("name"), "vote_balance", vote_statement)
		if not doc.get("vote_statement") and doc.get("docstatus") == 0:
			doc.set("vote_statement", vote_statement)
			doc.flags.ignore_permissions = True
			doc.save()
			doc.notify_update()
		from mtrh_dev.mtrh_dev.tender_quotation_utils import document_dashboard
		vote_statement+= document_dashboard(document_type, document_name)
		return vote_statement
	elif document_type=="Material Request":
		pass
	else:
		return
def daily_pending_work_reminder():
	#GET UNIQUE LIST OF USERS WITH PENDING WORK ON WORKFLOW ACTION TABLE.
	user_pending_counts = frappe.db.get_all('Workflow Action',
		filters = {
			'workflow_state': ['NOT IN', ['%Approved%', '%Cancelled%', 'Approved', 'Cancelled']],#Approved
			'status': ['not like', '%Completed%']
		},
		fields=['count(name) as count', 'user'],
		group_by='user'
	)

	if user_pending_counts and user_pending_counts[0]:
		for user in user_pending_counts:
			user_pending_works = frappe.db.get_all('Workflow Action',
				filters = {
					'workflow_state': ['NOT IN', ['%Approved%', '%Cancelled%', 'Approved', 'Cancelled']],
					'status': ['not like', '%Completed%'],
					'user': user.get("user")
				},
				fields=['reference_name', 'reference_doctype', 'workflow_state', 'creation']
			)
			no_of_documents = user.get("count")
			user_email = user.get("user")
			email_message = f"Dear Sir/Madam,<br/>There are {no_of_documents} items which are pending in your in-tray in the ERP. It is advised that prompt action be taken on the documents to improve efficieny. The list of items is shown below. You can also find all your pending work at all times here: https://bit.ly/2F8E18L <br/>"
			email_message += f"<b>Pending Items for - {user_email}: </b><hr><table border='1' width='100%' >"
			email_message += "<tr><td><b>Document Type</b></td><td>Document</td><td>Current State</td><td align='right'>Action Delay</td></tr>"
			
			date_format = "%m/%d/%Y"
			today_date = datetime.today() #.strftime(date_format)
			cummulative_hours = 0
			for document in user_pending_works:
				reference_name = document.get("reference_name")
				reference_doctype = document.get("reference_doctype")
				workflow_state = document.get("workflow_state")
				creation = document.get("creation")
				creation_date =  creation #.strftime(date_format)
				delta = today_date - creation_date
				delay_days = delta.days
				delay_time_narrative = ""
				if(delay_days == 0):
					delay_hours = int(delta.seconds/3600)
					cummulative_hours += delay_hours
					delay_time_narrative = f"{delay_hours} hours"
				else:
					cummulative_hours += delay_days * 24
					delay_time_narrative = f"{delay_days} days"
				email_message += f"<tr><td>{reference_doctype}</td><td>{reference_name}</td><td>{workflow_state}</td><td align='right'>{delay_time_narrative}</td></tr>"
			email_message += "</table><br/><hr>Your prompt action will alleviate more delays! Login and take action here: https://portal.mtrh.go.ke. <hr>Thank you!"
			formatted_date = today_date.strftime(date_format)
			subject = f"ERP Intray - {formatted_date}"
			send_notifications(user_email, email_message, subject)
			average_hours = int(cummulative_hours/no_of_documents)
			sms_to_user = f"You have {no_of_documents} pending documents to action on the portal. Average delay in action: {average_hours} hours. Check your actions here:  https://bit.ly/2F8E18L"
			phone = get_user_phonenumber(user_email)
			if phone:
				data = {
					"phone": phone,
					"message": sms_to_user
				}
				incoming_payload =[]
				incoming_payload.append(data.copy())
				send_sms_alert(json.dumps(incoming_payload))
	return user_pending_counts

def send_notifications(recipients, message, subject):
	email_args = {
		"recipients": [recipients],
		"message": _(message),
		"subject": subject
	}
	enqueue(method=frappe.sendmail, queue='short', timeout=300, **email_args)
def project_budget_submit(doc , state):
	hand_in_budget = doc.get("hand_in_budget")
	if hand_in_budget:
		project = doc.get("name")
		budget_exists = frappe.db.sql(f"SELECT name, docstatus FROM `tabBudget` WHERE project ='{project}'",as_dict=True)
		submitted_budgets =[x for x in budget_exists if x.get("docstatus")=="1"]
		if len(submitted_budgets) > 1 :
			frappe.throw("Sorry, this project already has an approved budget")
			return
		frappe.db.delete("Budget", {"project":project})
		i_table = doc.get("procurement_plan_items")
		budget_items =[{x.get("expense_account") : x.get("amount")}\
			for x in i_table ]
		#frappe.msgprint(budget_items)
		#return budget_items
		import collections, functools, operator 
		reduced_budget_dict = dict(functools.reduce(operator.add, 
			map(collections.Counter, budget_items))) 
		tobereturned = make_budget("Project", project, reduced_budget_dict)
		doc.flags.ignore_permissions=True
		doc.run_method("set_missing_values")
		doc.set("status","Pending Budget Approval")
		doc.set("budget_submitted", True)
		doc.set("hand_in_budget", False)
		
		return tobereturned
def make_budget(dimension, dimension_name, items):
	budget = frappe.get_doc({
		"doctype": "Budget",
		"budget_against" :  dimension,
		"cost_center" : dimension_name if dimension =="Cost Center" else None,
		"department" : dimension_name  if dimension =="Department" else None,
		"project" : dimension_name  if dimension =="Project" else None,
		#employee_department = frappe.db.get_value("Employee",{"user_id":frappe.session.user},"department")
		"fiscal_year" : get_fiscal_year(today())[0],
		"company" : frappe.defaults.get_user_default("Company"),
		"action_if_annual_budget_exceeded" : "Stop",
		"action_if_accumulated_monthly_budget_exceeded" : "Ignore"
	}) 
	for k in items:
		budget.append("accounts", {
			"account": k,
			"budget_amount": items.get(k)
		})
	
	budget.flags.ignore_permissions=True
	budget.flags.ignore_links=True
	#budget.run_method("set_missing_values")
	budget.insert()
	return budget
@frappe.whitelist()
def recall_budget(dimension, dimension_name):
	if dimension == "Project":
		budget_exists = frappe.db.sql(f"SELECT name, docstatus FROM `tabBudget` WHERE project ='{dimension_name}'",as_dict=True)
		submitted_budgets =[x for x in budget_exists if x.get("docstatus")=="1"]
		if len(submitted_budgets) > 1 :
			frappe.throw("Sorry, the budget for this project has already been approved and cannot be recalled. Ask for cancellation to be able to amend.")
			return
		frappe.db.delete("Budget", {"project":dimension_name})
		frappe.db.set_value("Project", dimension_name, "budget_submitted", False)
		frappe.msgprint(_("The budget for the project has been recalled successfully."))
		return
def project_budget_approved(doc , state):
	frappe.db.set_value("Project", doc.get("project"), "status", "Budget Approved")
@frappe.whitelist()
def update_sq(docname=None):
	docname = 'PUR-SQTN-2020-00002'
	doc = frappe.get_doc("Supplier Quotation", docname)

	
	#total_taxes_and_charges
	frappe.db.sql(f"UPDATE `tabSupplier Quotation` SET  taxes_and_charges=0.0,\
		total_taxes_and_charges= 0.0 WHERE name ='{docname}' ")

	frappe.db.sql(f"DELETE FROM  `tabPurchase Taxes and Charges`  WHERE parent ='{docname}'")

	frappe.db.sql(f"UPDATE `tabSupplier Quotation Item` SET rate = 62366.00  WHERE parent ='{docname}' ")

def log_time_to_action(doc, state):
	#VALIDATE THAT IT IS A WORKFLOW TRANSITION.
	workflow_name = get_workflow_name(doc.get('doctype'))
	if not workflow_name:
		return
	new_workflow_state = get_doc_workflow_state(doc)
	if not new_workflow_state:
		return
	old_workflow_state = frappe.db.get_value(doc.get('doctype'), doc.get('name'), 'workflow_state') if doc.get('workflow_state') else None
	if (old_workflow_state and new_workflow_state) and old_workflow_state != new_workflow_state:
		#WORKFLOW STATE CHANGED. LETS PROCEED.
		actions = frappe.db.get_all('Workflow Action',
			filters={
				"reference_name": doc.get('name'),
				"workflow_state": old_workflow_state
			},
			fields=["name", "user", "reference_doctype", "creation"],
			as_list=False
		)
		for action in actions:
			now = datetime.now()
			when_created = action.get("creation")
			diff_in_seconds = int(frappe.utils.data.time_diff_in_seconds(now, when_created))
			diff_in_hours = int(frappe.utils.data.time_diff_in_hours(now, when_created))
			time_to_action = frappe.get_doc({
				"doctype": "Time to Action",
				"time_actioned" :  frappe.utils.data.now_datetime(),
				"user" : action.get("user"),
				"reference_name" : doc.get('name'),
				"reference_doctype" : action.get("reference_doctype"),
				"workflow_state" : old_workflow_state,
				"time_to_action" : diff_in_seconds, 
				"hours_action": diff_in_hours
			})
			time_to_action.flags.ignore_permissions=True
			time_to_action.flags.ignore_links=True
			time_to_action.insert()
	return

@frappe.whitelist()
def create_user(employee, user = None, email=None):
	emp = frappe.get_doc("Employee", employee)

	employee_name = emp.employee_name.split(" ")
	middle_name = last_name = ""

	if len(employee_name) >= 3:
		last_name = " ".join(employee_name[2:])
		middle_name = employee_name[1]
	elif len(employee_name) == 2:
		last_name = employee_name[1]

	first_name = employee_name[0]

	if email:
		emp.prefered_email = email

	user = frappe.new_doc("User")
	user.update({
		"name": emp.employee_name,
		"email": emp.prefered_email,
		"enabled": 1,
		"first_name": first_name,
		"middle_name": middle_name,
		"last_name": last_name,
		"gender": emp.gender,
		"birth_date": emp.date_of_birth,
		"phone": emp.cell_number,
		"bio": emp.bio
	})
	user.flags.ignore_permissions = True
	user.insert()
	return user.name
@frappe.whitelist()
def return_applicable_document_template(doctype):
	return frappe.db.sql(f"""SELECT DISTINCT applicable_for\
		 FROM `tabDocument Template Doctype` WHERE parent ='{doctype}'""", as_dict=True)
def return_fields_to_capitalize():
	return ["item_name","item_group_name","employee_name"]
def capitalize_essential_fields(doc , state):
	fields_to_capitalize = return_fields_to_capitalize()
	if fields_to_capitalize:
		for d in fields_to_capitalize:
			if frappe.get_meta(doc.get("doctype")).has_field(d):
				doc.set(d, doc.get(d).upper())
def enforce_variants(doc, state):
	if not doc.get("variant_of"):
		if not doc.get("has_variants") and doc.get("disabled")==False:
			frappe.throw(_("Error. Kindly ensure that this item has at least one variant"))
def enforce_unique_item_name(doc, state):
	if frappe.db.count('Item', {'item_name': doc.get("item_name").upper(), "item_code":["!=", doc.get("name")]}) > 0:
		item_name = doc.get("item_name").upper()
		if doc.get("disabled")==True:
			pass
		else:
			frappe.throw(f"Sorry {item_name} already exists!")
	return