variable "function_name" { type = string }
variable "image_uri" { type = string }
variable "role_arn" { type = string }

variable "memory_size" {
  type    = number
  default = 512
}

variable "timeout" {
  type    = number
  default = 30
}

variable "env_vars" {
  type      = map(string)
  default   = {}
  sensitive = true
}
