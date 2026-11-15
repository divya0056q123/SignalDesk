locals {
  required_apis = toset([
    "artifactregistry.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "iam.googleapis.com",
    "monitoring.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "sqladmin.googleapis.com",
  ])
}

resource "google_project_service" "required" {
  for_each           = local.required_apis
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_sql_database_instance" "main" {
  project             = var.project_id
  name                = "signaldesk-postgres"
  region              = var.region
  database_version    = "POSTGRES_16"
  deletion_protection = true

  settings {
    tier              = var.database_tier
    availability_type = "REGIONAL"
    disk_type         = "PD_SSD"
    disk_size         = var.database_disk_size_gb
    disk_autoresize   = true

    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = true
      transaction_log_retention_days = 7

      backup_retention_settings {
        retained_backups = 14
        retention_unit   = "COUNT"
      }
    }

    ip_configuration {
      ipv4_enabled = true
    }
  }

  depends_on = [google_project_service.required]
}

resource "google_sql_database" "main" {
  project  = var.project_id
  name     = "signaldesk"
  instance = google_sql_database_instance.main.name
}

resource "random_password" "database" {
  length  = 48
  special = false
}

resource "random_password" "session_secret" {
  length  = 64
  special = false
}

resource "random_password" "bootstrap_token" {
  length  = 48
  special = false
}

resource "google_sql_user" "app" {
  project  = var.project_id
  name     = "rtla_app"
  instance = google_sql_database_instance.main.name
  password = random_password.database.result
}

resource "google_secret_manager_secret" "database_url" {
  project   = var.project_id
  secret_id = "signaldesk-database-url"

  replication {
    auto {}
  }

  depends_on = [google_project_service.required]
}

resource "google_secret_manager_secret_version" "database_url" {
  secret      = google_secret_manager_secret.database_url.id
  secret_data = "postgresql://rtla_app:${urlencode(random_password.database.result)}@/signaldesk?host=/cloudsql/${google_sql_database_instance.main.connection_name}"

  depends_on = [google_sql_database.main, google_sql_user.app]
}

resource "google_secret_manager_secret" "session_secret" {
  project   = var.project_id
  secret_id = "signaldesk-session-secret"

  replication {
    auto {}
  }

  depends_on = [google_project_service.required]
}

resource "google_secret_manager_secret_version" "session_secret" {
  secret      = google_secret_manager_secret.session_secret.id
  secret_data = random_password.session_secret.result
}

resource "google_secret_manager_secret" "bootstrap_token" {
  project   = var.project_id
  secret_id = "signaldesk-bootstrap-token"

  replication {
    auto {}
  }

  depends_on = [google_project_service.required]
}

resource "google_secret_manager_secret_version" "bootstrap_token" {
  secret      = google_secret_manager_secret.bootstrap_token.id
  secret_data = random_password.bootstrap_token.result
}

data "google_secret_manager_secret" "smtp_password" {
  project   = var.project_id
  secret_id = var.smtp_password_secret
}

resource "google_service_account" "backend" {
  project      = var.project_id
  account_id   = "signaldesk-backend"
  display_name = "SignalDesk backend"
}

resource "google_project_iam_member" "backend_cloud_sql" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.backend.email}"
}

resource "google_secret_manager_secret_iam_member" "backend_secrets" {
  for_each = {
    database_url   = google_secret_manager_secret.database_url.secret_id
    session_secret = google_secret_manager_secret.session_secret.secret_id
    bootstrap      = google_secret_manager_secret.bootstrap_token.secret_id
    smtp_password  = data.google_secret_manager_secret.smtp_password.secret_id
  }

  project   = var.project_id
  secret_id = each.value
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.backend.email}"
}

resource "google_cloud_run_v2_service" "backend" {
  project  = var.project_id
  name     = "signaldesk-backend"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.backend.email
    timeout         = "3600s"

    scaling {
      min_instance_count = 0
      max_instance_count = 1
    }

    volumes {
      name = "cloudsql"

      cloud_sql_instance {
        instances = [google_sql_database_instance.main.connection_name]
      }
    }

    containers {
      image = var.backend_image

      ports {
        name           = "http1"
        container_port = 8000
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "1Gi"
        }
      }

      env {
        name  = "APP_ENV"
        value = "production"
      }
      env {
        name  = "AUTH_ENABLED"
        value = "true"
      }
      env {
        name  = "ALLOW_REGISTRATION"
        value = "false"
      }
      env {
        name  = "SAMPLE_DATA_ENABLED"
        value = "false"
      }
      env {
        name  = "ALLOWED_HOSTS"
        value = "${var.app_domain},*.run.app"
      }
      env {
        name  = "CORS_ORIGINS"
        value = "https://${var.app_domain}"
      }
      env {
        name  = "SMTP_HOST"
        value = var.smtp_host
      }
      env {
        name  = "SMTP_PORT"
        value = tostring(var.smtp_port)
      }
      env {
        name  = "SMTP_USERNAME"
        value = var.smtp_username
      }
      env {
        name  = "SMTP_FROM_EMAIL"
        value = var.smtp_from_email
      }
      env {
        name  = "SMTP_SECURITY"
        value = var.smtp_port == 465 ? "ssl" : "starttls"
      }
      env {
        name  = "PUBLIC_BASE_URL"
        value = "https://${var.app_domain}"
      }
      env {
        name = "SMTP_PASSWORD"
        value_source {
          secret_key_ref {
            secret  = data.google_secret_manager_secret.smtp_password.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "DATABASE_URL"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.database_url.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "SECRET_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.session_secret.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "BOOTSTRAP_TOKEN"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.bootstrap_token.secret_id
            version = "latest"
          }
        }
      }

      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }
    }
  }

  depends_on = [
    google_project_iam_member.backend_cloud_sql,
    google_secret_manager_secret_iam_member.backend_secrets,
    google_sql_database.main,
  ]
}

resource "google_cloud_run_v2_service_iam_member" "backend_public" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.backend.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_service" "frontend" {
  project  = var.project_id
  name     = "signaldesk-frontend"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    timeout = "300s"

    scaling {
      min_instance_count = 0
      max_instance_count = 3
    }

    containers {
      image = var.frontend_image

      ports {
        name           = "http1"
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }

      env {
        name  = "BACKEND_URL"
        value = google_cloud_run_v2_service.backend.uri
      }
    }
  }
}

resource "google_cloud_run_v2_service_iam_member" "frontend_public" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.frontend.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_domain_mapping" "frontend" {
  project  = var.project_id
  location = var.region
  name     = var.app_domain

  metadata {
    namespace = var.project_id
  }

  spec {
    route_name = google_cloud_run_v2_service.frontend.name
  }
}
