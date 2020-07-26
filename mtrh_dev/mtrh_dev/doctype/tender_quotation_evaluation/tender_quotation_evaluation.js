// Copyright (c) 2020, MTRH and contributors
// For license information, please see license.txt

frappe.ui.form.on('Tender Quotation Evaluation', {
onload_post_render:function(frm){
	if(frm.doc.rfq_no){
		//POPULATE INFO
		frappe.call({
			method: "tqe_info",
			freeze: true,
			freeze_message: __("Loading evaluation status, might take time"),
			 args: {
				  "rfq":frm.doc.rfq_no
				},
			callback: function (r) {
				console.log(r)
				
				//localStorage.setItem('doc', JSON.stringify(r.message.doc));
				//Return tqe latest report for opening and preliminary. and save
				frm.doc.respondents = r.message.respondents;
				frm.doc.procurement_method = r.message.procurement_method;
				frm.doc.opening_status = r.message.opening_status;
				frm.doc.opening_report = r.message.opening_report;
				frm.doc.opening_time = r.message.opening_time;
				
				frm.doc.evaluation_criteria = r.message.evaluation_criteria;
				frm.doc.preliminary_report__findings = r.message.preliminary_report__findings;
				frm.doc.preliminary_status = r.message.preliminary_status;
				frm.doc.scorecard = r.message.scorecard;
				
				frm.save()
				frm.refresh()
				
			},
			error: () => {
			   
				setTimeout(() => frappe.set_route('List', 'Tender Quotation Evaluation'), 2000);
			}
		})
			//SET ITEMS FILTER
			console.log("Loading items on rfq "+frm.doc.rfq_no)
			frappe.call({
				method:"mtrh_dev.mtrh_dev.doctype.tender_quotation_evaluation.tender_quotation_evaluation.unevaluated_items_query",
				args: {
					"rfq": frm.doc.rfq_no	
				},
				async: false, 
				callback: function(values){
					console.log("Received the payload")
					console.log(values);
					frm.set_query('item', function(){
						return {
							"doctype":'Item',
							// "fields" : 'item_group',
							"filters":[
								["item_code", "IN", values.message]
							]
						};
					});
				}
			})
			
		}
		else{
			frappe.msgprint("Sorry, operation not permitted.")
			setTimeout(() => frappe.set_route('List', 'Tender Quotation Evaluation'), 2000);
		}
	}
});


