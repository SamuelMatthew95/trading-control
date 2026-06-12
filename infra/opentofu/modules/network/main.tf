# Network module — isolated bridge network all stack containers join.

terraform {
  required_providers {
    docker = {
      source  = "kreuzwerker/docker"
      version = "~> 3.0"
    }
  }
}

resource "docker_network" "this" {
  name   = "${var.name_prefix}-net"
  driver = "bridge"

  labels {
    label = "managed-by"
    value = "opentofu"
  }
}
