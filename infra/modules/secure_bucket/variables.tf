variable "bucket_name" {
  description = "Bucket name; every bucket in this repo starts with upx-."
  type        = string

  validation {
    condition     = startswith(var.bucket_name, "upx-")
    error_message = "Buckets in this repo must start with upx- (isolation from the old repos)."
  }
}

variable "keep_old_versions_days" {
  description = "Days to keep earlier versions of overwritten or deleted files."
  type        = number
  default     = 90
}
