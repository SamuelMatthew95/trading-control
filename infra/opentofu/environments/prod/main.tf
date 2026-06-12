# Prod environment — declares the production contract:
#   * remote state with locking (MANDATORY — uncomment and configure backend)
#   * immutable image tags only (validation below rejects :latest / :local)
#   * managed databases preferred: replace module.database with an
#     RDS/ElastiCache (or Render) implementation exposing the same outputs
#   * secrets injected via TF_VAR_* from a secret manager, never tfvars files
#
# The actual production deployment of this project runs on Render
# (render.yaml); this environment exists to make the IaC path to a
# self-managed prod explicit and reviewable.

terraform {
  required_version = ">= 1.6.0"

  # backend "s3" {
  #   bucket         = "trading-control-tfstate"
  #   key            = "prod/terraform.tfstate"
  #   region         = "auto"
  #   dynamodb_table = "trading-control-tflock"
  # }

  required_providers {
    docker = {
      source  = "kreuzwerker/docker"
      version = "~> 3.0"
    }
  }
}

provider "docker" {} # DOCKER_HOST → production Docker host / swarm manager

locals {
  name_prefix = "trading-prod"
}

variable "api_image" {
  type = string

  validation {
    condition     = can(regex(":sha-[0-9a-f]{40}$", var.api_image))
    error_message = "Production images must be pinned to an immutable sha tag (ghcr.io/...:sha-<commit>)."
  }
}

variable "postgres_password" {
  type      = string
  sensitive = true
}

variable "signoz_endpoint" {
  description = "Production SigNoz collector endpoint (required — prod is never unobserved)."
  type        = string

  validation {
    condition     = var.signoz_endpoint != ""
    error_message = "signoz_endpoint must be set in prod."
  }
}

variable "secret_env" {
  type      = map(string)
  default   = {}
  sensitive = true
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
  api_image    = var.api_image
  database_url = module.database.database_url
  redis_url    = module.database.redis_url

  otel_enabled  = true
  otel_endpoint = module.monitoring.otlp_endpoint

  secret_env = var.secret_env
}

output "api_url" {
  value = module.compute.api_url
}
