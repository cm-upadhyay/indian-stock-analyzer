resource "aws_lambda_function" "this" {
  function_name = var.function_name
  role          = var.role_arn
  package_type  = "Image"
  image_uri     = var.image_uri
  memory_size   = var.memory_size
  timeout       = var.timeout

  environment {
    variables = var.env_vars
  }

  lifecycle {
    # env vars + image managed by deploy script; image_config CMD override set per-function
    ignore_changes = [environment, image_uri, image_config, publish]
  }
}
