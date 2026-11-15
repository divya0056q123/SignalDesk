# Google Cloud deployment template

This Terraform configuration prepares a single-region deployment using Cloud Run, Cloud SQL for PostgreSQL, Secret Manager, and a verified custom domain. It is not applied automatically. Review the plan and regional pricing before applying; Cloud SQL and Cloud Run can incur ongoing charges.

The backend is intentionally capped at one Cloud Run instance because login throttling and WebSocket fan-out are currently in process memory. This avoids silently losing those guarantees across replicas, but limits backend scale. The frontend can scale independently. Cloud SQL automated backups and point-in-time recovery are enabled; they are not a substitute for an independently retained export and a tested restore procedure.

## Prerequisites

- A Google Cloud project with billing enabled and permission to enable APIs, create Cloud Run and Cloud SQL resources, create service accounts and IAM bindings, and manage Secret Manager.
- Terraform 1.6+ and the Google Cloud CLI installed and authenticated.
- A custom domain verified for Google Cloud. DNS changes are required after creating the mapping.
- An SMTP relay account and a verified sender address. Add its password to Secret Manager as `signaldesk-smtp-password` before planning:

  ```powershell
  gcloud secrets create signaldesk-smtp-password --replication-policy=automatic --project $Project
  gcloud secrets versions add signaldesk-smtp-password --data-file="C:\secure\path\smtp-password.txt" --project $Project
  ```

  Keep the password file outside the repository and remove it securely after upload. The Terraform configuration refers to the secret but does not read its value.
- A protected, versioned Google Cloud Storage bucket for Terraform state. Do not use local Terraform state: the state contains generated database and application secrets. Restrict bucket access to deployment administrators.

## Build images without a local Docker engine

From the project root, replace the project and region values:

```powershell
$Project = "YOUR_GCP_PROJECT_ID"
$Region = "us-central1"
$Repository = "signaldesk"

gcloud config set project $Project
gcloud services enable artifactregistry.googleapis.com cloudbuild.googleapis.com --project $Project
gcloud artifacts repositories create $Repository --location $Region --repository-format docker --description "SignalDesk production images"

$BackendImage = "$Region-docker.pkg.dev/$Project/$Repository/backend:release-1"
$FrontendImage = "$Region-docker.pkg.dev/$Project/$Repository/frontend:release-1"

gcloud builds submit --project $Project --region $Region --tag $BackendImage --file backend/Dockerfile.production .
gcloud builds submit --project $Project --region $Region --tag $FrontendImage --file Dockerfile.production frontend
```

Cloud Build runs remotely. It can incur build charges and requires Artifact Registry and Cloud Build permissions.

## Apply the infrastructure

Create the state bucket first (choose a globally unique name) and enable object versioning:

```powershell
gcloud storage buckets create gs://YOUR_UNIQUE_TF_STATE_BUCKET --project $Project --location $Region --uniform-bucket-level-access --public-access-prevention
gcloud storage buckets update gs://YOUR_UNIQUE_TF_STATE_BUCKET --versioning
Set-Location deploy/gcp
terraform init -backend-config="bucket=YOUR_UNIQUE_TF_STATE_BUCKET" -backend-config="prefix=signaldesk"
terraform plan -var="project_id=$Project" -var="region=$Region" -var="app_domain=YOUR_VERIFIED_DOMAIN" -var="backend_image=$BackendImage" -var="frontend_image=$FrontendImage" -var="smtp_host=YOUR_SMTP_HOST" -var="smtp_username=YOUR_SMTP_USERNAME" -var="smtp_from_email=YOUR_VERIFIED_SENDER"
```

Inspect the full plan, including Cloud SQL size, high availability, secret creation, public Cloud Run invoker bindings, and domain mapping. Only apply after confirming the resources and costs:

```powershell
terraform apply -target=google_sql_database_instance.main -target=google_sql_database.main -target=google_sql_user.app -target=google_secret_manager_secret.database_url -target=google_secret_manager_secret_version.database_url -var="project_id=$Project" -var="region=$Region" -var="app_domain=YOUR_VERIFIED_DOMAIN" -var="backend_image=$BackendImage" -var="frontend_image=$FrontendImage" -var="smtp_host=YOUR_SMTP_HOST" -var="smtp_username=YOUR_SMTP_USERNAME" -var="smtp_from_email=YOUR_VERIFIED_SENDER"
```

Before deploying the backend, grant its database role permission to create application tables. Set a temporary password for the built-in PostgreSQL administrator, then connect and run the SQL grants:

```powershell
gcloud sql users set-password postgres --instance signaldesk-postgres --prompt-for-password --project $Project
gcloud sql connect signaldesk-postgres --user postgres --database signaldesk --project $Project
```

At the `psql` prompt, run:

```sql
GRANT CONNECT, CREATE, TEMPORARY ON DATABASE signaldesk TO rtla_app;
GRANT USAGE, CREATE ON SCHEMA public TO rtla_app;
```

Exit `psql`, then apply the remaining resources:

```powershell
terraform apply -var="project_id=$Project" -var="region=$Region" -var="app_domain=YOUR_VERIFIED_DOMAIN" -var="backend_image=$BackendImage" -var="frontend_image=$FrontendImage" -var="smtp_host=YOUR_SMTP_HOST" -var="smtp_username=YOUR_SMTP_USERNAME" -var="smtp_from_email=YOUR_VERIFIED_SENDER"
```

Terraform creates distinct random values for the database password, session signing key, and first-account bootstrap token. They are stored in Secret Manager. The Terraform state also contains secret material and must remain protected.

## Finish setup and verify

1. Follow the DNS records shown by the Cloud Run domain mapping and wait for certificate provisioning.
2. Read the one-time setup code from Secret Manager and use it to create the first account:

   ```powershell
   gcloud secrets versions access latest --secret=signaldesk-bootstrap-token --project $Project
   ```

3. Check `https://YOUR_VERIFIED_DOMAIN/api/health`, then sign in and test log ingestion, workspace isolation, logout, and WebSocket updates.
4. Configure Cloud Monitoring uptime alerts and notification channels for the health endpoint. Cloud Run request logs and metrics are available in Cloud Logging and Cloud Monitoring.
5. Before real user data is accepted, configure an independent encrypted export/retention destination and perform a restore drill. The included SQL backups/PITR remain within the managed Cloud SQL service.
6. Do not increase the backend maximum instance count until login throttling and WebSocket broadcasts use shared infrastructure. Email password recovery and per-account machine-ingestion credentials are not included in this template.

To destroy a test deployment, first review `terraform plan -destroy`. The Cloud SQL instance has deletion protection; disable it only after confirming that all required data and backups have been retained.
