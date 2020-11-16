# Copyright (c) 2020 MTRH
# Author: Thomas Mwogi and Salim Mwaura

from __future__ import unicode_literals
import frappe, json
from frappe import _
from mtrh_dev.mtrh_dev.utilities import get_link_to_form_new_tab, get_attachment_urls, get_votehead_balance

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
		to_return+= f"<tr><td>User Purchase Requests:</td><td>{material_rq_links}</td></tr>"
		to_return+= f"<tr><td>Authority to Procure: </td><td>{authority_to_procure}</td></tr>"
		to_return+= f"<tr><td>Opening Report</td><td>{opening_report}</td></tr>"
		to_return+= "</table>"
	elif doctype == "Purchase Order":
		all_linked_documents= []
		all_linked_documents.extend([document.get("name")])
		this_supplier = document.get("supplier")
		doc_items = document.get("items")
		item_array = [x.get("item_code") for x in doc_items]
		item_q_str = '('+','.join("'{0}'".format(i) for i in item_array)+')'

		to_return+= "<h3>Attachments and Linked Documents</h3><table border='1' width='100%' >"
		to_return += "<th>Document</th><th>Link</th>"
		#MATERIAL REQUEST LINK
		material_requests = []
		#material_requests = [x.get("material_request") for x in document.get("items") if x.get("material_request") and x.get("material_request") not in material_requests]
		[material_requests.append(x.get("material_request")) for x in document.get("items") if x.get("material_request") and x.get("material_request") not in material_requests]
		if len(material_requests) > 0:
			mr_links  =[get_link_to_form_new_tab("Material Request", x) for x in material_requests]
			to_return+= f"<tr><td>User Purchase Requests:</td><td>{mr_links}</td></tr>"
		else:
			to_return+= f"<tr><td>User Purchase Requests:</td><td>Done outside this system. Check Attachements</td></tr>"
		supplier_quotations = [x.get("supplier_quotation") for x in document.get("items") if x.get("supplier_quotation")]
		
		#DISPLAY AWARD DOCUMENT - once expiry date has been added, add that verification as well.
		awards = frappe.db.sql(f"""SELECT name, procurement_method, reference_number\
				FROM `tabTender Quotation Award`\
					WHERE item_code IN {item_q_str}""", as_dict=True)
		award_arr = [x.get("name") for x in awards]
		award_links  =[get_link_to_form_new_tab("Tender Quotation Award", x.get("name")) + " [Tender Number: " + x.get("reference_number") + "] " for x in awards]
		all_linked_documents.extend([x.get("name") for x in awards])
		if award_links:
			to_return+= f"<tr><td>Award Document(s): </td><td>{award_links}</td></tr>"
		# PROFESSIONAL OPINION.
		professional_opinion_links = []
		for item in doc_items:
			item_code = item.get("item_code")
			rate = item.get("rate")
			opionion_price_schedule = frappe.db.sql(f"""SELECT parent\
				FROM `tabAward Price Schedule Item`\
					WHERE item_code = '{item_code}' AND rate = '{rate}' AND bidder = '{this_supplier}' """, as_dict=True)
			if opionion_price_schedule:
				all_linked_documents.extend([x.get("parent") for x in opionion_price_schedule])
				professional_opinion_links.extend([get_link_to_form_new_tab("Procurement Professional Opinion", x.get("parent")) + " [Item: " + item_code + "] " for x in opionion_price_schedule])
		if professional_opinion_links:
			to_return+= f"<tr><td>Procurement Professional Opinion(s): </td><td>{professional_opinion_links}</td></tr>"
		
		if len(supplier_quotations) > 0:
			sq_q = '('+','.join("'{0}'".format(i) for i in supplier_quotations)+')'
			quotations_q = frappe.db.sql(f"""SELECT DISTINCT request_for_quotation FROM \
				`tabSupplier Quotation` WHERE name in {sq_q}""", as_dict=True)
			rfqs_arr = [x.get("request_for_quotation") for x in quotations_q]
			rfq_q = '('+','.join("'{0}'".format(i) for i in rfqs_arr)+')'
			professional_opinion_q = frappe.db.sql(f"""SELECT name FROM `tabProcurement Professional Opinion`\
				 WHERE request_for_quotation IN {rfq_q} """,as_dict =True)
			rfq_links  =[get_link_to_form_new_tab("Request for Quotation", x.get("request_for_quotation")) for x in quotations_q]
			if not professional_opinion_links:
				professional_opinion_links = [get_link_to_form_new_tab("Procurement Professional Opinion", x.get("name")) for x in professional_opinion_q]
				to_return+= f"<tr><td>Award Report:	</td><td>{professional_opinion_links}</td></tr>"
			to_return+= f"<tr><td>Authority to Procure: </td><td>{rfq_links}</td></tr>"
		else: 
			externally_generated_ids = [x.get("externally_generated_order")\
				for x in document.get("items") if x.get("externally_generated_order")]
			#frappe.throw(externally_generated_ids)
			if isinstance(externally_generated_ids, list) and externally_generated_ids:
				externally_generated_ids = list(dict.fromkeys(externally_generated_ids))
				attachments = get_attachment_urls(externally_generated_ids)
				if attachments:
					to_return+= f"<tr><td>Scanned (Externally generated order) Document Attachments: </td><td>{attachments}</td></tr>"
		d = get_attachment_urls(all_linked_documents)
		if d:
			to_return+= f"<tr><td>Other Document Attachments: </td><td>{d}</td></tr>"
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
		if d:
			to_return+= f"<tr><td style='white-space: nowrap; font-weight: bold;'>Uploaded Documents (External): </td><td>{d}</td></tr>"
		
		to_return+= "</table>"

	elif doctype == "Payment Request":
		#LINKS APPLY FOR PURCHASE INVOICE REFERENCE DOCUMENTS. REMEMBER TO ADD FOR THE OTHER REFERENCE TYPE DOCUMENTS.
		all_linked_documents= []
		if document.get("reference_doctype") == "Purchase Invoice":
			#LINED PURCHASE INVOICE
			this_invoice_no = document.get("reference_name")
			this_invoice = frappe.get_doc("Purchase Invoice", this_invoice_no)
			all_linked_documents.extend([this_invoice])
			
			linked_purchase_invoices = get_link_to_form_new_tab("Purchase Invoice", this_invoice_no)
			
			purchase_receipts_a = [x.get("purchase_receipt") for x in this_invoice.get("items")]
			purchase_receipts = list(dict.fromkeys(purchase_receipts_a))
			all_linked_documents.extend(purchase_receipts)
			linked_purchase_receipts = [get_link_to_form_new_tab("Purchase Receipt", x) for x in purchase_receipts]

			#LINKED PURCHASE ORDERS
			purchase_orders_list = [x.get("purchase_order") for x in this_invoice.get("items")]
			purchase_orders = list(dict.fromkeys(purchase_orders_list))
			linked_purchase_orders = [get_link_to_form_new_tab("Purchase Order", x) for x in purchase_orders]
			linked_material_requests=[]
			
		elif document.get("reference_doctype") == "Purchase Order":
			invoice_arr = [x.get("invoice_number") for x in document.get("invoices")]
			all_linked_documents.extend(invoice_arr)
			linked_purchase_invoices = [get_link_to_form_new_tab("Purchase Invoice", x) for x in invoice_arr]
			inv_q = '('+','.join("'{0}'".format(i) for i in invoice_arr)+')'
			
			purchase_receipt_q = frappe.db.sql(f"""SELECT DISTINCT purchase_receipt FROM `tabPurchase Invoice Item`\
				WHERE parent IN {inv_q} """, as_dict = True)
			purchase_receipts =[x.get("purchase_receipt") for x in purchase_receipt_q]
			all_linked_documents.extend(purchase_receipts)
			linked_purchase_receipts = [get_link_to_form_new_tab("Purchase Receipt", x.get("purchase_receipt")) for x in purchase_receipt_q]
			
			purchase_orders = [document.get("reference_name")]
			linked_purchase_orders = [get_link_to_form_new_tab("Purchase Order", x) for x in purchase_orders]
			linked_material_requests=[]
			#purchase_receipts_a = [[[x.get("purchase_receipt") for x in y] for y in frappe.get_doc("Purchase Invoice", z).get("items")] for z in invoice_arr]
		else:
			return
		#LINKED INSPECTION DOCUMENTS
		purchase_receipts_arr = [x for x in purchase_receipts]
		all_linked_documents.extend(purchase_receipts_arr)
		pr_q = '('+','.join("'{0}'".format(i) for i in purchase_receipts_arr)+')'
		quality_inspection_q = frappe.db.sql(f"""SELECT name FROM `tabQuality Inspection`\
				WHERE reference_name IN {pr_q} """,as_dict =True)
		linked_quality_inspections = [get_link_to_form_new_tab("Quality Inspection", x.get("name")) for x in quality_inspection_q]
		quality_inspection_arr =[x.get("name") for x in quality_inspection_q]
		all_linked_documents.extend(quality_inspection_arr)
		
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
		to_return+= f"<tr><td style='white-space: nowrap; font-weight: bold;'>Vendor Invoice Details: </td><td>{linked_purchase_invoices}</td></tr>"
		if d:
			to_return+= f"<tr><td style='white-space: nowrap; font-weight: bold;'>Uploaded Documents (External): </td><td>{d}</td></tr>"
		
		to_return+= "</table>"
	elif doctype == "Purchase Receipt":
		pass
	elif doctype == "Quality Inspection":
		all_linked_documents= []
		all_linked_documents.extend([document.get("name")])
		to_return+= "<h3>Attachments and Linked Documents</h3><table border='1' width='100%' >"
		to_return += "<th>Document</th><th>Link</th>"

		#SHOW ASSOCIATED PURCHASE RECEIPTS/GRNs
		pr_link  =[get_link_to_form_new_tab("Purchase Receipt", document.get("reference_name"))]
		all_linked_documents.extend([document.get("reference_name")])

		#LINKED PURCHASE ORDERS
		purchase_orders_list = []
		pr_doc = frappe.get_doc("Purchase Receipt", document.get("reference_name"))
		[purchase_orders_list.append(x.get("purchase_order")) for x in pr_doc.get("items") if x.get("item_code") == document.get("item_code")]
		linked_purchase_orders = [get_link_to_form_new_tab("Purchase Order", x) for x in purchase_orders_list]
		all_linked_documents.extend(linked_purchase_orders)
		linked_material_requests=[]
		
		#LINKED MATERIAL REQUESTS
		#if purchase_orders_list:
		#	[linked_material_requests.append(x.get("material_request")) for x in frappe.get_doc("Purchase Order", purchase_orders_list[0]).get("items") if x.get("item_code") == document.get("item_code")]
		#	all_linked_documents.extend(purchase_orders_list)
			
		#SHOW ATTACHMENTS
		#frappe.msgprint(f"These are the linked documents: {all_linked_documents}")
		d = get_attachment_urls(all_linked_documents)

		to_return+= f"<tr><td style='white-space: nowrap; font-weight: bold;'>Goods Received Notes (GRN): </td><td>{pr_link}</td></tr>"
		to_return+= f"<tr><td style='white-space: nowrap; font-weight: bold;'>Purchase Orders: </td><td>{linked_purchase_orders}</td></tr>"
		if d:
			to_return+= f"<tr><td style='white-space: nowrap; font-weight: bold;'>Uploaded Documents (External): </td><td>{d}</td></tr>"
		to_return+= "</table>"
	elif doctype == "Material Request":
		this_material_request = document.get("name")
		all_linked_documents= []
		all_linked_documents.extend([this_material_request])
		to_return+= "<h3>Attachments and Linked Documents</h3><table border='1' width='100%' >"
		to_return += "<th>Document</th><th>Link</th>"
		this_fiscal_year = frappe.defaults.get_user_default("fiscal_year")
		this_department = document.get("department")

		#GET ASSOCIATED PROCUREMENT PLAN - TO ADD PROCUREMENT PLAN BALANCES IN FUTURE.
		proc_plan = frappe.db.sql(f"""SELECT DISTINCT name\
			FROM `tabProcurement Plan`\
				WHERE department_name = '{this_department}' AND fiscal_year = '{this_fiscal_year}' AND docstatus = 1""", as_dict=True)
		proc_plan_array = [x.get("name") for x in proc_plan] #should only be one really.
		proc_plan_link =  [get_link_to_form_new_tab("Procurement Plan", x.get("name")) for x in proc_plan]
		all_linked_documents.extend(proc_plan_array)
		pro_plan_q_str = '('+','.join("'{0}'".format(i) for i in proc_plan_array)+')'

		doc_items = document.get("items")
		item_array = [x.get("item_code") for x in doc_items]
		item_q_str = '('+','.join("'{0}'".format(i) for i in item_array)+')'
		proc_plan_items = frappe.db.sql(f"""SELECT DISTINCT item_code, qty\
			FROM `tabProcurement Plan Item`\
				WHERE item_code IN {item_q_str} AND parent IN {pro_plan_q_str} AND docstatus = 1""", as_dict=True)
		pro_plan_item_string = ' ('+' || '.join("'Item: <b>{0}</b> - Planned: {1}'".format(i.get("item_code"), i.get("qty")) for i in proc_plan_items)+')'
		
		#GET LINKED REQUEST FOR QUOTATIONS IF ANY
		rfqs = frappe.db.sql(f"""SELECT DISTINCT parent\
			FROM `tabRequest for Quotation Item`\
				WHERE material_request = '{this_material_request}' AND item_code IN {item_q_str}""", as_dict=True)
		rfq_links =  [get_link_to_form_new_tab("Request for Quotation", x.get("parent")) for x in rfqs]
		all_linked_documents.extend(rfq_links)
		
		#GET LINKED PURCHASE ORDERS IF ANY
		purchase_orders = frappe.db.sql(f"""SELECT DISTINCT parent\
			FROM `tabPurchase Order Item`\
				WHERE material_request = '{this_material_request}' AND item_code IN {item_q_str}""", as_dict=True)
		po_links =  [get_link_to_form_new_tab("Purchase Order", x.get("parent")) for x in purchase_orders]
		all_linked_documents.extend(po_links)

		#GET LINKED AWARD AND PRICES IF ANY

		#GET LINKED PURCHASE RECEIPTS IF ANY.
		purchase_receipts = frappe.db.sql(f"""SELECT DISTINCT parent\
			FROM `tabPurchase Receipt Item`\
				WHERE material_request = '{this_material_request}' AND item_code IN {item_q_str}""", as_dict=True)
		pr_links =  [get_link_to_form_new_tab("Purchase Receipt", x.get("parent")) for x in purchase_receipts]
		all_linked_documents.extend(pr_links)

		d = get_attachment_urls(all_linked_documents)

		to_return+= f"<tr><td style='white-space: nowrap; font-weight: bold;'>Procurement Plan: </td><td>{proc_plan_link} - {pro_plan_item_string}</td></tr>"
		if rfq_links:
			to_return+= f"<tr><td style='white-space: nowrap; font-weight: bold;'>RFQs/Tenders: </td><td>{rfq_links}</td></tr>"
		if po_links:
			to_return+= f"<tr><td style='white-space: nowrap; font-weight: bold;'>Purchase Orders: </td><td>{po_links}</td></tr>"
		if pr_links:
			to_return+= f"<tr><td style='white-space: nowrap; font-weight: bold;'>GRNs: </td><td>{pr_links}</td></tr>"
		if d:
			to_return+= f"<tr><td style='white-space: nowrap; font-weight: bold;'>Uploaded Documents (External): </td><td>{d}</td></tr>"
		to_return+= "</table>"
	elif doctype == "Tender Quotation Award":
		tender_number = document.get("reference_number")
		all_linked_documents= []
		all_linked_documents.extend([tender_number])
		to_return+= "<h3>Attachments and Linked Documents</h3><table border='1' width='100%' >"
		to_return += "<th>Document</th><th>Link</th>"

		#CHECK IF THERE IS AN ASSOCIATED PROFESSIONAL OPIONION
		no_of_opinions = frappe.db.count('Procurement Professional Opinion', {'request_for_quotation': tender_number})
		if no_of_opinions > 0:
			opinion_name = frappe.db.get_value('Procurement Professional Opinion', {'request_for_quotation': tender_number}, "name")
			all_linked_documents.extend([opinion_name])
			d = get_attachment_urls(all_linked_documents)
			professional_opinion_links =  [get_link_to_form_new_tab("Procurement Professional Opinion", opinion_name)]

			if professional_opinion_links:
				to_return+= f"<tr><td style='white-space: nowrap; font-weight: bold;'>Associated Professional Opinion: </td><td>{professional_opinion_links}</td></tr>"
			if d:
				to_return+= f"<tr><td style='white-space: nowrap; font-weight: bold;'>Uploaded Documents (External): </td><td>{d}</td></tr>"
		else:
			to_return+= f"<tr><td style='white-space: nowrap; font-weight: bold;'>Associated Professional Opinion: </td><td>Professional Opinion is External. Check Attachments if any</td></tr>"
		to_return+= "</table>"
	return to_return