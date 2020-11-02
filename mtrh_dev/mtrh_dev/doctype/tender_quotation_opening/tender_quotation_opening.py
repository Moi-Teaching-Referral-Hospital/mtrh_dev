# -*- coding: utf-8 -*-
# Copyright (c) 2020, MTRH and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import nowdate, getdate, add_days, add_years, cstr, get_url, get_datetime, get_link_to_form
import copy
from frappe.utils import get_files_path, get_hook_method, call_hook_method, random_string, get_fullname, today, cint, flt
from mtrh_dev.mtrh_dev.workflow_custom_action import send_notifications
class TenderQuotationOpening(Document):
	def refloat_quotation(self):
		if not self.refloated:	
			self.duplicate_rfq()
		else:
			frappe.throw(_("Document already re-floated"))
	def duplicate_rfq(self, item_filter = None, duplicate_type = None):
		rfq = self.rfq_no
		doc = frappe.get_doc("Request for Quotation", rfq)
		item_category = doc.get("buyer_section")	
		mode_of_purchase =doc.get("mode_of_purchase")
		try:
			sq_doc = frappe.get_doc({
				"doctype": "Request for Quotation",	
				"buyer_section":item_category,
				"mode_of_purchase": mode_of_purchase,
				"transaction_date": add_days(nowdate(), 30),
				"company": frappe.defaults.get_user_default("company"),	
				"amended_from": rfq,
				"message_for_supplier": "Please find attached, a list of item/items for your response via a quotation. We now only accept responses to the quotation via our portal. \
					Responses by replying via email or via paper based methods are not accepted for this quote. Please login to the portal using your credentials here: https://portal.mtrh.go.ke. Then click on 'Request for Quotations', pick this RFQ/Tender and fill in your unit price inclusive of tax.",
				"status":"Draft"			
			})	
			sq_doc = self.append_items_to_rfq(sq_doc , doc.get("items"), item_filter)
			sq_doc = self.append_bidders(sq_doc , doc.get("suppliers"))
			sq_doc.flags.ignore_permissions = True
			sq_doc.run_method("set_missing_values")
			sq_doc.insert()
			if duplicate_type and "renegotiation" in duplicate_type:
				sq_doc.submit() #SUBMIT RFQ IF WE INTEND TO RENEGOTIATE FOR THESE ITEMS
				self.notify_supplier(sq_doc.get("name"))
			opening_report = get_link_to_form("Tender Quotation Opening", self.name)
			professional_opinion = frappe.db.get_value("Procurement Professional Opinion"\
				,{"reference_number":self.get("name")},"name", as_dict = True)
			opinion_link = None
			if professional_opinion:
				opinion_link = get_link_to_form("Procurement Professional Opinion", professional_opinion.get("name"))
			
			documents =f"Professional Opinion: <h4>{opinion_link}</h4>Opening Report: <h4>{opening_report}</h4>"
			
			sq_doc.add_comment("Shared",text=f"This quotation was refloated\
				 under the Accounting officer authorization. See comments on {documents}")
			self.db_set("refloated", True)
		except Exception as e:
			frappe.throw(f"{e}")
	def append_items_to_rfq(self,sq_doc , items, item_filter = None):
		procurement_value = 0.0
		if not item_filter:
			item_filter = [x.get("item_code") for x in items] #Assign all items in existing rfq if no filter is provided
		for item_dict in items:
			if item_dict.item_code in item_filter:
				sq_doc.append('items', {
					"item_code": item_dict.get("item_code"),
					"item_name": item_dict.get("item_name"),
					"description": item_dict.get("description"),
					"qty": item_dict.get("qty"),
					"rate": item_dict.get("rate"),		
					"amount": item_dict.get("amount"),		
					"warehouse": item_dict.get("warehouse") or None,
					"material_request": item_dict.get("material_request"),
					"schedule_date": add_days(nowdate(), 30),
					"stock_uom": item_dict.get("stock_uom"),
					"uom": item_dict.get("uom"),
					"conversion_factor": item_dict.get("conversion_factor"),
					"parent": sq_doc.name
				})
				#ADD UP THE TOTAL VALUE  FOR THIS RFQ.
				#total = float(item_dict)
				procurement_value += flt(item_dict.get("amount"))
		sq_doc.value_of_procurement = procurement_value

		return sq_doc
	def append_bidders(self, sq_doc, suppliers):
		sq  = sq_doc.append("suppliers",{})
		for d in suppliers:
			sq.supplier = d.get("supplier")
			sq.supplier_name = d.get("supplier_name")
			sq.contact = d.get("contact")
			sq.email_id = d.get("email_id")
			sq.send_email = False
			sq.email_sent = False
			sq.no_quote = False
			#sq.quote_status = "Pending",
			sq.parent: sq_doc.get("name")
		return sq_doc
	def valid_document_for_renegotiation(self):
		return len(self.get("bids")) == 1
	def send_for_renegotiation(self):
		if not self.valid_document_for_renegotiation():
			recommendation = self.get("recommendation")
			frappe.throw(f"Sorry this document is not valid for {recommendation} because it has more than one bidder.")
		if "Send for Renegotiation" in [self.get("recommendation")]:
			sq = self.get("bids")[0].get("bid_number")
			sq_doc = frappe.get_doc("Supplier Quotation", sq)
			sq_doc.flags.ignore_permissions = True
			sq_doc.cancel()
			self.create_document_extension
			self.notify_supplier()
	def create_document_extension(self):
		rfq = self.get("rfq_number")
		doc = frappe.get_doc("Request for Quotation", rfq)
		ex_doc = frappe.get_doc({
			"doctype": "Document Expiry Extension",
			"document_type":"Request for Quotation",
			"document_name": rfq,
			"from_date": doc.get("transaction_date"),
			"to_date": add_days(nowdate(), 30),
		})
		ex_doc.flags.ignore_permissions=True
		ex_doc.save()
		ex_doc.submit()
		document = self.get("name")
		link_to_document= get_link_to_form("Tender Quotation Opening",document)
		ex_doc.add_comment("Shared", f"This extension was approved under Accounting officer authority. See {link_to_document}")
		return
	def notify_supplier(self, new_rfq=None):
		template = frappe.db_get_value("Document Template", "Renegotiation of Quotation Price - Direct Procurement", "part a")
		rfq_number = self.get("rfq_number")
		sq_number = self.get("bids")[0].get("bid_number")
		doc = frappe.get_doc("Request for Quotation", rfq_number)
		sq_doc = frappe.get_doc("Supplier Quotation", sq_number)
		items =f"<h4>Your Quotation{sq_number}</h4><table style='width:100%;border:1px;padding: 0;margin: 0;border-collapse: collapse;border-spacing:0;'><tr><td>Item Name</td><td>Unit of Measure</td><td>Unit Price</td></tr>"
		
		for item in sq_doc.get("items"):
			item_name = item.get("item_name")
			uom = item.get("stock_uom")
			price = item.get("rate")
			items += f"<tr><td>{item_name}</td><td>{uom}</td><td>{price}</td></tr>"
		if new_rfq:
			items += f"NB: <h4> <mark> Please Send your quotation under reference {new_rfq}</mark></h4>"
		message = eval(f"f'{template}'")
		bidder_email = self.get_supplier_contact(sq_doc.get("supplier"))
		send_notifications([bidder_email], message,\
			f"RFQ {rfq_number} - Resubmit Better Offer",\
				doc.get("doctype"),doc.get("name"))
		return
	def get_supplier_contact(self, thesupplier):
		contact = frappe.db.get_value("Dynamic Link",\
				{"link_doctype":"Supplier", "link_title":thesupplier, "parenttype":"Contact"} ,"parent")
		email = frappe.db.get_value("Contact", contact, "email_id")
		return email




