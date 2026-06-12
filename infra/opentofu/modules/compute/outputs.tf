output "api_container" {
  value = docker_container.api.name
}

output "api_url" {
  value = "http://localhost:${var.api_host_port}"
}
