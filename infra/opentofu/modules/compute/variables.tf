variable "name_prefix" {
  type = string
}

variable "network_name" {
  type = string
}

variable "api_image" {
  description = "Image to run. Local builds: trading-control-api:local. CI-published: ghcr.io/samuelmatthew95/trading-control:sha-<commit>."
  type        = string
}

variable "database_url" {
  type      = string
  sensitive = true
}

variable "redis_url" {
  type = string
}

variable "use_memory_mode" {
  type    = bool
  default = false
}

variable "log_level" {
  type    = string
  default = "INFO"
}

variable "otel_enabled" {
  type    = bool
  default = false
}

variable "otel_endpoint" {
  type    = string
  default = "http://localhost:4317"
}

variable "api_host_port" {
  type    = number
  default = 8000
}

variable "secret_env" {
  description = "API keys (ALPACA_API_KEY, GEMINI_API_KEY, ...). Empty values are dropped."
  type        = map(string)
  default     = {}
  sensitive   = true
}
