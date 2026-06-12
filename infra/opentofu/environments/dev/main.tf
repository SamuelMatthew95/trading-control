# Dev environment — same module graph as local, but:
#   * images pinned to immutable CI tags (never :local / :latest)
#   * host ports not published for the databases
#   * telemetry on, forwarding to the shared dev SigNoz
#
# Targets a dev Docker host (set DOCKER_HOST=ssh://dev-box or a TLS endpoint);
# the module interfaces are the contract, so swapping the database module for
# a managed-DB implementation changes nothing here.

terraform {
  required_version = ">= 1.6.0"

  # Shared environments need shared state + locking. Example (S3-compatible —
  # any of AWS S3, Cloudflare R2, MinIO works and stays free with R2/MinIO):
  #
  # backend "s3" {
  #   bucket         = "trading-control-tfstate"
  #   key            = "dev/terraform.tfstate"
  #   region         = "auto"
  #   dynamodb_table = "trading-control-tflock"   # or use_lockfile (Tofu >= 1.10)
  # }

  required_providers {
    docker = {
      source  = "kreuzwerker/docker"
      version = "~> 3.0"
    }
  }
}

provider "docker" {}

locals {
  name_prefix = "trading-dev"
}

module "network" {
  source      = "../../modules/network"
  name_prefix = local.name_prefix
}

module "database" {
  source       = "../../modules/database"
  name_prefix  = local.name_prefix
  network_name = module.network.network_name
  expose_ports = false

  postgres_password = var.postgres_password
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
  api_image    = var.api_image # e.g. ghcr.io/samuelmatthew95/trading-control:sha-<commit>
  database_url = module.database.database_url
  redis_url    = module.database.redis_url

  otel_enabled  = true
  otel_endpoint = module.monitoring.otlp_endpoint

  secret_env = var.secret_env
}

variable "api_image" {
  type = string
}

variable "postgres_password" {
  type      = string
  sensitive = true
}

variable "signoz_endpoint" {
  type    = string
  default = ""
}

variable "secret_env" {
  type      = map(string)
  default   = {}
  sensitive = true
}

output "api_url" {
  value = module.compute.api_url
}
