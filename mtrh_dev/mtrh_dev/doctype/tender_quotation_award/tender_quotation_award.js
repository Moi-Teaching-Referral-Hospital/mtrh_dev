// Copyright (c) 2020, MTRH and contributors
// For license information, please see license.txt
var item_doc ="";
frappe.ui.form.on('Tender Quotation Award', {
		item_code:function(frm){
			frappe.call('document_info', {
				doctype: 'Item',
				docname: frm.doc.item_code
			}).then(r => {
				frm.doc.item_name = r.message.item_name;
				refresh_field("item_name");
				console.log(r);
				item_doc = r;
			});
	}
});
frappe.ui.form.on('Tender Quotation Award Suppliers', {
    supplier_name: function(frm, cdt, cdn){
        console.log(frm.doc.item_code)
        const award = locals[cdt][cdn]
        award.item_uom = item_doc.message.stock_uom;
        console.log(item_doc.message.stock_uom)
        frm.refresh_field("suppliers")
    }
})