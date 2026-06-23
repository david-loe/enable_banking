## JSON Updates

This app is heavily JSON-driven. Many system objects are maintained through JSON files and imported by Frappe.

Important:

* Whenever a change is made to JSON files for Doctypes or other system imports, the `modified` field must always be updated.
* This applies especially to:

  * `doctype/*/*.json`
  * `web_form/*/*.json`
  * `notification/*/*.json`
  * Workspace/sidebar/desktop JSONs
* Outdated `modified` values can quickly lead to sync or import issues that are difficult to trace.

## Automatic Typing

After changing DocTypes, regenerate the Python type annotations for the affected controllers. Run this bench command:

`bench --site <site> execute "frappe.get_doc('DocType', '<DocType Name>').export_types_to_controller()"`

The generated type blocks are managed automatically and should not be edited manually.