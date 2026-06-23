frappe.ui.form.on("Enable Banking Account", {
	refresh(frm) {
		if (frm.is_new()) return;

		frm.add_custom_button(__("Refresh Details/Balances"), () => {
			frappe
				.call({
					method: "enable_banking.sync.refresh_account_details_and_balances",
					args: { integration_account: frm.doc.name },
					freeze: true,
					freeze_message: __("Refreshing account details and balances..."),
				})
				.then(() => frm.reload_doc());
		});

		if (frm.doc.bank_account) {
			frm.add_custom_button(__("Sync Now"), () => {
				frappe
					.call({
						method: "enable_banking.tasks.sync_account_now",
						args: { integration_account: frm.doc.name },
						freeze: true,
						freeze_message: __("Queueing account synchronization..."),
					})
					.then(() => frm.reload_doc());
			});
			frm.add_custom_button(__("Unmap Bank Account"), () => {
				frappe.confirm(
					__("Remove this mapping and clear Enable Banking balances from the Bank Account?"),
					() => {
						frappe
							.call({
								method: "enable_banking.onboarding.unmap_account",
								args: { integration_account: frm.doc.name },
								freeze: true,
							})
							.then(() => frm.reload_doc());
					},
				);
			});
		}

		if (frm.doc.bank_account) return;

		frm.add_custom_button(__("Map Existing Bank Account"), () => {
			const dialog = new frappe.ui.Dialog({
				title: __("Map Existing Bank Account"),
				fields: [
					{
						fieldname: "bank_account",
						fieldtype: "Link",
						label: __("Bank Account"),
						options: "Bank Account",
						reqd: 1,
						get_query() {
							return {
								filters: {
									company: frm.doc.company,
									is_company_account: 1,
									disabled: 0,
								},
							};
						},
					},
				],
				primary_action_label: __("Map Account"),
				primary_action(values) {
					frappe
						.call({
							method: "enable_banking.onboarding.map_existing_account",
							args: {
								integration_account: frm.doc.name,
								bank_account: values.bank_account,
							},
							freeze: true,
						})
						.then(() => {
							dialog.hide();
							frm.reload_doc();
						});
				},
			});
			dialog.show();
		});

		frm.add_custom_button(__("Create ERPNext Bank Account"), () => {
			frappe.confirm(
				__(
					"Create a Bank, Bank-type GL Account, and Bank Account for this provider account?",
				),
				() => {
					frappe
						.call({
							method: "enable_banking.onboarding.create_erpnext_account",
							args: { integration_account: frm.doc.name },
							freeze: true,
						})
						.then(() => frm.reload_doc());
				},
			);
		});
	},
});
