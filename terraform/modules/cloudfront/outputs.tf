output "distribution_id" { value = aws_cloudfront_distribution.this.id }
output "distribution_domain" { value = aws_cloudfront_distribution.this.domain_name }
output "url" { value = "https://${aws_cloudfront_distribution.this.domain_name}" }
