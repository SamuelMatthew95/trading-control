variable "api_image" {
  type    = string
  default = "trading-control-api:local"
}

variable "otel_enabled" {
  type    = bool
  default = true # collector is part of this environment, so export by default
}

variable "signoz_endpoint" {
  description = "Forward telemetry to a host SigNoz (e.g. host.docker.internal:4317); empty = debug exporter."
  type        = string
  default     = ""
}

# Secrets — set via environment, never in files:
#   export TF_VAR_alpaca_api_key=...
variable "alpaca_api_key" {
  type      = string
  default   = ""
  sensitive = true
}

variable "alpaca_secret_key" {
  type      = string
  default   = ""
  sensitive = true
}

variable "gemini_api_key" {
  type      = string
  default   = ""
  sensitive = true
}
