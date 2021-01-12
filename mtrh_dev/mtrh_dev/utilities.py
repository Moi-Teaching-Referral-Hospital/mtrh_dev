import frappe, json
from frappe import _
from frappe.utils.file_manager import check_max_file_size, get_content_hash, get_file_name, get_file_data_from_hash
from frappe.utils import get_files_path,cstr ,get_hook_method, call_hook_method, random_string, get_fullname, today, cint, flt, get_url_to_form, strip_html, money_in_words
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
from frappe.utils import nowdate, getdate, add_days, add_years, cstr, get_url, get_datetime

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
	if sq_doc.get("items"):
		sq_doc.insert()
		raise_po_based_on_direct_purchase(rfq)
		#frappe.msgprint(_("Your submission of Quotation {0} was successful. You will be alerted once it is opened and evaluated.").format(sq_doc.name))
		return sq_doc.name
	else:
		return "NO QUOTE"
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
	#frappe.msgprint(f"part_no: {part_no}")
	sq_doc.append('items', {
		"item_code": data.item_code,
		"item_name": data.item_name,
		"description": data.description,
		"qty": data.qty,
		"rate": data.rate,
		"attachments": data.attachments,
		"files": data.attachments,
		"supplier_part_no": frappe.db.get_value("Item Supplier", {'parent': data.item_code, 'supplier': supplier}, "supplier_part_no") if data.rate > 0 else "NO QUOTE",
		"warehouse": data.warehouse or '',
		"request_for_quotation_item": data.name,
		"request_for_quotation": data.parent
	})

def cleanup_sq(doc, state):
	items = doc.get("items")
	total = 0.0
	for d in items:
		if d.get("supplier_part_no") == "NO QUOTE":
			d.rate = 0.0
			d.amount = 0.0
			total += d.rate * d.amount
	doc.base_grand_total = doc.grand_total = doc.rounded_total = doc.total = doc.base_total = doc.net_total = total
	doc.in_words = money_in_words(total)
	doc.run_method("set_missing_values")
	#doc.save(ignore_permissions = True)
	return
def cleanup_item_idx(doc, state):
	i =0
	#frappe.msgprint("Realigning row indexes")
	for d in doc.get("items"):
		i += 1
		d.idx = i
	doc.notify_update
#====================================================================================================================================================
# ADD IMPORTANT ACTION LOGS TO DOCUMENTS. THESE LOGS CAN THEN BE AVAILABLE ON PRINT MODE TO TRACK APPROVALS AND DECISIONS ON DOCUMENTS.
#====================================================================================================================================================
def process_workflow_log(doc, state): 
	this_doc_workflow_state = ""
	the_decision =""
	if state == "before_save":
		workflow = get_workflow_name(doc.get('doctype'))
		if not workflow: 
			this_doc_workflow_state ="Draft"
		else:
			this_doc_workflow_state = get_doc_workflow_state(doc)
			if is_workflow_action_already_created(doc):
				if this_doc_workflow_state == "Draft":
					docs_that_may_be_send_to_draft = ["Material Request", "Request for Quotation", "Purchase Order"\
						, "Procurement Professional Opinion", "Bulk SMS Dispatch", "Procurement Plan", "Tender Quotation Award"\
							,"Fleet Request Manifest", "Prequalification", "Purchase Invoice", "Purchase Receipt"\
								,"Payment Request"]
					if doc.get('doctype') in docs_that_may_be_send_to_draft:
						#REMOVE ALL WORKFLOW ACTION STATES.
						doc_name = doc.get("name")
						action_docs = frappe.db.sql(f"""SELECT name FROM `tabWorkflow Action` WHERE reference_name = '{doc_name}' """, as_dict=True)
						documents =[frappe.get_doc("Workflow Action", x.get("name")) for x in action_docs]
						flagged_documents =[]
						for x in documents:
							x.flags.ignore_permissions = True
							flagged_documents.append(x)
						list(map(lambda x: x.delete(), flagged_documents))
				#CLEAR ALL WORKFLOW ACTIONS THAT HAVE ALREADY BEEN COMPLETED ON THIS DOCUMENT IF THE NEW WORKFLOW ACTION IS DRAFT
				#if this_doc_workflow_state == "Draft":
					#doc_name = doc.get("name")
					#frappe.db.sql(f"""DELETE FROM `tabWorkflow Action` WHERE reference_name = '{doc_name}' AND name != '1'""")
				return
			if not this_doc_workflow_state:
				this_doc_workflow_state ="Draft"
		the_decision = "Actioned To: " + this_doc_workflow_state
		
	elif state == "before_submit":
		the_decision = "Document Approved!"
		
		#LET THE USER GIVE A MEMO FOR APPROVING DOCUMENT.
		#comment_on_action(doc, state)
	elif state == "on_cancel":
		the_decision = "Document Cancelled/Revoked!"
		
		#LET THE USER GIVE A MEMO FOR CANCELLING DOCUMENT.
		#comment_on_action(doc, state)
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
		docs_that_may_be_send_to_draft = ["Material Request", "Request for Quotation", "Purchase Order"\
			, "Procurement Professional Opinion", "Bulk SMS Dispatch", "Procurement Plan", "Tender Quotation Award"\
				,"Fleet Request Manifest", "Prequalification", "Purchase Invoice", "Purchase Receipt"\
					"Payment Request"]
		if doc.get('doctype') in docs_that_may_be_send_to_draft:
			#REMOVE ALL WORKFLOW ACTION STATES.
			doc_name = doc.get("name")
			action_docs = frappe.db.sql(f"""SELECT name FROM `tabWorkflow Action` WHERE reference_name = '{doc_name}' """, as_dict=True)
			documents =[frappe.get_doc("Workflow Action", x.get("name")) for x in action_docs]
			flagged_documents =[]
			for x in documents:
				x.flags.ignore_permissions = True
				flagged_documents.append(x)
			list(map(lambda x: x.delete(), flagged_documents))
			#frappe.db.sql(f"""DELETE FROM `tabWorkflow Action` WHERE reference_name = '{doc_name}' AND name != '1'""")
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
	if doc.get("action_log") is None:
		return
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
def sms_delivery_status_update_cron():
	sent  = frappe.db.sql("""SELECT name FROM `tabSMS Log` WHERE status ='Sent' and creation >= '2020-11-25'""",as_dict=True)
	docs = [frappe.get_doc("SMS Log", x.get("name")) for x in sent]
	#mark_sms_delivery_status(doc)
	list(map(lambda x: mark_sms_delivery_status(x), docs))
def mark_sms_delivery_status(doc):
	if not doc.sent_to:
		return
	if "sending success" in doc.sent_to:
		doc.status ="Delivered"
	else:
		doc.status="Undelivered"
	doc.flags.ignore_permissions =True
	doc.save()
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
	if sms_names and sms_names is not None:
		sms_names_str = '('+','.join("'{0}'".format(i) for i in sms_names)+')'
		sql_upd_sms = f"UPDATE `tabSMS Log` SET status = 'Processed' WHERE `name` IN {sms_names_str}"
		frappe.db.sql(sql_upd_sms)
	return
def test_bulk_sms():
	contacts_arr =["0722810063"]
	message ="Testing bulk SMS"
	incoming_payload = [
		 {
			"phone": x,
			"message": message
		} for x in contacts_arr]
	send_sms_alert(json.dumps(incoming_payload))	
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
	department = doc.get("department")
	employee_number = doc.get("employee_number")
	'''if not frappe.db.exists({"doctype":"User Permission",
							"user":userid,
							"allow":"Department",
							"for_value":department}):'''
	clear_user_permissions(userid,"Department")
	clear_user_permissions(userid,"Leave Rota")
	clear_user_permissions(userid,"Leave Application")
	#frappe.get_doc()
	fullname = doc.get("employee_name")
	if department:
		if userid:
			frappe.get_doc(dict(
				doctype='User Permission',
				user=userid,
				allow="Department",
				for_value=department,
				apply_to_all_doctypes=0,
				applicable_for="Material Request"
			)).insert(ignore_permissions=True)
			frappe.get_doc(dict(
				doctype='User Permission',
				user=userid,
				allow="Department",
				for_value=department,
				apply_to_all_doctypes=0,
				applicable_for="Leave Rota"
			)).insert(ignore_permissions=True)
			if not is_manager(): 
				frappe.get_doc(dict(
					doctype='User Permission',
					user=employee_number,
					allow="Employee",
					for_value=userid,
					apply_to_all_doctypes=0,
					applicable_for="Leave Application"
				)).insert(ignore_permissions=True)
			frappe.msgprint("User {0} - {1} has been assigned to {2}".format(userid, fullname, department))

			#THERE IS A FRAPPE ERROR WHERE USERS ASSIGNED TO TREE CAN'T SEE IMMEDIATE CHILD DEPARTMENTS.
			#GET CHILD NON TREE DEPARTMENTS
			child_non_group_departments = frappe.db.get_list("Department", filters={"is_group": False, "parent_department": department}, fields=["name"])
			for child in child_non_group_departments:
				frappe.get_doc(dict(
					doctype='User Permission',
					user=userid,
					allow="Department",
					for_value=child.get("name"),
					apply_to_all_doctypes=0,
					applicable_for="Material Request"
				)).insert(ignore_permissions=True)
				frappe.get_doc(dict(
					doctype='User Permission',
					user=userid,
					allow="Department",
					for_value=child.get("name"),
					apply_to_all_doctypes=0,
					applicable_for="Leave Rota"
				)).insert(ignore_permissions=True)
		else:
			frappe.msgprint("Department permissions have not been applied since the user does not have a log in account.")
	else:
		return
		#frappe.throw("Please ensure that user has log in credentials and is allocated to a department")
def is_manager(user = None):
	if not user: user = frappe.session.user
	return "Chief Executive Officer" in frappe.get_roles(user)\
		 or "Head of Department" in frappe.get_roles(user)\
			 or "Head of Directorate" in frappe.get_roles(user)\
				 or "Senior Director" in frappe.get_roles(user)
def process_comment(doc,state):
	if doc.reference_doctype and doc.reference_name and doc.content:
		sender_fullname = get_fullname(frappe.session.user)
		mentions = extract_mentions(doc.content)
		if not mentions:
			#DISABLED FOR NOW: 
			return
			#ALERT ALL USERS WHO HAVE EVER ACTIONED ON THIS DOCUMENT.
			if  doc.get("comment_type") == "Comment" and doc.get("owner")!="Administrator":
				list_of_action_users = frappe.db.get_all("Comment", filters = {"reference_name": doc.reference_name, "comment_type": ["IN", ["Workflow","Created","Edit","Shared","Comment"]]}, fields=["comment_email"])
				emails =[x.get("comment_email") for x in list_of_action_users]
				unique_list = list(dict.fromkeys(emails))
				if frappe.session.user in unique_list:
					unique_list.remove(frappe.session.user)
				email_message = doc.content
				docname = doc.get("reference_name")
				subject = f"Comment Alert - {docname} from {sender_fullname}"
				list(map(lambda x: send_notifications(x, email_message, subject, doc.reference_doctype, doc.reference_name),unique_list))
			return
		
		#title = get_title(doc.reference_doctype, doc.reference_name)
		reference_document = frappe.get_doc(doc.reference_doctype, doc.reference_name)
		recipients = [frappe.db.get_value("User", {"enabled": 1, "name": name, "user_type": "System User", "allowed_in_mentions": 1}, "email")
			for name in mentions]
		"""notification_message = _('''{0} mentioned you in a comment in {1} [{2}] please log in to your portal or corporate email account view and respond to the comment''')\
			.format(sender_fullname, doc.reference_doctype, title)"""
		data = doc.content
		"""import re
		nosp = re.compile('\ufeff.*\ufeff')#REMOVES SPECIAL CHARACTERS @TAGS
		p_data = re.sub(nosp, '', data)
		clean = re.compile('<(.*?)>') #REMOVES ALL HTML LIKE TAGS I.E <>
		filtered_content = re.sub(clean, '', p_data)"""
		filtered_content = strip_html(data)
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
def get_link_to_form_new_tab(doctype, name, label=None):
	if not label: label = name

	return """<a target="_blank" href="{0}">{1}</a>""".format(get_url_to_form(doctype, name), label)
def get_attachment_urls(docname):
	if not isinstance(docname, list):
		docname =[docname]
	if not docname: return
	refname_q = '('+','.join("'{0}'".format(i) for i in docname)+')'
	attachments_list_query =f"""SELECT file_url, file_name FROM `tabFile`\
		WHERE attached_to_name IN {refname_q}"""
	attachments_list = frappe.db.sql(attachments_list_query, as_dict=True)
	urls =["""<a target="_blank" href="{0}">{1}</a>""".format(x.get("file_url"), x.get("file_name")) for x in attachments_list]
	unique_urls = list(dict.fromkeys(urls))
	return unique_urls
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
	pl = run(report_name, filters, user="Administrator")
	#need = []
	#if pl.get('result') and pl.get('result')[0]:
	filtered_pl = pl.get('result')
	filtered_pl.pop()
	need  = [b for b in filtered_pl if b.get("Account") == account] #[[...]]
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
		single_row = list(need[0].values())

		data_to_return['q_budget'] = single_row[quarter_budget]
		data_to_return['q_actual'] = single_row[quarter_actual]
		data_to_return['q_commit'] = single_row[quarter_commit]
		data_to_return['q_balance'] = single_row[quarter_balance]
		data_to_return['t_budget'] = single_row[18]
		data_to_return['t_actual'] = single_row[19]
		data_to_return['t_commit'] = single_row[20]
		data_to_return['t_balance'] = single_row[21]
	return data_to_return
def validate_budget_exists(doc, state):
	if doc.get("doctype")=="Material Request" and doc.get("purpose") in ["Material Issue","Material Transfer"]:
		return
	department = doc.get("items")[0].get("department")
	project = doc.get("project")
	dimension, dimension_name = "Department", department
	if project: dimension, dimension_name ="Project", project
	if frappe.session.user == "Administrator": return #department is None or not department: return #ADDED THIS AFTER ERROR DURING AUTOGENERATION DURING REORDER LEVEL CHECK
	fy = frappe.defaults.get_user_default("fiscal_year")
	if not frappe.get_value("Budget",{str(dimension): dimension_name,"fiscal_year":fy,"docstatus": 1},"name"):
		frappe.throw(f"Sorry, there isn't a budget set up  for {dimension} {dimension_name} Financial Year: {fy}\
		 and as such this expenditure cannot be incurred")
	expense_accounts =[x.get("expense_account") for x in doc.get("items")]
	unique_expense_accounts = list(dict.fromkeys(expense_accounts))
	for d in unique_expense_accounts:
		budget = frappe.get_value("Budget",{dimension: dimension_name,"fiscal_year":fy,"docstatus": 1},"name")
		document = frappe.get_doc("Budget", budget)
		accounts = [x.get("account") for x in document.get("accounts")]
		if d not in accounts:
			frappe.throw(f"""Sorry, there is no Approved Votebook Allocation for {d} in {dimension} {dimension_name}""")
	return
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
	
	pl = run(report_name, filters, user="Administrator")
	filtered_pl = pl.get('result')
	filtered_pl.pop()
	need  = [b for b in filtered_pl if b.get("Account") == account] #[[...]]
	#need  = [b for b in pl.get('result') if b[1]==account] #[[...]]old
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
		single_row = list(need[0].values())#need[0]
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

		real_quarter_commitment = (vote.get("q_balance") or 0.0) + (amount or 0.0) + total_amount_older_pos
		real_annual_commitment = (vote.get("t_balance") or 0.0) + (amount or 0.0) + total_amount_older_pos
		
		
		#FORMAT THE VOTE BALANCE STATEMENT
		vote_statement = "<b>Vote Balance Statement - {0} - {1}</b></hr><br/><table border='1' width='100%' style='border-collapse: collapse;'>".format(department, account)
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
		#from mtrh_dev.mtrh_dev.tender_quotation_utils import document_dashboard
		#vote_statement+= document_dashboard(document_type, document_name)
		return vote_statement
	elif document_type=="Payment Request":
		#GET ASSOCIATED PURCHASE ORDER.
		doc = frappe.get_doc(document_type, document_name)
		if doc.get("reference_doctype") == "Purchase Invoice":
			associated_invoice = frappe.get_doc("Purchase Invoice", doc.get("reference_name"))
			associated_po = frappe.get_doc("Purchase Order", associated_invoice.get("items")[0].purchase_order)
		elif doc.get("reference_doctype") == "Purchase Order":
			associated_po = frappe.get_doc("Purchase Order", doc.get("reference_name"))
		else:
			return
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
		vote_statement = "<b>Vote Balance Statement - {0} - {1}</b></hr><br/><table border='1' width='100%'  style='border-collapse: collapse;'>".format(department, account)
		vote_statement += "<tr><td><b>Item</b></td><td>Quarter</td><td>Annual</td></tr>"
		vote_statement += "<tr><td><b>Allocation</b></td><td align='right'>{0}</td><td align='right'>{1}</td></tr>".format(quarter_budget, annual_budget)
		vote_statement += "<tr><td><b>Commitments and Expenditure</b></td><td align='right'>{0}</td><td align='right'>{1}</td></tr>".format(quarter_aggregated, annual_aggregated)
		vote_statement += "<tr><td><b>Balance Before</b></td><td align='right'>{0}</td><td align='right'>{1}</td></tr>".format(quarter_balance_before, annual_balance_before)
		vote_statement += "<tr><td><b>This Entry</b></td><td align='right'>{0}</td><td align='right'>{1}</td></tr>".format(this_entry_formatted, this_entry_formatted)
		vote_statement += "<tr><td><b>Balance After</b></td><td align='right'>{0}</td><td align='right'>{1}</td></tr>".format(quarter_balance_after, annual_balance_after)
		vote_statement += "</table>"
		#forcefully_update_doc_field("Purchase Order", doc.get("name"), "vote_balance", vote_statement)
		if not doc.get("vote_statement") and doc.get("docstatus") == 0:
			frappe.db.set_value("Payment Request", doc.get("name"), "vote_statement", vote_statement)
			#doc.set("vote_statement", vote_statement)
			#doc.flags.ignore_permissions = True
			#doc.save()
			#doc.notify_update()
		#from mtrh_dev.mtrh_dev.tender_quotation_utils import document_dashboard
		#vote_statement+= document_dashboard(document_type, document_name)
		return vote_statement
	elif document_type=="Material Request":
		pass
	else:
		return
def daily_pending_work_reminder():
	#GET UNIQUE LIST OF USERS WITH PENDING WORK ON WORKFLOW ACTION TABLE.
	user_pending_counts = frappe.db.get_all('Workflow Action',
		filters = {
			'workflow_state': ['NOT IN', ['%Approved%', '%Cancelled%', 'Approved', 'Cancelled', 'Draft']],#Approved
			'status': ['not like', '%Completed%']
		},
		fields=['count(name) as count', 'user'],
		group_by='user'
	)

	if user_pending_counts and user_pending_counts[0]:
		for user in user_pending_counts:
			user_pending_works = frappe.db.get_all('Workflow Action',
				filters = {
					'workflow_state': ['NOT IN', ['%Approved%', '%Cancelled%', 'Approved', 'Cancelled', 'Draft']],
					'status': ['not like', '%Completed%'],
					'user': user.get("user")
				},
				fields=['reference_name', 'reference_doctype', 'workflow_state', 'creation']
			)
			no_of_documents = user.get("count")
			user_email = user.get("user")
			email_message = f"Dear Sir/Madam,<br/>There are {no_of_documents} items which are pending in your in-tray in the ERP. It is advised that prompt action be taken on the documents to improve efficieny. The list of items is shown below. You can also find all your pending work at all times here: https://bit.ly/2F8E18L <br/>"
			email_message += f"<b>Pending Items for - {user_email}: </b><hr><table border='1' width='100%'  style='border-collapse: collapse;' >"
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

def send_notifications(recipients, message, subject, doctype = None, docname = None):
	if not isinstance(recipients, list):
		recipients =[recipients]

	email_subject = strip_html(subject)
	if doctype is not None:
		this_doc = frappe.get_doc(doctype, docname)
		doc_link = get_url_to_form(doctype, docname)
		
		email_args = {
			"recipients": recipients,
			"subject": email_subject,
			"template": "new_notification",
			"header": [subject, 'orange'],
			"args" : {
				"body_content": subject,
				"description": _(message),
				"document_type": doctype,
				"document_name": docname,
				"doc_link": doc_link
			}
		}
	else:
		email_args = {
			"recipients": recipients,
			"subject": email_subject,
			"template": "new_notification",
			"header": [email_subject, 'orange'],
			"args" : {
				"body_content": email_subject,
				"description": _(message)
			}
		}
	enqueue(method=frappe.sendmail, queue='long', timeout=300, **email_args)
def submit_project_budget():
	print("Checking for un-submitted project budgets")
	unsubmitted_project_budgets = frappe.db.sql(f"""SELECT name FROM `tabProject`\
		 WHERE docstatus =1 AND hand_in_budget=0""", as_dict =1)
	docs =[frappe.get_doc("Project", x.get("name")) for x in unsubmitted_project_budgets]
	print("Found",len(docs))
	if docs:
		list(map(lambda x: project_budget_submit(x,"Submitted"),docs))
def project_budget_submit(doc , state):
	hand_in_budget = doc.get("docstatus")
	
	if hand_in_budget ==1:
		frappe.msgprint("Preparing to post budget..")
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
		is_approved = doc.get("budget_is_approved_externally")
		import collections, functools, operator 
		reduced_budget_dict = dict(functools.reduce(operator.add, 
			map(collections.Counter, budget_items))) 
		tobereturned = make_budget("Project", project, reduced_budget_dict,is_approved)
		doc.flags.ignore_permissions=True
		doc.run_method("set_missing_values")
		#doc.set("status","Pending Budget Approval")
		#doc.db_set("budget_submitted", True)
		doc.db_set("hand_in_budget", doc.get("docstatus"))
		#doc.set("hand_in_budget", False)
		frappe.msgprint("Budget has been posted..")
		return tobereturned
def make_budget(dimension, dimension_name, items, is_approved=False):
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
	if is_approved:
		budget.submit()
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
	if doc.get("project"):
		frappe.db.set_value("Project", doc.get("project"), "status", "Budget Approved")
		frappe.db.set_value("Project", doc.get("project"), "budget_submitted", True)
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
def return_fields_to_capitalize(doc):
	meta  = meta = frappe.get_meta(doc.get("doctype"))
	fieldnames =[x.get("fieldname") for x in meta.get("fields") \
		 if x.get("fieldtype") in ["Data"] and x.get("fieldname") not in\
			  ["status","workflow_state","abbr","attribute_name","abbreviation", "name"]]
	#frappe.throw(fieldnames)
	return fieldnames
def capitalize_essential_fields(doc , state):
	#frappe.throw(doc.get("doctype"))
	#return
	#allowed_to_capitalize = frappe.db.get_value("DocType",doc.get("doctype"),"module") in ["Buying",\
	#	"Fleet Management System","Stock","Library Management","Fleet Management System"]
	#if not allowed_to_capitalize or "Setting" in doc.get("doctype"):
	#	return
	#else:
	fields_to_capitalize = return_fields_to_capitalize(doc)
	if fields_to_capitalize:
		for d in fields_to_capitalize:
			if doc.get(d):
				doc.set(d, str(doc.get(d)).upper())
	return
def enforce_variants(doc, state):
	if not doc.get("variant_of"):
		if not doc.get("has_variants") and doc.get("disabled")==False:
			if frappe.session.user =="Administrator":
				return
			frappe.throw(_("Error. Kindly ensure that this item has at least one variant"))
def enforce_unique_item_name(doc, state):
	if frappe.db.count('Item', {'item_name': doc.get("item_name").upper(), "disabled": False ,"item_code":["!=", doc.get("name")]}) > 0:
		item_name = doc.get("item_name").upper()
		if doc.get("disabled")==True:
			pass
		else:
			frappe.throw(f"Sorry {item_name} already exists!")
	return
def append_attachments_to_file(doc, state):
	#thedoctype = doc.get("doctype")
	#frappe.msgprint(f"Doctype to save file - {thedoctype}")
	if doc.get("doctype") in ["Email Account", "Email Queue", "File", "DefaultValue", "User", "Comment", "Version", "DocShare", "Error Log"]:
		return
	meta  = meta = frappe.get_meta(doc.get("doctype"))
	fieldnames =[x.get("fieldname") for x in meta.get("fields") \
		 if x.get("fieldtype") in ["Attach","Attach Image"]]
	if fieldnames:
		attachment_urls = [doc.get(x) for x in fieldnames if doc.get(x)]
		from frappe.utils.file_manager import save_url
		for url in attachment_urls:
			filedict = frappe.db.get_value("File",{"file_url": url}\
				,['file_name','folder'],as_dict=1)
			if filedict is not None:
				save_url(url, filedict.get("file_name"), doc.get("doctype"),\
					doc.get("name"), filedict.get("folder"),True,None)
	return

def process_email_to_sms(doc, state):
	the_email = doc.get("message")
	recipients = doc.get("recipients")

	#SEND OUT SMS IF THE EMAIL CONTAINS OTP CODE
	if recipients[0]:
		import re
		code = re.search(r"\*\*([0-9]{6})\*\*", the_email)
		if code:
			the_code = code.group(1)
			notification_message = f"Your login Code: {the_code} \n This verifies your digital signature!"
			#schedule_sms_to_user(recipients[0].recipient, notification_message)
			#THERE IS NEED TO SEND SMS IMMEDIATELY.
			incoming_payload = [{
				"phone": get_user_phonenumber(recipients[0].recipient),
				"message": notification_message
			}]
			#incoming_payload.append(data.copy())
			send_sms_alert(json.dumps(incoming_payload))
def create_draft_leave_rotas():
	enabled_leave_year = frappe.db.get_value("Leave Year", {"enabled":1}, as_dict=True).name
	if enabled_leave_year:
		departments = frappe.db.sql(f"""SELECT name FROM `tabDepartment`\
			 WHERE name NOT IN (SELECT department FROM `tabLeave Rota` WHERE leave_year ='{enabled_leave_year}')""", as_dict=1)
		unique_departments = [d.get("name") for d in departments]

		for d in departments:
			department_name = d.get("name")
			if department_name in unique_departments:
				frappe.get_doc(dict(
						doctype ='Leave Rota',	
						department = d.get("name"),
						leave_year = enabled_leave_year
					)).insert(ignore_permissions=True)
			user_list = frappe.db.sql(f"""SELECT user_id FROM `tabEmployee`\
				 WHERE department ='{department_name}'""",as_dict=True)
			users = [x.get("user_id") for x in user_list]
			#print(users)
			#apply_department_permission_on_leave_rota(users, d)
def apply_department_permission_on_leave_rota():
	user_list = frappe.db.sql(f"""SELECT user_id , department FROM `tabEmployee`\
				 WHERE status = 'Active' and user_id is not null""",as_dict=True)
	for d in user_list:
		if d and d.user_id and d.get("department"):
			frappe.get_doc(dict(
				doctype='User Permission',
				user=d.get("user_id"),
				allow="Department",
				for_value= d.get("department"),
				apply_to_all_doctypes=0,
				applicable_for="Leave Rota"
			)).insert(ignore_permissions=True)
def apply_buyer_section(doc, state):
	pass
@frappe.whitelist()
def reassign_workflow_items(current_user, new_user, workflow, make_copy = None, doctype = None):
	if doctype:
		#BE SPECIFIC TO ONLY THE DOCTYPE.
		if not make_copy:
			#ONLY COPY AND DON'T DELETE FOR CURRENT USER.
			actions = frappe.db.get_all('Workflow Action',
				filters={
					"reference_doctype": doctype,
					"workflow_state": workflow,
					"user": current_user
				},
				fields=["reference_name", "status"],
				as_list=False
			)
			workflow_docs_list = '('+','.join("'{0}'".format(i) for i in [x.get("reference_name") for x in actions])+')'
			if workflow_docs_list: frappe.db.sql(f"UPDATE `tabWorkflow Action` set user = '{new_user}' where user = '{current_user}' and reference_name IN {workflow_docs_list} and name !='1';")
			"""for action in actions:
				frappe.get_doc(dict(
					doctype = 'Workflow Action',
					user = new_user,
					reference_doctype = doctype,
					reference_name = action.get("reference_name"),
					status = action.get("status"),
					workflow_state = workflow
				)).insert(ignore_permissions=True)"""
def validate_duplicate_budget(doc, state):
	department = doc.get("department")
	fy = doc.get("fiscal_year")
	docname = doc.get("name")
	if department:
		if frappe.db.sql(f"""select name from `tabBudget` WHERE department ='{department}'\
			 AND fiscal_year ='{fy}' AND docstatus !='2' AND name !='{docname}'""") :
			frappe.throw(f"Sorry there is an existing budget for {department} in {fy}")			
@frappe.whitelist()
def form_start_import_custom(docname): 
	args = { "data_import": docname }
	from frappe.core.doctype.data_import.data_import import start_import
	enqueue(method=start_import, queue='short', timeout=300, **args)
	return
@frappe.whitelist()
def imported_leave_balance(pf_number):
	d = frappe.db.get_value("Leave Balance Migration",\
		{"pf_number":pf_number},"leave_balance") or 0
	return d if d < 15 else 15
def validate_procurement_plan_exists(doc,state):
	department = doc.get("department_name")
	fy = doc.get("fiscal_year")
	docname = doc.get("name")
	if department:
		if frappe.db.sql(f"""select name from `tabProcurement Plan` WHERE department_name ='{department}'\
			 AND fiscal_year ='{fy}' AND docstatus !='2' AND name !='{docname}'""") :
			frappe.throw(f"Sorry there is an existing procurement plan for {department} in {fy}")	
def merge_procurement_plan():
	parent ='PROC-INFORMATION & COMMUNICATION TECHNOLOGY DEPARTMENT - MTRH-2020-2021-11816-3'
	doc = frappe.get_doc("Procurement Plan", parent)
	department = doc.get("department_name")
	fy = doc.get("fiscal_year")
	idx = len(doc.get("procurement_item"))
	items =[x.get("item_code") for x in doc.get("procurement_item")]
	to_be_cancelled = frappe.db.sql(f"""select name from `tabProcurement Plan`\
		 WHERE department_name ='{department}'\
			 AND fiscal_year ='{fy}' AND docstatus !='2' AND name !='{parent}'""", as_dict=True) 
	for d in to_be_cancelled:
		this_parent = d.get("name")
		document = frappe.get_doc("Procurement Plan", d.get("name"))
		for j in document.get("procurement_item"):
			idx += 1
			item_code = j.get("item_code")
			if item_code not in items:
				sql = f"""UPDATE `tabProcurement Plan Item` set idx ='{idx}', parent ='{parent}' WHERE\
					item_code ='{item_code}' AND parent ='{this_parent}' and name !=''"""
				frappe.db.sql(sql)
		document.flags.ignore_permissions = True
		#frappe.cancel_doc(document)
	return
def cascade_item_default():
	is_group_list = frappe.db.sql(f"""SELECT name FROM `tabItem Group` WHERE is_group=1 and name = 'DRUGS'""", as_dict=True)
	if is_group_list:
		group_docs =[frappe.get_doc("Item Group", x.get("name")) for x in is_group_list]
		for d in group_docs:
			parent = d.name
			parent_defaults = d.get("item_group_defaults")[0]
			child_groups = frappe.db.sql(f"""SELECT name FROM `tabItem Group` WHERE parent_item_group ='{parent}'""", as_dict=True)
			child_docs = [frappe.get_doc("Item Group", x.get("name")) for x in child_groups]
			list(map(lambda x: apply_group_defaults(x, parent_defaults), child_docs))
def cascade_item_default_hook(doc,state):
	#IF ONE IS NOT ADMINISTRATOR AND THEY ARE TRYING TO PLACE THIS GROUP ON THE ROUTE, THROW ERROR. ONLY ADMIN SHOULD DO THIS
	if frappe.session.user != "Administrator" and doc.get("parent_item_group") == "All Item Groups":
		frappe.throw("Please add this group under any of the existing groups and not 'All Item Groups'. Only administrator can create root group")
	if doc.get("is_group"):
		d = doc
		parent =  d.name
		parent_defaults = d.get("item_group_defaults")[0]
		child_groups = frappe.db.sql(f"""SELECT name FROM `tabItem Group` WHERE parent_item_group ='{parent}'""", as_dict=True)
		child_docs = [frappe.get_doc("Item Group", x.get("name")) for x in child_groups]
		list(map(lambda x: apply_group_defaults(x, parent_defaults, state), child_docs))
	else:
		return
def apply_group_defaults(doc, defaults=None, state=None):#CONTEXT= ITEM GROUP
	print(doc.name,"is_locked:" , doc.is_locked)
	if doc.is_locked:
		return
	item_group = doc.name
	if defaults:
		frappe.db.sql(f"""DELETE FROM `tabItem Default` WHERE parent ='{item_group}'""")
		doc.append("item_group_defaults",{
			"company": defaults.company,
			"default_warehouse":defaults.default_warehouse,
			"expense_account": defaults.expense_account,
			"default_income_account": defaults.default_income_account
		})
		if not state:
			doc.flags.ignore_permissions = True
			doc.save()
def merge_purchase_order(docname):
	doc = frappe.get_doc("Purchase Order", docname)
	items = [x.get("item_code") for x in doc.get("items")]
	workflow_state, supplier = doc.get("workflow_state"), doc.get("supplier")
	pos = frappe.db.sql(f"SELECT name FROM `tabPurchase Order`\
		 WHERE workflow_state ='{workflow_state}' and supplier ='{supplier}' and name!= '{docname}'", as_dict=True)
	order_docs =[frappe.get_doc("Purchase Order", x.get("name")) for x in pos]
	if not isinstance(order_docs, list) or not order_docs:
		return
	for d in order_docs:
		items2 = [x.get("item_code") for x in d.get("items")]
		items_not_in_this_order = compare_po_items(items,items2, d.get("items"))
def compare_po_items(order1_items, order2_items, po2_child):
	items_not_in_this_order =[]
	for x in order2_items:
		if x not in order1_items:
			items_not_in_this_order.append(x)
	return items_not_in_this_order
@frappe.whitelist()
def raise_project_bq(docname, items):
	try:
		doc = frappe.get_doc("Project", docname)
		items_to_raise = json.loads(items)[0]
		item_codes  = [x for x in items_to_raise] 
		mr_items = doc.get("procurement_plan_items")
		mr_items_to_raise =[x for x in mr_items if x.item_code in item_codes]
		#########
		item_ids_str = '('+','.join("'{0}'".format(i) for i in item_codes)+')'
		department = doc.department
		warehouse, item_group = mr_items_to_raise[0].warehouse, mr_items_to_raise[0].item_group
		material_request = frappe.get_doc({
			"doctype": "Material Request",
			"naming_series":"MAT-REQ-PROJ-.YYYY.-",
			"material_request_type":"Purchase",	
			"is_project": True,
			"company":frappe.defaults.get_user_default("company"),
			"schedule_date":date.today(),
			"item_category": item_group,
			"department":department,
			"reason_for_this_request": f"Project {docname} ",
			"set_warehouse": warehouse,
			"transaction_date":date.today(),
			"requested_by":frappe.session.user,	
			"requester": frappe.session.user,		
			"project": docname			
			#"grand_total": grand_total,
			#"total_request_value":grand_total,
		})
		material_request = append_mr_items(material_request, mr_items_to_raise, docname, department)
		material_request.flags.ignore_permissions = True
		material_request.insert()
		material_request.submit()
		frappe.db.sql(f"""UPDATE `tabProject Procurement Plan Item` SET\
			ordered =1 WHERE parent ='{docname}'\
				 AND item_code in  {item_ids_str}""")
	except Exception as e:
		frappe.throw(f"{e}")
	#########
	doc.notify_update()
	return material_request
def append_mr_items(doc, items, project=None, department=None):
	for item in items:
		unit_price,grand_total = item.rate or 0, item.rate or 0 * item.qty or 0 
		rowdict ={}
		rowdict["item_code"] = item.item_code
		rowdict["item_name"] = item.item_name
		rowdict["qty"] = item.qty
		rowdict["brand"] = item.brand
		rowdict["stock_uom"] = item.stock_uom
		rowdict["uom"] = item.uom
		rowdict["rate"] = unit_price
		rowdict["amount"] = grand_total
		rowdict["conversion_factor"] = item.conversion_factor
		rowdict["schedule_date"] = item.schedule_date
		rowdict["expense_account"] = item.expense_account
		rowdict["department"] = department if department else None
		rowdict["warehouse"] = item.warehouse
		rowdict["stock_qty"] = item.stock_qty
		rowdict["project"] = project if project else None
		doc.append("items", frappe._dict(rowdict))
		#material_request_items = [frappe._dict(rowdict)]
	return compute_mr_totals(doc)
def compute_mr_totals(doc):
	amount =0.0
	for x in doc.get("items"):
		amount += x.get("amount")
	doc.total_request_value = amount
	doc.grand_total = amount
	return doc
def create_leave_allocation_cron():
    la = frappe.db.sql(f"""SELECT DISTINCT parent FROM `tabLeave Rota Employee`\
		 WHERE employee NOT IN (SELECT employee FROM `tabLeave Allocation`)\
		 AND docstatus=true LIMIT 2""", as_dict=True)
    if la:
        approved_leaves = [frappe.get_doc("Leave Rota",x.get("parent")) for x in la]
        list(map(lambda x: x.create_leave_allocations(), approved_leaves))
@frappe.whitelist()
def get_unutilized_leaves(employee=None):
	#if frappe.session.user =="Administrator": return
	if not employee: return
	unapplied_leaves = frappe.db.sql(f"""SELECT name, leave_type, allocated_days,\
		 from_date, to_date FROM `tabLeave Allocation`\
			 WHERE employee ='{employee}' AND applied = false""", as_dict =True)
	return [x.get("name") for x in unapplied_leaves]
def mark_leave_allocation(doc, state):
	if not doc.get("active_leave_rota"): return
	linked_allocation = doc.get("active_leave_rota")
	if state == "after_insert":
		linked_allocation.db_set("applied", True)
	if state in ["before_submit", "on_submit"]:
		linked_allocation.db_set("utilized",True)
		linked_allocation.db_set("applied", True)
def set_leave_to_date(doc,state):
	days = doc.number_of_days
	
	#===================
	date_format ="%Y-%m-%d"
	from datetime import datetime
	applicant_commencement = datetime.strptime(str(doc.from_date), date_format)
	from_date = applicant_commencement.date()
	#===================
	employee = doc.employee
	holiday_list = frappe.get_value("Employee", employee,'holiday_list')
	#if state =="before_save":
	doc.set("to_date", date_by_adding_business_days(from_date, days, holiday_list))
	doc.set("total_leave_days",days)

	#SET THE LEAVE ALLOCATION FOR THIS LEAVE APPLICATION.
	leave_allocations = frappe.db.get_all('Leave Allocation', 
		filters = { 
			'from_date': ('<=', from_date),
			'to_date': ('>=', from_date),
			'employee': employee,
			'leave_type': doc.get("leave_type"),
		},
		fields = ["name", "reliever", "reliever_name", "allocated_days", "from_date", "to_date"]
	)
	if leave_allocations and leave_allocations[0]:
		#applicable_leave_allocation = frappe.get_doc("Leave Allocation", leave_allocations[0].get("name"))
		doc.set("active_leave_rota", leave_allocations[0].get("name"))
		doc.set("reliever", leave_allocations[0].get("reliever"))
		doc.set("reliever_name", leave_allocations[0].get("reliever_name"))
		doc.set("allocated_days", leave_allocations[0].get("allocated_days"))
		doc.set("allocated_from_date", leave_allocations[0].get("from_date"))
		doc.set("allocated_to_date", leave_allocations[0].get("to_date"))
	
	#ASSIGN THE DOCUMENT TO THE NEXT PERSON IN THE WORKFLOW
	user = doc.leave_approver if "Supervisor" in doc.get("workflow_state") else  doc.final_approver
	if "Supervisor" in doc.get("workflow_state") or "Final" in doc.get("workflow_state"):
		if "Final" in doc.get("workflow_state"):
			from erpnext.hr.doctype.leave_application.leave_application import get_leave_approver
			user = get_leave_approver(employee)
		share_and_assign_workflow_action(doc , user)
	else:
		user = doc.leave_approver if "Department" in doc.get("workflow_state") else  doc.final_approver
		doc.flags.ignore_permissions = True
		docname = doc.name
		frappe.db.sql(f"""delete from `tabDocShare` WHERE share_name='{docname}' and name !='';""")
		#frappe.share.remove(doc.get("doctype"), doc.get("name"), user, ignore_permissions=True)
	
	#IF THE PERSON THE DOCUMENT IS SHARED WITH HAS ROLE OF CEO, FLAG OFF THE DOCUMENT SO THAT IT BYPASSES THE HOD AND GOES TO HR.

def date_by_adding_business_days(from_date, add_days, holiday_list = None):
	import datetime
	if add_days < 1:
		frappe.throw("Sorry non-zero days not allowed")
	business_days_to_add = add_days
	current_date = from_date
	while business_days_to_add > 0:
		current_date += datetime.timedelta(days=1)
		weekday = current_date.weekday()
		if weekday >= 5: # sunday = 6
			continue
		business_days_to_add -= 1
	current_date -= datetime.timedelta(days=1)
	#ADD HOLIDAY
	if holiday_list:
		holiday_doc = frappe.get_doc("Holiday List", holiday_list)
		holidays = [x for x in holiday_doc.get("holidays")]
		count = 0
		for x in holidays:
			if from_date <= x.get("holiday_date") <= current_date:	
				count += 1 	
		if count > 0:
			current_date += datetime.timedelta(days=count)
	return current_date
def share_and_assign_workflow_action(doc, user):
	from frappe.workflow.doctype.workflow_action.workflow_action import create_workflow_actions_for_users
	#frappe.msgprint(f"Applying permissions for {user}")
	workflow_state = doc.get("workflow_state")

	frappe.share.add(doc.get('doctype'), doc.get('name'),\
			user = user, read = 1, write = 1)
	create_workflow_actions_for_users([user],doc)
def apply_global_permissions():
	users =frappe.db.sql(f"""SELECT DISTINCT name FROM `tabEmployee`\
		 WHERE user_id IS NOT NULL""", as_dict=True)
	d = [x.get("name") for x in users]
	if d:
		documents =[frappe.get_doc("Employee", x) for x in d]
		list(map(lambda x: x.save(ignore_permissions=True), documents))
def set_po_requires_aie_holder_approval(doc, state):
	department = doc.get("items")[0].department
	if department:
		doc.set("requires_aie_holder_approval",\
			 frappe.get_doc("Department",department).get("purchase_order_requires_hod_approval"))
@frappe.whitelist()
def apply_for_unscheduled_leave(employee, leavetype, net_leave_days, commencement_date, reliever, supervisor =None):
	#CREATE LEAVE ALLOCATION AND SUBMIT IT
	#if frappe.session.user == "Administrator": frappe.throw("Only employee role is permitted to apply for leave")
	ends = None
	if frappe.get_value("Leave Type",leavetype,"include_holiday"):
		ends = add_days(commencement_date, int(net_leave_days))
		frappe.msgprint(f"""{commencement_date} {ends}""")
	if not ends: frappe.throw("Only permitted for un-scheduled leaves")
	e = frappe.db.get_value("Employee",employee,\
		["name","department","employee_name"])
	employee, department,employee_name =e[0],e[1], e[2]
	lv_doc = frappe.get_doc({
		"doctype": "Leave Allocation",
		"leave_type": leavetype,
		"employee": employee,
		"from_date": commencement_date,
		"to_date": ends,
		"carry_forward": 0,
		"allocated_days": net_leave_days or 0,
		"reliever": reliever,
		"new_leaves_allocated":net_leave_days or 0,
		"total_leaves_allocated": net_leave_days or 0,
		"reliever_is_mandatory": frappe.db.get_value("Department",\
			department,"requires_reliever"),
		})
	lv_doc.flags.ignore_permissions = True
	lv_doc.run_method("set_missing_values")
	lv_doc.insert()
	lv_doc.submit()
	#CREATE LEAVE APPLICATION DRAFT
	# RETURN DOCUMENT FOR Routing
	if lv_doc.name:
		if not supervisor: supervisor = reliever
		lv_app = frappe.get_doc({
			"doctype": "Leave Application",
			"leave_type": leavetype,
			"employee": employee,
			"employee_name": employee_name,
			"department": department,
			"from_date": commencement_date,
			"to_date": ends,
			"allocated_days": net_leave_days or 0,
			"total_leave_days": net_leave_days or 0,
			"number_of_days": net_leave_days or 0,
			"reliever": reliever,
			"immediate_supervisor":supervisor
			})
		lv_app.flags.ignore_permissions = True
		lv_app.run_method("set_missing_values")
		lv_app.insert()
	return lv_app.name
def remove_employee_rights_for_managers():
	employee_users = frappe.db.sql(f"""SELECT name, user_id FROM `tabEmployee`\
		 WHERE user_id IS NOT NULL""", as_dict =True)
	users =[x.get("user_id") for x in employee_users]
	managers =[x for x in users if is_manager(x)]
	remove_employee_permission(managers)
def remove_employee_permission(users):
	users_str = '('+','.join("'{0}'".format(i) for i in users)+')'
	print(managers_str)
	frappe.db.sql(f"""DELETE FROM `tabUser Permission`\
		 WHERE applicable_for='Leave Application' AND user IN {users_str} """)
