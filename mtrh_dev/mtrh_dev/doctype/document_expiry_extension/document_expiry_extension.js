// Copyright (c) 2020, MTRH and contributors
// For license information, please see license.txt

frappe.ui.form.on('Document Expiry Extension', {
	// refresh: function(frm) {

	// }
	document_type: function (frm) {
		if (frm.doc.document_type) {
			switch(frm.doc.document_type) {
				//===================================================================
				case "Purchase Order":
					frm.set_query("document_name", function() {
						return {
							filters: [
								["docstatus", "!=", "2"]
							]
						}
					});
				  refresh_field("document_name")
				  console.log("Filtered purchase requests")
				  break;
				//====================================================================
				case "Material Request":
					//Filter Material requests
					frm.set_query("material_requests", function() {
						return {
							filters: [
								["docstatus", "!=", "2"]
							]
						}
					});
				  refresh_field("material_requests")
				  console.log("Filtered material requests")
				  break;
				//====================================================================
				case "Request for Quotation":
					frm.set_query("quotations_and_tenders", function() {
						return {
							filters: [
								["docstatus", "!=", "2"]
							]
						}
					});
				refresh_field("quotations_and_tenders")
				console.log("Filtered quotations and tenders")
				break;
				//==========================================================================
				case "Contract":
					frm.set_query("contracts", function() {
						return {
							filters: [
								["docstatus", "!=", "2"]
							]
						}
					});
				refresh_field("contracts")
				console.log("Filtered contracts")
				break;
				//=========================================================
				default:
					console.log("No relevant key was selected")
				  // code block
			  }
		}
	}
});
