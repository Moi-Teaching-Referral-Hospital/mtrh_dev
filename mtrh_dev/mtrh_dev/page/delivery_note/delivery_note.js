frappe.pages['delivery-note'].on_page_load = function(wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Creating Delivery Note',
		single_column: true
	});
}