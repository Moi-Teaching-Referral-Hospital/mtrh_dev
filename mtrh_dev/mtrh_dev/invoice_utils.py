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
import datetime
from frappe.utils import cint, flt, cstr, now
from datetime import date, datetime
from erpnext.stock.utils import get_stock_balance
from erpnext.stock.doctype.item.item import get_item_defaults, get_uom_conv_factor
from erpnext.setup.doctype.item_group.item_group import get_item_group_defaults
from erpnext.assets.doctype.asset_category.asset_category import get_asset_category_account
from erpnext.setup.doctype.brand.brand import get_brand_defaults


class InvoiceUtils(Document):
	pass
def raise_payment_request(doc, state):
	args ={}
	args["dt"] = "Purchase Invoice"
	args["dn"] = doc.get("name")
	args["loyalty_points"] = ""
	args["party"] = doc.get("party")
