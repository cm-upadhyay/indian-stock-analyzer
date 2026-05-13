plugin "aws" {
  enabled = true
  version = "0.38.0"
  source  = "github.com/terraform-linters/tflint-ruleset-aws"
}

config {
  # Only fail on errors, not warnings
  force = false
}
