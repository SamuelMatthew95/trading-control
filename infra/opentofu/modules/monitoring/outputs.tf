output "otlp_endpoint" {
  description = "In-network OTLP gRPC endpoint for the API's OTEL_EXPORTER_OTLP_ENDPOINT."
  value       = "http://${docker_container.otelcol.name}:4317"
}
