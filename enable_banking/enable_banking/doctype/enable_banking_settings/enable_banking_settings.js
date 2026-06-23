// Copyright (c) 2026, david-loe and contributors
// For license information, please see license.txt

const MAX_PRIVATE_KEY_FILE_BYTES = 64 * 1024;

frappe.ui.form.on("Enable Banking Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Connect Bank"), () => show_connect_bank_dialog(frm));

		frm.add_custom_button(__("Sync Now"), () => {
			frappe
				.call({
					method: "enable_banking.tasks.sync_all_now",
					freeze: true,
					freeze_message: __("Queueing Enable Banking accounts..."),
				})
				.then((response) => {
					frappe.show_alert(
						__("Queued {0} account(s).", [response.message?.queued || 0]),
					);
				});
		});

		frm.add_custom_button(__("Test Configuration"), () => {
			const save = frm.is_dirty() ? frm.save() : Promise.resolve();
			save.then(() => frm.call("test_configuration"));
		}).addClass("btn-primary");

		frm.add_custom_button(
			__("Paste Private Key"),
			() => show_private_key_dialog(frm),
			__("Private Key"),
		);

		if (frm.doc.private_key_configured) {
			frm.add_custom_button(
				__("Clear Private Key"),
				() => {
					frappe.confirm(__("Remove the encrypted pasted private key?"), () => {
						frm.call("clear_private_key").then(() => frm.reload_doc());
					});
				},
				__("Private Key"),
			);
		}
	},
});

function show_connect_bank_dialog(frm) {
	let aspsps = [];
	const dialog = new frappe.ui.Dialog({
		title: __("Connect Bank"),
		fields: [
			{
				fieldname: "company",
				fieldtype: "Link",
				label: __("Company"),
				options: "Company",
				reqd: 1,
			},
			{
				fieldname: "parent_gl_account",
				fieldtype: "Link",
				label: __("Parent Bank GL Account"),
				options: "Account",
				reqd: 1,
				get_query() {
					return {
						filters: {
							company: dialog.get_value("company"),
							account_type: "Bank",
							is_group: 1,
							disabled: 0,
						},
					};
				},
			},
			{
				fieldname: "country",
				fieldtype: "Link",
				label: __("Country"),
				options: "Country",
				reqd: 1,
			},
			{
				fieldname: "load_banks",
				fieldtype: "Button",
				label: __("Load Banks"),
				click() {
					load_aspsps(dialog).then((rows) => {
						aspsps = rows;
						if (rows.length) {
							dialog.set_value("aspsp_name", rows[0].name);
						}
					});
				},
			},
			{
				fieldname: "aspsp_name",
				fieldtype: "Select",
				label: __("Bank"),
				options: "",
				reqd: 1,
				onchange() {
					const selected = aspsps.find(
						(aspsp) => aspsp.name === dialog.get_value("aspsp_name"),
					);
					if (!selected) return;
					const max_days = Math.max(
						1,
						Math.floor(selected.maximum_consent_validity / 86400),
					);
					const consent = dialog.get_field("consent_days");
					consent.df.description = __(
						"This bank permits at most {0} days.",
						[max_days],
					);
					consent.refresh();
					if (dialog.get_value("consent_days") > max_days) {
						dialog.set_value("consent_days", max_days);
					}
					const psu_types = selected.psu_types.length
						? selected.psu_types
						: ["personal", "business"];
					dialog.set_df_property("psu_type", "options", psu_types.join("\n"));
					if (!psu_types.includes(dialog.get_value("psu_type"))) {
						dialog.set_value("psu_type", psu_types[0]);
					}
				},
			},
			{
				fieldname: "psu_type",
				fieldtype: "Select",
				label: __("PSU Type"),
				options: "personal\nbusiness",
				default: "personal",
				reqd: 1,
			},
			{
				fieldname: "consent_days",
				fieldtype: "Int",
				label: __("Consent Days"),
				default: frm.doc.default_consent_days || 90,
				reqd: 1,
			},
			{
				fieldname: "automatic_sync",
				fieldtype: "Check",
				label: __("Automatic Sync"),
				default: frm.doc.automatic_sync || 0,
			},
		],
		primary_action_label: __("Continue to Bank"),
		primary_action(values) {
			frappe.call({
				method: "enable_banking.onboarding.start_authorization",
				args: values,
				freeze: true,
				freeze_message: __("Starting bank authorization..."),
				callback(response) {
					if (response.message?.redirect_url) {
						window.location.assign(response.message.redirect_url);
					}
				},
			});
		},
	});
	dialog.show();
}

function load_aspsps(dialog) {
	const country = dialog.get_value("country");
	if (!country) {
		frappe.msgprint(__("Select a country."));
		return Promise.resolve([]);
	}
	return frappe
		.call({
			method: "enable_banking.onboarding.get_aspsps",
			args: { country },
			freeze: true,
			freeze_message: __("Loading banks..."),
		})
		.then((response) => {
			const rows = response.message || [];
			dialog.set_df_property(
				"aspsp_name",
				"options",
				rows.map((aspsp) => aspsp.name).join("\n"),
			);
			return rows;
		});
}

function show_private_key_dialog(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __("Paste Enable Banking Private Key"),
		fields: [
			{
				fieldname: "private_key_file",
				fieldtype: "HTML",
			},
			{
				fieldname: "private_key",
				fieldtype: "Code",
				label: __("PEM Private Key"),
				options: "Text",
				reqd: 1,
			},
		],
		primary_action_label: __("Store Encrypted Key"),
		primary_action(values) {
			frm.call("set_private_key", {
				private_key: values.private_key,
			}).then(() => {
				dialog.hide();
				frm.reload_doc();
			});
		},
	});
	dialog.show();
	setup_private_key_file_input(dialog);
}

function setup_private_key_file_input(dialog) {
	const $wrapper = dialog.get_field("private_key_file").$wrapper;
	const $label = $("<label>", {
		class: "control-label",
		text: __("Choose PEM File"),
	});
	const $input = $("<input>", {
		type: "file",
		class: "form-control",
		accept: ".pem,.key,text/plain,application/x-pem-file",
	});
	const $description = $("<p>", {
		class: "help-box small text-muted",
		text: __(
			"The file is read in this browser and is not uploaded as an attachment.",
		),
	});
	const $status = $("<p>", {
		class: "small text-muted",
	});

	$input.on("change", () => {
		const file = $input[0].files?.[0];
		if (!file) return;

		if (file.size > MAX_PRIVATE_KEY_FILE_BYTES) {
			show_private_key_file_error(__("The selected private key exceeds the 64 KiB limit."));
			$input.val("");
			return;
		}

		$status.removeClass("text-danger").text(__("Reading {0}...", [file.name]));
		read_private_key_file(file)
			.then((private_key) => {
				if (
					!private_key.trim() ||
					private_key.includes("\0") ||
					private_key.includes("\uFFFD")
				) {
					throw new Error(__("The selected file is not a valid UTF-8 text file."));
				}
				return dialog.set_value("private_key", private_key);
			})
			.then(() => {
				$status
					.removeClass("text-danger")
					.text(__("Loaded {0}.", [file.name]));
			})
			.catch((error) => {
				const message =
					error?.message || __("The selected private key file could not be read.");
				$status.addClass("text-danger").text(message);
				show_private_key_file_error(message);
				$input.val("");
			});
	});

	$wrapper.empty().append($label, $input, $description, $status);
}

function read_private_key_file(file) {
	return new Promise((resolve, reject) => {
		const reader = new FileReader();
		reader.onload = () => resolve(reader.result);
		reader.onerror = () =>
			reject(new Error(__("The selected private key file could not be read.")));
		reader.readAsText(file, "UTF-8");
	});
}

function show_private_key_file_error(message) {
	frappe.msgprint({
		title: __("Invalid Private Key File"),
		message,
		indicator: "red",
	});
}
