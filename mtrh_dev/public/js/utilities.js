//FOR ALL MTRH DEV JAVASCRIPT UTILITIES
// the following two handles will watch the page changes everywhere
$(window).on('hashchange', page_changed);
$(window).on('load', page_changed);
//$(window).on('refresh', page_changed);
function page_changed(event) {
    // waiting for page to load completely
    frappe.after_ajax(function () {
		var route = frappe.get_route();

        if (route[0] == "Form") {
			if (!cur_frm.is_new() && (route[1] !== undefined) && (route[2] !== undefined)) {
				console.log("1. " + route[1] + ", 2: " + route[2] + ", 3: " + cur_frm.doc.name + ", 4: " + cur_frm.doc.doctype)
				
				frappe.call({
					"method":"mtrh_dev.mtrh_dev.document_dashboard.document_dashboard",
						args: {
							"docname": cur_frm.doc.name,
							"doctype": cur_frm.doc.doctype
						},
					"callback":function(e){
						console.log("DASHBOARD: " + e.message);
						//frm.dashboard.refresh();
						//setTimeout(() => {
							//$(".form-dashboard-section.custom").remove();
							//$("#divdash").remove();
						cur_frm.dashboard.add_section("<div id='divdash'>" + e.message + "</div>");
						cur_frm.dashboard.show();
						//}, 2000);
					}
				});
			}
            frappe.ui.form.on(route[1], {
				onload_post_render: function(frm){
					
				},
                refresh: function (frm) {
					// if the loaded doc is dirty, don't show workflow buttons
					console.log("Beginning execution...")
					if (frm.doc.__unsaved===1) {
						console.log("Is Dirty")
						return;
					}

					//////
					//const { we_been_here } = localStorage;
					if (!frm.is_new()) {
						//console.log("REFRESH -> " + we_been_here);
						//localStorage.setItem("we_been_here", true);
						
					}
					//////
					
					var state_fieldname = frappe.workflow.get_state_fieldname(frm.doctype);
					function set_default_state() {
						var default_state = frappe.workflow.get_default_state(frm.doctype, frm.doc.docstatus);
						if(default_state) {
							frm.set_value(state_fieldname, default_state);
						}
					}
					function get_state() {
						//if(!frm.doc[state_fieldname]) {
						//	set_default_state();
						//}
						return frm.doc[state_fieldname];
					}
					const state = get_state();
					if(!state) {
						return;
					}
					function has_approval_access(transition) {
						let approval_access = false;
						const user = frappe.session.user;
						if (user === 'Administrator'
							|| transition.allow_self_approval
							|| user !== frm.doc.owner) {
							approval_access = true;
						}
						return approval_access;
					}
					frappe.workflow.get_transitions(frm.doc).then(transitions => {
						frm.page.clear_actions_menu();
						transitions.forEach(d => {
							if (frappe.user_roles.includes(d.allowed) && has_approval_access(d)) {
								frm.page.add_action_item(__(d.action), function() {
									workflowstate_includes_scm = false;
									if(frm.doc.workflow_state){
										workflowstate_includes_scm = frm.doc.workflow_state.toLowerCase().includes("scm");
									}
									if(workflowstate_includes_scm || d.action.toLowerCase().includes("confirm") || d.action.toLowerCase().includes("approve") || d.action.toLowerCase().includes("cancel") || d.action.toLowerCase().includes("submit") || d.action.toLowerCase().includes("reject") || d.action.toLowerCase().includes("terminate") || d.action.toLowerCase().includes("recall") || d.action.toLowerCase().includes("confirm") || d.action.toLowerCase().includes("send")){
										frappe.confirm(
											'Are you sure you want to "' + d.action + '" the document ' + frm.doc.name + '?',
											function(){
												frappe.prompt([
													{
														label: 'Enter narative for your decision to ' + d.action + '. Document: ' + frm.doc.name,
														fieldtype: 'Small Text',
														reqd: true,
														fieldname: 'reason'
													}],
													function(args){
														frm.timeline.insert_comment("Decision: " + d.action + " - Memo : " + args.reason);
														frm.selected_workflow_action = d.action;
														frm.script_manager.trigger('before_workflow_action').then(() => {
															frappe.xcall('frappe.model.workflow.apply_workflow', {doc: frm.doc, action: d.action}).then((doc) => {
																frappe.model.sync(doc);
																frm.refresh();
																frm.selected_workflow_action = null;
																frm.script_manager.trigger("after_workflow_action");
															});
														});
													}
												);
												
											},
											function(){
												validated = false;
												window.close();
												//frappe.throw("No action taken. Go back to document");
											}
										);
									}else{
										frm.selected_workflow_action = d.action;
										frm.script_manager.trigger('before_workflow_action').then(() => {
											frappe.xcall('frappe.model.workflow.apply_workflow', {doc: frm.doc, action: d.action}).then((doc) => {
												frappe.model.sync(doc);
												frm.refresh();
												frm.selected_workflow_action = null;
												frm.script_manager.trigger("after_workflow_action");
											});
										});
									}
								});
							}
						});
					});
                }
            })
 

        }
    })
}

//1. SUBSCRIBE TO AN EVENT THAT TRIGGERS NEED FOR ONE TO INPUT A COMMENT.
frappe.realtime.on("doc_comment", (data) => {
	frappe.prompt([
		{
			label: 'Enter narative for your decision to ' + data.decision + '. Document: ' + doc.doc_name,
			fieldtype: 'Small Text',
			reqd: true,
			fieldname: 'reason'
		}],
		function(args){
			console.log("Reason: " + args.reason);
			//INSERT COMMENT.
			d = frappe.get_doc(doc.doc_type, doc.doc_name);
			d.add_comment('The document decision: ' + data.decision + ": " + args.reason);
		}
	);
})