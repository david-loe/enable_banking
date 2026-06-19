frappe.ui.form.on("Enable Banking Connection", {
	refresh(frm) {
		if (frm.is_new()) return;

		frm.add_custom_button(__("Sync Now"), () => {
			frappe
				.call({
					method: "enable_banking.tasks.sync_connection_now",
					args: { connection: frm.doc.name },
					freeze: true,
					freeze_message: __("Queueing mapped accounts..."),
				})
				.then((response) => {
					frappe.show_alert(
						__("Queued {0} account(s).", [response.message?.queued || 0]),
					);
					frm.reload_doc();
				});
		});

		frm.add_custom_button(__("Refresh Details/Balances"), () => {
			frappe
				.call({
					method: "enable_banking.sync.refresh_connection_details_and_balances",
					args: { connection: frm.doc.name },
					freeze: true,
					freeze_message: __("Refreshing account details and balances..."),
				})
				.then(() => frm.reload_doc());
		});

		frm.add_custom_button(__("Reauthorize"), () => {
			frappe.call({
				method: "enable_banking.onboarding.reauthorize",
				args: { connection: frm.doc.name },
				freeze: true,
				callback(response) {
					if (response.message?.redirect_url) {
						window.location.assign(response.message.redirect_url);
					}
				},
			});
		});

		if (frm.doc.authorization_status !== "CLOSED") {
			frm.add_custom_button(__("Close Connection"), () => {
				frappe.confirm(
					__("Close this provider session and disable synchronization?"),
					() => {
						frappe
							.call({
								method: "enable_banking.onboarding.close_connection",
								args: { connection: frm.doc.name },
								freeze: true,
							})
							.then(() => frm.reload_doc());
					},
				);
			});
		}
	},
});
