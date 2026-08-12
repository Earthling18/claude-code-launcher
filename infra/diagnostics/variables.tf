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
  default     = 30
}

variable "api_requests_per_minute" {
  description = "Global API Gateway limit for this low-volume endpoint."
  type        = number
  default     = 600
}

variable "client_ip_requests_per_minute" {
  description = "Per source-IP API Gateway limit."
  type        = number
  default     = 30
}
