# Database module — PostgreSQL (pgvector) + Redis with persistent volumes.
# Locally these are containers; the module's OUTPUTS (connection URLs) are the
# contract, so a cloud environment can swap in RDS/ElastiCache equivalents
# behind the same interface.

terraform {
  required_providers {
    docker = {
      source  = "kreuzwerker/docker"
      version = "~> 3.0"
    }
  }
}

resource "docker_volume" "pgdata" {
  name = "${var.name_prefix}-pgdata"
}

resource "docker_volume" "redisdata" {
  name = "${var.name_prefix}-redisdata"
}

resource "docker_image" "postgres" {
  name         = var.postgres_image
  keep_locally = true
}

resource "docker_image" "redis" {
  name         = var.redis_image
  keep_locally = true
}

resource "docker_container" "postgres" {
  name    = "${var.name_prefix}-postgres"
  image   = docker_image.postgres.image_id
  restart = "unless-stopped"

  env = [
    "POSTGRES_USER=${var.postgres_user}",
    "POSTGRES_PASSWORD=${var.postgres_password}",
    "POSTGRES_DB=${var.postgres_db}",
  ]

  networks_advanced {
    name = var.network_name
  }

  volumes {
    volume_name    = docker_volume.pgdata.name
    container_path = "/var/lib/postgresql/data"
  }

  # pgvector extension required by the app's vector_memory table.
  upload {
    file    = "/docker-entrypoint-initdb.d/10-init.sql"
    content = "CREATE EXTENSION IF NOT EXISTS vector;\n"
  }

  dynamic "ports" {
    for_each = var.expose_ports ? [1] : []
    content {
      internal = 5432
      external = var.postgres_host_port
    }
  }

  healthcheck {
    test     = ["CMD-SHELL", "pg_isready -U ${var.postgres_user} -d ${var.postgres_db}"]
    interval = "5s"
    timeout  = "3s"
    retries  = 10
  }
}

resource "docker_container" "redis" {
  name    = "${var.name_prefix}-redis"
  image   = docker_image.redis.image_id
  restart = "unless-stopped"
  command = ["redis-server", "--appendonly", "yes"]

  networks_advanced {
    name = var.network_name
  }

  volumes {
    volume_name    = docker_volume.redisdata.name
    container_path = "/data"
  }

  dynamic "ports" {
    for_each = var.expose_ports ? [1] : []
    content {
      internal = 6379
      external = var.redis_host_port
    }
  }

  healthcheck {
    test     = ["CMD", "redis-cli", "ping"]
    interval = "5s"
    timeout  = "3s"
    retries  = 10
  }
}
