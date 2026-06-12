# The module contract: consumers depend on these URLs, never on container
# names — a managed-database implementation can replace this module without
# touching the compute module.

output "database_url" {
  value     = "postgresql://${var.postgres_user}:${var.postgres_password}@${docker_container.postgres.name}:5432/${var.postgres_db}"
  sensitive = true
}

output "redis_url" {
  value = "redis://${docker_container.redis.name}:6379/0"
}

output "postgres_container" {
  value = docker_container.postgres.name
}

output "redis_container" {
  value = docker_container.redis.name
}
