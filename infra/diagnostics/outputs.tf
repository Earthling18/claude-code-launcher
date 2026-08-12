output "diagnostics_endpoint" {
  description = "Compile this HTTPS URL into CCL_DIAGNOSTICS_ENDPOINT for release builds."
  value       = "https://${alicloud_api_gateway_group.diagnostics.sub_domain}/diagnostics/v1/report"
}

output "sls_project" {
  value = alicloud_log_project.diagnostics.project_name
}

output "sls_logstore" {
  value = alicloud_log_store.diagnostics.logstore_name
}
