terraform {
  required_version = ">= 1.10.0"

  required_providers {
    databricks = {
      source  = "databricks/databricks"
      version = "~> 1.90"
    }
  }

  # The same state bucket as infra/aws. The key sits under aws/ because that is the part of the bucket the
  # GitHub apply role may write (infra/bootstrap/github.tf).
  backend "s3" {
    bucket       = "upx-tfstate-538498973473"
    key          = "aws/databricks/terraform.tfstate"
    region       = "ap-southeast-2"
    encrypt      = true
    use_lockfile = true
  }
}
