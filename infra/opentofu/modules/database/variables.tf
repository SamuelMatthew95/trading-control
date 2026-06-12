variable "name_prefix" {
  type = string
}

variable "network_name" {
  description = "Docker network from the network module."
  type        = string
}

variable "postgres_image" {
  type    = string
  default = "pgvector/pgvector:pg15"
}

variable "redis_image" {
  type    = string
  default = "redis:7-alpine"
}

variable "postgres_user" {
  type    = string
  default = "trading"
}

variable "postgres_password" {
  description = "Database password. Local default only — inject via TF_VAR_postgres_password for anything shared."
  type        = string
  default     = "trading"
  sensitive   = true
}

variable "postgres_db" {
  type    = string
  default = "trading_control"
}

variable "expose_ports" {
  description = "Publish DB/Redis ports on the host (debugging convenience)."
  type        = bool
  default     = false
}

variable "postgres_host_port" {
  type    = number
  default = 5432
}

variable "redis_host_port" {
  type    = number
  default = 6379
}
