variable "lambda_url_domain" { type = string } # e.g. xxx.lambda-url.us-east-1.on.aws
variable "web_acl_arn" { type = string }
variable "comment" {
  type    = string
  default = ""
}
