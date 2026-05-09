# Cache policy: 5-min TTL, keyed on path + run_date query param only.
# Authorization header is forwarded to origin (via origin request policy) but
# NOT included in the cache key — all authenticated users see the same analysis data.
resource "aws_cloudfront_cache_policy" "five_min" {
  name        = "analyzer-api-5min"
  min_ttl     = 0
  default_ttl = 300
  max_ttl     = 300

  parameters_in_cache_key_and_forwarded_to_origin {
    cookies_config { cookie_behavior = "none" }
    headers_config { header_behavior = "none" }

    query_strings_config {
      query_string_behavior = "whitelist"
      query_strings {
        items = ["run_date"]
      }
    }

    enable_accept_encoding_brotli = true
    enable_accept_encoding_gzip   = true
  }
}

# CloudFront distribution — uses *.cloudfront.net domain (no custom domain yet).
# Custom domain (api.srenix.in) will be added once Route53 NS propagation is confirmed.
resource "aws_cloudfront_distribution" "this" {
  enabled         = true
  is_ipv6_enabled = true
  comment         = var.comment != "" ? var.comment : "analyzer-api"
  web_acl_id      = var.web_acl_arn

  origin {
    domain_name = var.lambda_url_domain
    origin_id   = "lambda"

    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  # Default behavior — no caching, all headers forwarded (auth endpoints, webhooks, SSE)
  default_cache_behavior {
    allowed_methods        = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = "lambda"
    viewer_protocol_policy = "redirect-to-https"
    compress               = true

    # CachingDisabled managed policy
    cache_policy_id = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"
    # AllViewerExceptHostHeader — forwards Authorization + all other headers to Lambda
    origin_request_policy_id = "b689b0a8-53d0-40ab-baf2-68738e2966ac"
  }

  # /api/v1/latest — 5-min cache (stock picks same for all users)
  ordered_cache_behavior {
    path_pattern           = "/api/v1/latest*"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = "lambda"
    viewer_protocol_policy = "redirect-to-https"
    compress               = true

    cache_policy_id          = aws_cloudfront_cache_policy.five_min.id
    origin_request_policy_id = "b689b0a8-53d0-40ab-baf2-68738e2966ac"
  }

  # /api/v1/accuracy — 5-min cache (rolling 30-day stats, rarely changes)
  ordered_cache_behavior {
    path_pattern           = "/api/v1/accuracy*"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = "lambda"
    viewer_protocol_policy = "redirect-to-https"
    compress               = true

    cache_policy_id          = aws_cloudfront_cache_policy.five_min.id
    origin_request_policy_id = "b689b0a8-53d0-40ab-baf2-68738e2966ac"
  }

  # /api/v1/stream/* — no caching (SSE long-poll, must pass through immediately)
  ordered_cache_behavior {
    path_pattern           = "/api/v1/stream/*"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = "lambda"
    viewer_protocol_policy = "redirect-to-https"
    compress               = false

    cache_policy_id          = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"
    origin_request_policy_id = "b689b0a8-53d0-40ab-baf2-68738e2966ac"
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  # Use CloudFront's default *.cloudfront.net certificate (free, no ACM needed)
  viewer_certificate {
    cloudfront_default_certificate = true
  }

  # Don't cache error responses — always pass through to client
  custom_error_response {
    error_code            = 403
    error_caching_min_ttl = 0
  }

  custom_error_response {
    error_code            = 500
    error_caching_min_ttl = 0
  }
}
