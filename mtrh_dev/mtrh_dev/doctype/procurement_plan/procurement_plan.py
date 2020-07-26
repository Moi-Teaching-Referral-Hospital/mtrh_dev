# -*- coding: utf-8 -*-
# Copyright (c) 2020, MTRH and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe import msgprint
from frappe.utils import cint, flt, cstr, now
import datetime
from datetime import date, datetime
from frappe.model.document import Document

class ProcurementPlan(Document):
	pass
@frappe.whitelist()
def procurement_consumption_mrq(year_start, year_end,item_code, department_name):
	#msgprint("I have run again") 
	total_qty =frappe.db.sql("""SELECT sum(qty) FROM `tabMaterial Request Item` WHERE creation BETWEEN %s AND %s
	AND item_code = %s AND upper(department) = %s AND docstatus=1;""",(year_start,year_end,item_code,department_name.upper()))
	#msgprint(total_qty[0][0])
	return flt(total_qty[0][0]) if total_qty else 0.0
@frappe.whitelist()
def procurement_plan_bal_mrq(year_start, year_end,item_code, department_name, fiscal_year):
	#msgprint("I have run again") 
	total_qty =frappe.db.sql("""SELECT coalesce(sum(qty),0) FROM `tabMaterial Request Item` WHERE creation BETWEEN %s AND %s
	AND item_code = %s AND upper(department) = %s AND docstatus!=2;""",(year_start,year_end,item_code,department_name.upper()))
	procurement_plan_amt = frappe.db.sql("""SELECT coalesce(sum(qty),0) FROM `tabProcurement Plan Item` WHERE docstatus=1 AND item_code=%s AND upper(department_name)=%s 
		AND fs_yr=%s """,(item_code,department_name.upper(),fiscal_year))
	procurement_plan_balance = procurement_plan_amt[0][0]-total_qty[0][0]
	#msgprint(flt(total_qty[0][0]))
	frappe.response["consumed"] = total_qty
	return procurement_plan_balance
@frappe.whitelist()
def get_budget_balance_by_account(department,expense_account,fiscal_year, year_start, year_end):
	budget = frappe.db.get_value('Budget', {'department': department,"fiscal_year": fiscal_year, "docstatus":"1"}, 'name')
	budget_amount = frappe.db.get_value('Budget Account', {'parent':budget, "account":expense_account, "docstatus":"1"}, 'budget_amount')
	total_drafts_and_submitted_orders = frappe.db.sql("""SELECT coalesce(sum(qty),0) FROM `tabPurchase Order Item` WHERE creation BETWEEN %s AND %s
    AND upper(department) = %s AND expense_account=%s AND docstatus!=2;""",(year_start,year_end,department.upper(),expense_account))
	balance = flt(budget_amount)-flt(total_drafts_and_submitted_orders[0][0])
	return balance if balance else 0.0
@frappe.whitelist()
def updatesupplier(suppname,itemcode,bidder,itemname,itemprice,user,uom,brand):
       	supplierdefault =frappe.db.sql("""UPDATE `tabItem Default` set default_supplier=%s where parent=%s""",(suppname,itemcode))
       	pricelist =frappe.db.sql("""INSERT INTO  `tabPrice List` (name,creation,modified,modified_by,owner,docstatus,currency,price_list_name,enabled,buying) values(%s,now(),now(),%s,%s,'0','KES',%s,1,1)""",(bidder,user,user,bidder))
       	itempriceinsert=frappe.db.sql("""INSERT INTO  `tabItem Price` (name,creation,modified,modified_by,owner,docstatus,currency,item_description,lead_time_days,buying,selling,
	item_name,valid_from,brand,price_list,item_code,price_list_rate) values(uuid_short(),now(),now(),%s,%s,'0','KES',%s,'0','1','0',%s,now(),%s,%s,%s,%s)""",(user,user,itemname,itemname,brand,bidder,itemcode,itemprice))
       	setdefaultpricelist =frappe.db.sql("""UPDATE `tabItem Default` set default_price_list=%s where parent=%s""",(bidder,itemcode))
@frappe.whitelist()
def Checking_Expired_Partially_Purchase_Order(year_start,year_end,expense_account):
	#today=date.today() 	 
	total_amount =frappe.db.sql("""SELECT  coalesce(sum(amount*((a.per_received)/100)),0) FROM `tabPurchase Order Item` b,`tabPurchase Order` a WHERE b.creation BETWEEN %s AND %s AND a.name=b.parent AND a.schedule_date < now()
	AND b.expense_account= %s AND b.docstatus=1;""",(year_start,year_end,expense_account))
	return total_amount[0][0]
	
	