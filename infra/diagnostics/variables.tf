variable "region" {
  description = "Alibaba Cloud region for Function Compute, SLS and API Gateway."
  type        = string
  default     = "cn-shanghai"
}

variable "name_prefix" {
  description = "Short lowercase prefix used by all diagnostic resources."
  type        = string
  default     = "ccl-diagnostics"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,30}$", var.name_prefix))
    error_message = "name_prefix must use lowercase letters, digits and hyphens."
  }
}

variable "sls_project_name" {
  description = "Globally unique SLS project name."
  type        = string
}

variable "retention_days" {
  description = "Diagnostic log retention in days."
  type        = number
  default     = 14

  validation {
    condition     = var.retention_days >= 1 && var.retention_days <= 30
    error_message = "retention_days must be between 1 and 30."
  }
}

variable "api_requests_per_day" {
  description = "Hard daily request budget for the entire diagnostics endpoint."
  type        = number
  default     = 300

  validation {
    condition     = var.api_requests_per_day >= 1 && var.api_requests_per_day <= 1000
    error_message = "api_requests_per_day must be between 1 and 1000."
  }
}

variable "client_ip_requests_per_day" {
  description = "Hard daily request budget for one source IP."
  type        = number
  default     = 10

  validation {
    condition     = var.client_ip_requests_per_day >= 1 && var.client_ip_requests_per_day <= 100
    error_message = "client_ip_requests_per_day must be between 1 and 100."
  }
}
