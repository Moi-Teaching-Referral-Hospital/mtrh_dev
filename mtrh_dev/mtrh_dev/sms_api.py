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

class SMSApi(Document):
	pass
@frappe.whitelist(allow_guest=True)
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
@frappe.whitelist(allow_guest=True)
def send_sms_alert(incoming_payload):
	#============================================================================================================
	#THIS METHOD REQUIRES A SIMPLE ARRAY OF JSON OBJECTS CONTAINING "phone" and "message" as keys
	#FOR EXAMPLE [{"phone":"7000000","message":"Get here fast"},{"phone":"7111111","message":"Get here quicker"}]
	#WE WILL LOOP FOR NOW BUT IN FUTURE WE USE THE REFRESH TOKEN AND SEND THE ENTIRE PAYLOAD TO THE BULK SMS SERVER
	#=============================================================================================================
	payload_to_use = json.loads(incoming_payload)
	for recipient in payload_to_use:
		#==============================================================================================================
		#GET AN OAUTH TOKEN
		#==============================================================================================================
		conn = http.client.HTTPSConnection("resmsapi.onfonmedia.co.ke")
		payload = "{\"grant_type\":\"password\",\"username\":\"mtrh\",\"password\":\"3eldoret\",\"client_id\":\"27\",\"client_secret\":\"75za6W8wqZCG7pvy\"} "

		headers = {
			'content-type': "application/json",
			'cache-control': "no-cache"
			#'postman-token': "660e591e-3254-264d-6d74-3faaf8d89259"
			}

		conn.request("POST", "/oauth2/token", payload, headers)
		res = conn.getresponse()
		data = res.read()
		print(data.decode("utf-8"))
		tokenjson = json.loads(data)
		frappe.response["tokendict"]=tokenjson
		token = str(tokenjson.get("access_token"))
		frappe.response["token"]=token
		"""With a token now I send an SMS"""
		#-=======================================================================================================================
		#GENERATE A RANDOM INT SMS ID
		#========================================================================================================================
		import string 
		import random 
		# initializing size of string  to 10
		N = 10
		# using random.choices() 
		# generating random strings  
		value = ''.join(random.choices(string.digits +
									string.digits, k = N)) 
		frappe.response["radint"] =value
		#=====================================================================================================================
		#PREPARE AN OUTGOING PAYLOAD TO THE RECIPIENT
		#=====================================================================================================================
		outgoing_payload =[]
		data={}
		data["msisdn"]=recipient.get("phone")
		data["destination"]="MTRH"
		data["message"]=recipient.get("message")
		data["sms_id"]=value
		outgoing_payload.append(data)
		# "[{\"msisdn\":\"254722810063\",\"destination\":\"MTRH\",\"message\":\"Test message on new bridge endpoint\",\"sms_id\":\"100019\"}]"
		#=====================================================================================================================
		#SEND THE SMS
		#=====================================================================================================================
		send_sms(token,outgoing_payload)
def send_sms(token, payload):
	conn = http.client.HTTPSConnection("resmsapi.onfonmedia.co.ke")
	headers = {
		'content-type': "application/json",
		'authorization': "Bearer "+token,
		'cache-control': "no-cache"
		#'postman-token': "69e5ef72-95bd-e4c4-26bb-ee9808b8d339"
		}

	conn.request("POST", "/v1/sendsms/sms", json.dumps(payload), headers)
	res = conn.getresponse()
	data = res.read()
	print(data.decode("utf-8"))
	frappe.response["sms_sending_response"]=data.decode("utf-8")
	log_sms(data,payload)
def log_sms(response, payload):
	frappe.response["response_from_isp"]=response
	frappe.response["payload_sent_out"]=payload
	for content in payload:
		recipient = content.get("msisdn")
		message = content.get("message")
		print(content)
		frappe.response["content_to_log"]=content
		sms_entry_doc = frappe.new_doc('SMS Log')
		sms_entry_doc.update(
				{
					"sender_name": "MTRH Bulk SMS",
					"message":message,			
					"sent_to": response,	
					"requested_numbers":recipient,
					"sent_on": frappe.utils.data.now_datetime(),
					"no_of_requested_sms": 0,
					"no_of_sent_sms":0
				}
			)
		sms_entry_doc.insert(ignore_permissions=True)
