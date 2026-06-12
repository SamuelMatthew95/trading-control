output "network_name" {
  description = "Name of the bridge network containers should join."
  value       = docker_network.this.name
}

output "network_id" {
  value = docker_network.this.id
}
