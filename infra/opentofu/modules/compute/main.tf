# Compute module — the trading-control API container.

terraform {
  required_providers {
    docker = {
      source  = "kreuzwerker/docker"
      version = "~> 3.0"
    }
  }
}

resource "docker_image" "api" {
  name         = var.api_image
  keep_locally = true
}

resource "docker_container" "api" {
  name    = "${var.name_prefix}-api"
  image   = docker_image.api.image_id
  restart = "unless-stopped"

  env = concat(
    [
      "PORT=8000",
      "DATABASE_URL=${var.database_url}",
      "REDIS_URL=${var.redis_url}",
      "USE_MEMORY_MODE=${var.use_memory_mode}",
      "LOG_LEVEL=${var.log_level}",
      "ALPACA_PAPER=true",
      "BROKER_MODE=paper",
      "ALLOWED_HOSTS=localhost,127.0.0.1,${var.name_prefix}-api",
      "OTEL_ENABLED=${var.otel_enabled}",
      "OTEL_EXPORTER_OTLP_ENDPOINT=${var.otel_endpoint}",
    ],
    # Secrets arrive as a map so callers can wire TF_VAR_* / external vaults.
    [for k, v in var.secret_env : "${k}=${v}" if v != ""]
  )

  networks_advanced {
    name = var.network_name
  }

  ports {
    internal = 8000
    external = var.api_host_port
  }

  healthcheck {
    test         = ["CMD-SHELL", "python -c \"import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status==200 else 1)\""]
    interval     = "10s"
    timeout      = "5s"
    retries      = 3
    start_period = "30s"
  }
}
