output "api_url" {
  value = module.compute.api_url
}

output "otlp_endpoint" {
  value = module.monitoring.otlp_endpoint
}

output "containers" {
  value = {
    api      = module.compute.api_container
    postgres = module.database.postgres_container
    redis    = module.database.redis_container
  }
}
