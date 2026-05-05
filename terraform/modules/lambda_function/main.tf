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
    # env vars contain secrets — manage via AWS Console / CI, not here
    ignore_changes = [environment, image_uri]
  }
}
