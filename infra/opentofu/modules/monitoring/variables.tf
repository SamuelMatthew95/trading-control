variable "name_prefix" {
  type = string
}

variable "network_name" {
  type = string
}

variable "collector_image" {
  type    = string
  default = "otel/opentelemetry-collector-contrib:0.111.0"
}

variable "signoz_endpoint" {
  description = "SigNoz OTLP gRPC endpoint (e.g. host.docker.internal:4317). Empty = debug exporter."
  type        = string
  default     = ""
}

variable "otlp_grpc_host_port" {
  type    = number
  default = 14317 # host port; avoids colliding with a host-level SigNoz on 4317
}
