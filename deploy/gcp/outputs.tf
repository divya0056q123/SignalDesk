output "frontend_url" {
  description = "Cloud Run URL for the frontend before custom-domain DNS finishes propagating."
  value       = google_cloud_run_v2_service.frontend.uri
}

output "backend_url" {
  description = "Cloud Run backend URL. The application still requires account authentication."
  value       = google_cloud_run_v2_service.backend.uri
}

output "cloud_sql_connection_name" {
  description = "Cloud SQL connection name attached to the backend service."
  value       = google_sql_database_instance.main.connection_name
}

output "bootstrap_secret_name" {
  description = "Use gcloud secrets versions access latest to retrieve the one-time setup code."
  value       = google_secret_manager_secret.bootstrap_token.secret_id
}
