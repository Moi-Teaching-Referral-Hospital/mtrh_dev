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

from frappe.utils import cint, flt, cstr, now
from datetime import date, datetime
from erpnext.buying.doctype.request_for_quotation.request_for_quotation import send_supplier_emails
from erpnext.stock.utils import get_stock_balance
import datetime
import psycopg2
class TQE(Document):
	pass
#@frappe.whitelist()
def get_connection():
	#print("Starting works")
	try:
        
		conn = psycopg2.connect("dbname='funsoft' user='fs_bridge' host='172.16.106.1' password='s3quence!'")
		return conn
	except Exception as e:
		frappe.throw ("I am unable to connect to the database due to {0} "+format(e))
@frappe.whitelist()
def get_patient_dict(key):
	key = key.strip()
	conn = get_connection()
	cur = conn.cursor()
	cur.execute("""SELECT * from public.hp_patient_register WHERE patient_no = %s OR 
		(first_name ILIKE %s OR second_name ILIKE %s OR last_name ILIKE %s or tel_no ILIKE %s or id_no=%s)""",(key,key,key,key,key,key))
	rows = cur.fetchall()
	#from bson import json_util
	frappe.response["response"] = rows
	conn.close()
def send_eleave_returns():
	pass