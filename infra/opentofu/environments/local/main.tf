# Local environment — fully free and runnable.
#
#   docker build -t trading-control-api:local ../../../..   (repo root)
#   cd infra/opentofu/environments/local
#   tofu init && tofu plan && tofu apply
#   curl localhost:8000/health
#   tofu destroy
#
# State: local file. This environment is disposable; see prod/main.tf for the
# remote-state pattern.

terraform {
  required_version = ">= 1.6.0" # OpenTofu

  required_providers {
    docker = {
      source  = "kreuzwerker/docker"
      version = "~> 3.0"
    }
  }
}

provider "docker" {}

locals {
  name_prefix = "trading-local"
}

module "network" {
  source      = "../../modules/network"
  name_prefix = local.name_prefix
}

module "database" {
  source       = "../../modules/database"
  name_prefix  = local.name_prefix
  network_name = module.network.network_name
  expose_ports = true # psql/redis-cli from the host while developing
}

module "monitoring" {
  source          = "../../modules/monitoring"
  name_prefix     = local.name_prefix
  network_name    = module.network.network_name
  signoz_endpoint = var.signoz_endpoint
}

module "compute" {
  source       = "../../modules/compute"
  name_prefix  = local.name_prefix
  network_name = module.network.network_name
  api_image    = var.api_image
  database_url = module.database.database_url
  redis_url    = module.database.redis_url

  otel_enabled  = var.otel_enabled
  otel_endpoint = module.monitoring.otlp_endpoint

  secret_env = {
    ALPACA_API_KEY    = var.alpaca_api_key
    ALPACA_SECRET_KEY = var.alpaca_secret_key
    GEMINI_API_KEY    = var.gemini_api_key
  }
}
