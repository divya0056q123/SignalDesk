variable "project_id" {
  description = "Google Cloud project ID with billing enabled."
  type        = string
}

variable "region" {
  description = "Region for Cloud Run and Cloud SQL."
  type        = string
  default     = "us-central1"
}

variable "app_domain" {
  description = "Verified custom domain serving the frontend, without a scheme."
  type        = string
}

variable "backend_image" {
  description = "Fully qualified Artifact Registry image URI for the production backend."
  type        = string
}

variable "frontend_image" {
  description = "Fully qualified Artifact Registry image URI for the production frontend."
  type        = string
}

variable "smtp_host" {
  description = "Authenticated SMTP relay hostname."
  type        = string
}

variable "smtp_port" {
  description = "SMTP relay port; 587 for STARTTLS or 465 for implicit TLS."
  type        = number
  default     = 587
}

variable "smtp_username" {
  description = "SMTP relay account username."
  type        = string
}

variable "smtp_from_email" {
  description = "Verified sender email address."
  type        = string
}

variable "smtp_password_secret" {
  description = "Existing Secret Manager secret ID containing the SMTP relay password."
  type        = string
  default     = "signaldesk-smtp-password"
}

variable "database_tier" {
  description = "Cloud SQL machine tier. Review regional pricing before applying."
  type        = string
  default     = "db-custom-2-7680"
}

variable "database_disk_size_gb" {
  description = "Initial Cloud SQL SSD size. Cloud SQL can grow this disk automatically."
  type        = number
  default     = 20
}
