# Monitoring module — standalone OpenTelemetry Collector.
#
# Receives OTLP from the API and forwards to SigNoz (when var.signoz_endpoint
# is set) or to the debug exporter (so `tofu apply` works with zero external
# dependencies). SigNoz itself ships its own compose bundle — see
# observability/signoz/README.md — and is intentionally not duplicated here.

terraform {
  required_providers {
    docker = {
      source  = "kreuzwerker/docker"
      version = "~> 3.0"
    }
  }
}

locals {
  exporter_block = var.signoz_endpoint != "" ? <<-EOT
    otlp:
      endpoint: ${var.signoz_endpoint}
      tls:
        insecure: true
  EOT
  : <<-EOT
    debug:
      verbosity: basic
  EOT

  exporter_name = var.signoz_endpoint != "" ? "otlp" : "debug"

  collector_config = <<-EOT
    receivers:
      otlp:
        protocols:
          grpc:
            endpoint: 0.0.0.0:4317
          http:
            endpoint: 0.0.0.0:4318
    processors:
      batch: {}
    exporters:
    ${indent(2, local.exporter_block)}
    service:
      pipelines:
        traces:
          receivers: [otlp]
          processors: [batch]
          exporters: [${local.exporter_name}]
        metrics:
          receivers: [otlp]
          processors: [batch]
          exporters: [${local.exporter_name}]
        logs:
          receivers: [otlp]
          processors: [batch]
          exporters: [${local.exporter_name}]
  EOT
}

resource "docker_image" "otelcol" {
  name         = var.collector_image
  keep_locally = true
}

resource "docker_container" "otelcol" {
  name    = "${var.name_prefix}-otelcol"
  image   = docker_image.otelcol.image_id
  restart = "unless-stopped"

  command = ["--config=/etc/otelcol/config.yaml"]

  upload {
    file    = "/etc/otelcol/config.yaml"
    content = local.collector_config
  }

  networks_advanced {
    name = var.network_name
  }

  ports {
    internal = 4317
    external = var.otlp_grpc_host_port
  }
}
