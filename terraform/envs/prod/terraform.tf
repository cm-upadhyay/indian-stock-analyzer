terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }

  backend "s3" {
    bucket         = "analyzer-tf-state"
    key            = "prod/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "analyzer-tf-locks"
    encrypt        = true
  }
}

provider "aws" { region = "us-east-1" }
