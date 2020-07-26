# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

# ERPNext - web based ERP (http://erpnext.com)
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe, json
import http.client
import mimetypes
from frappe import _
from frappe.model.mapper import get_mapped_doc
from frappe.utils import get_url, cint
from frappe.utils.background_jobs import enqueue
from frappe import msgprint
from frappe.model.document import Document
import datetime
from frappe.utils import cint, flt, cstr, now
from datetime import date, datetime
from fuzzywuzzy import process
from fuzzywuzzy import fuzz

class SMSApi(Document):
	pass
@frappe.whitelist()
def send_message(payload_to_send):
	msgprint(payload_to_send)
	#payload_to_use = json.loads(payload_to_send)
	msgparameters = []
	msgparameters.append(payload_to_send)
	conn = http.client.HTTPSConnection("api.onfonmedia.co.ke")
	payload ={}
	payload["SenderId"] ="MTRH"
	payload["MessageParameters"] = msgparameters
	"""[
		{
			"Number":number,
			"Text":message,

		}
	]"""
	payload["ApiKey"] = "69pJq6iTBSwfAaoL4BU7yHi361dGLkqQ1MJYHQF/lJI="
	payload["ClientId"] ="8055c2c9-489b-4440-b761-a0cc27d1e119"
	msgprint(payload)
	headers ={}
	headers['Content-Type']= 'application/json'
	headers['AccessKey']= 'FKINNX9pwrBDzGHxgQ2EB97pXMz6vVgd'
	headers['Content-Type']= 'application/json'
	headers['Cookie']= 'AWSALBTG=cWN78VX7OjvsWtCKpI8+ZTJuLfqNCOqRtmN6tRa4u47kdC/G4k7L3TdKrzftl6ni4LspFPErGdwg/iDlloajVm0LoGWChohiR07jljLMz/a8tduH+oHvptQVo1DgCplIyjCC+SyvnUjS2vrFiLN5E+OvP9KwWIjvmHjRiNJZSVJ4MageyKQ=; AWSALBTGCORS=cWN78VX7OjvsWtCKpI8+ZTJuLfqNCOqRtmN6tRa4u47kdC/G4k7L3TdKrzftl6ni4LspFPErGdwg/iDlloajVm0LoGWChohiR07jljLMz/a8tduH+oHvptQVo1DgCplIyjCC+SyvnUjS2vrFiLN5E+OvP9KwWIjvmHjRiNJZSVJ4MageyKQ='
	conn.request("POST", "/v1/sms/SendBulkSMS", payload, headers)
	res = conn.getresponse()
	data = res.read()
    #print(data.decode("utf-8"))
	frappe.response["payload"] = payload
	frappe.response["response"] =data
@frappe.whitelist()
def duplicate_checker(item_code):
	item = frappe.db.get_value("Item",{"item_code":item_code},"item_name")
	items = frappe.db.get_list('Item',
			filters={
				'disabled': "0",
				'item_code':["NOT LIKE",item_code] #EXCLUDE THIS PARTICULAR ITEM
			},
			fields=['item_name','item_code','item_group'],
			as_list=False
		)
	itemsarray =[]
	itemdict={}
	for row in items:
		ratio = fuzz.token_sort_ratio(item,str(row.item_name))
		itemcode = row.item_code
		itemname =row.item_name
		itemgroup =row.item_group
		if ratio > 80:
			itemdict["item_code"] = itemcode
			itemdict["item_name"] = itemname
			itemdict["item_category"] = itemgroup
			itemdict["ratio"] = ratio
			itemsarray.append(itemdict)
			itemdict ={}
	#payload = process.extract(item, itemsarray)
	frappe.response["potential_duplicates"]=itemsarray
	frappe.response["iteminquestion"] = item
	return itemsarray
@frappe.whitelist()
def canceldocuments(payload):
	#payload_to_use = json.loads(payload)
	items = frappe.db.get_list('Item',
				filters={		
					'item_code':["NOT IN", ["ITM000299", "760000","ITM000173"]] #760000
				},
				fields=['name'],
				as_list=False
			)
	myarr=[]
	payload_to_use =[]
	for item in items:
		payload_to_use.append(str(item.name))
	for lisitem in payload_to_use:
		item_code = lisitem
		#myarr.append(lisitem)
		#frappe.db.set_value("Item",item_code,"disabled","1")
		frappe.delete_doc("Item",item_code)
		"""awards = frappe.db.get_list('Tender Quotation Award',
				filters={
					'docstatus': "1",
					'item_code':item_code
				},
				fields=['name'],
				as_list=False
			)
		for award in awards:
			docname = award.name
			frappe.db.set_value("Tender Quotation Award",docname,"docstatus","2")
			frappe.delete_doc("Tender Quotation Award",docname)
		#frappe.delete_doc("Item",item_code)"""
	frappe.response["items"]=myarr
