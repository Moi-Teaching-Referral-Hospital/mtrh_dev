//FOR ALL MTRH DEV JAVASCRIPT UTILITIES
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