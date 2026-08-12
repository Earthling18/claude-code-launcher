data "alicloud_account" "current" {}

data "alicloud_log_service" "enabled" {
  enable = "On"
}

data "alicloud_api_gateway_service" "enabled" {
  enable = "On"
}

resource "alicloud_log_project" "diagnostics" {
  project_name = var.sls_project_name
  description  = "CC Launcher privacy-filtered diagnostic events"

  depends_on = [data.alicloud_log_service.enabled]
}

resource "alicloud_log_store" "diagnostics" {
  project_name     = alicloud_log_project.diagnostics.project_name
  logstore_name    = "launcher-diagnostics"
  retention_period = var.retention_days
  shard_count      = 1
  append_meta      = true
  auto_split       = false
}

resource "alicloud_log_store_index" "diagnostics" {
  project  = alicloud_log_project.diagnostics.project_name
  logstore = alicloud_log_store.diagnostics.logstore_name

  full_text {
    case_sensitive  = false
    include_chinese = true
    token           = ", '\";=()[]{}?@&<>/:\n\t\r"
  }
}

resource "random_password" "ingest_secret" {
  length  = 48
  special = false
}

data "archive_file" "function" {
  type        = "zip"
  source_dir  = "${path.module}/function"
  output_path = "${path.module}/diagnostics-function.zip"
  excludes    = ["index.test.js"]
}

resource "alicloud_fcv3_function" "ingest" {
  function_name        = "${var.name_prefix}-ingest"
  description          = "Validate, re-sanitize and store CC Launcher diagnostics"
  runtime              = "nodejs20"
  handler              = "index.handler"
  memory_size          = 256
  cpu                  = 0.25
  disk_size            = 512
  timeout              = 10
  instance_concurrency = 10
  internet_access      = false

  environment_variables = {
    INGEST_SHARED_SECRET = random_password.ingest_secret.result
  }

  code {
    zip_file = filebase64(data.archive_file.function.output_path)
  }

  log_config {
    project                = alicloud_log_project.diagnostics.project_name
    logstore               = alicloud_log_store.diagnostics.logstore_name
    log_begin_rule         = "None"
    enable_request_metrics = true
  }

  depends_on = [alicloud_log_store_index.diagnostics]
}

resource "alicloud_fcv3_trigger" "http" {
  function_name = alicloud_fcv3_function.ingest.function_name
  trigger_name  = "diagnostic-http"
  description   = "Private backend URL for API Gateway"
  qualifier     = "LATEST"
  trigger_type  = "http"
  trigger_config = jsonencode({
    authType = "anonymous"
    methods  = ["POST"]
  })
}

resource "alicloud_ram_role" "api_gateway" {
  role_name   = "${replace(var.name_prefix, "-", "")}-apigateway"
  description = "API Gateway may invoke only the diagnostics Function Compute function"
  assume_role_policy_document = jsonencode({
    Version = "1"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = ["apigateway.aliyuncs.com"] }
    }]
  })
}

resource "alicloud_ram_policy" "invoke_diagnostics" {
  policy_name = "${replace(var.name_prefix, "-", "")}-invoke"
  description = "Invoke only the CC Launcher diagnostics function"
  policy_document = jsonencode({
    Version = "1"
    Statement = [{
      Action = ["fc:InvokeFunction"]
      Effect = "Allow"
      Resource = [
        "acs:fc:${var.region}:${data.alicloud_account.current.id}:functions/${alicloud_fcv3_function.ingest.function_name}",
        "acs:fc:${var.region}:${data.alicloud_account.current.id}:functions/${alicloud_fcv3_function.ingest.function_name}/*"
      ]
    }]
  })
}

resource "alicloud_ram_role_policy_attachment" "gateway_invoke" {
  policy_name = alicloud_ram_policy.invoke_diagnostics.policy_name
  policy_type = alicloud_ram_policy.invoke_diagnostics.type
  role_name   = alicloud_ram_role.api_gateway.role_name
}

resource "alicloud_api_gateway_group" "diagnostics" {
  name        = replace(var.name_prefix, "-", "_")
  description = "CC Launcher diagnostic ingestion"
  base_path   = "/"

  depends_on = [data.alicloud_api_gateway_service.enabled]
}

resource "alicloud_api_gateway_api" "diagnostics" {
  group_id          = alicloud_api_gateway_group.diagnostics.id
  name              = "submit_diagnostic"
  description       = "Accept a privacy-filtered CC Launcher diagnostic report"
  auth_type         = "ANONYMOUS"
  force_nonce_check = false
  service_type      = "FunctionCompute"
  stage_names       = ["RELEASE"]

  request_config {
    protocol    = "HTTPS"
    method      = "POST"
    path        = "/diagnostics/v1/report"
    mode        = "PASSTHROUGH"
    body_format = "STREAM"
  }

  fc_service_config {
    function_version   = "3.0"
    function_type      = "HttpTrigger"
    region             = var.region
    function_base_url  = alicloud_fcv3_trigger.http.http_trigger[0].url_internet
    path               = "/"
    method             = "POST"
    only_business_path = true
    arn_role           = alicloud_ram_role.api_gateway.arn
    timeout            = 10000
  }

  constant_parameters {
    name        = "X-CCL-Ingest-Key"
    in          = "HEAD"
    value       = random_password.ingest_secret.result
    description = "Gateway-to-function shared secret"
  }

  depends_on = [alicloud_ram_role_policy_attachment.gateway_invoke]
}

resource "alicloud_api_gateway_plugin" "traffic_control" {
  plugin_name = "${replace(var.name_prefix, "-", "_")}_rate_limit"
  description = "Hard daily budget for the endpoint and each source IP"
  plugin_type = "trafficControl"
  plugin_data = jsonencode({
    scope                     = "PLUGIN"
    blockingMode              = "QUICK_RETURN"
    defaultLimit              = var.api_requests_per_day
    defaultPeriod             = "DAY"
    defaultRetryAfterBySecond = 3600
    parameters                = { ClientIP = "System:CaClientIp" }
    rules = [{
      name               = "PerClientIP"
      byParameters       = "ClientIP"
      bypassEmptyValue   = false
      limit              = var.client_ip_requests_per_day
      period             = "DAY"
      retryAfterBySecond = 3600
    }]
  })
}

resource "alicloud_api_gateway_plugin_attachment" "traffic_control" {
  api_id     = alicloud_api_gateway_api.diagnostics.api_id
  group_id   = alicloud_api_gateway_group.diagnostics.id
  plugin_id  = alicloud_api_gateway_plugin.traffic_control.id
  stage_name = "RELEASE"
}
