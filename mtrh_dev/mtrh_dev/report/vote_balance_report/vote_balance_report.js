// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

frappe.query_reports["Vote Balance Report"] = {
	"filters": [
		{
			fieldname: "from_fiscal_year",
			label: __("From Fiscal Year"),
			fieldtype: "Link",
			options: "Fiscal Year",
			default: frappe.sys_defaults.fiscal_year,
			reqd: 1
		},
		{
			fieldname: "to_fiscal_year",
			label: __("To Fiscal Year"),
			fieldtype: "Link",
			options: "Fiscal Year",
			default: frappe.sys_defaults.fiscal_year,
			reqd: 1
		},
		{
			fieldname: "period",
			label: __("Period"),
			fieldtype: "Select",
			options: [
				{ "value": "Monthly", "label": __("Monthly") },
				{ "value": "Quarterly", "label": __("Quarterly") },
				{ "value": "Half-Yearly", "label": __("Half-Yearly") },
				{ "value": "Yearly", "label": __("Yearly") }
			],
			default: "Quarterly",
			reqd: 1
		},
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			reqd: 1,
			read_only: 1,
			hidden: 1
		},
		{
			fieldname: "budget_against",
			label: __("Budget Against"),
			fieldtype: "Select",
			options: ["Cost Center", "Project"],
			default: "Department",
			reqd: 1,
			on_change: function() {
				frappe.query_report.set_filter_value("budget_against_filter", []);
				frappe.query_report.refresh();
			}
		},
		{
			fieldname:"budget_against_filter",
			label: __('Dimension Filter'),
			fieldtype: "MultiSelectList",
			get_data: function(txt) {
				if (!frappe.query_report.filters) return;

				let budget_against = frappe.query_report.get_filter_value('budget_against');
				if (!budget_against) return;

				return frappe.db.get_link_options(budget_against, txt);
			}
		},
		{
			fieldname:"show_cumulative",
			label: __("Show Cumulative Amount"),
			fieldtype: "Check",
			default: 0,
		}
	],
	onload: function(report) {
		var ultimate_filters =[]
		report.page.add_inner_button(__("Show Votebook Trends"), function() {
			//console.log(report.report_settings.filters)
			var the_filters = report.report_settings.filters
			the_filters.forEach(function(d){
				var obj ={}
				var thefield = String(d.fieldname)
				console.log(thefield)
				var thevalue = frappe.query_report.get_filter_value(thefield)
				obj.thefield = thevalue
				ultimate_filters.push(obj)
			})
			console.log(ultimate_filters)
			//frappe.msgprint("Showing report for "+report);
		});
	}
}

erpnext.dimension_filters.forEach((dimension) => {
	frappe.query_reports["Vote Balance Report"].filters[4].options.push(dimension["document_type"]);
});
//console.log(JSON.stringify(frappe.query_reports["Vote Balance Report"].filters))
//frappe.ui.form.on('Vote Balance Report', {
  //  refresh: function(frm) {

    
  //}
//});