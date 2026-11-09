resource "google_service_account" "app" {
  account_id   = "harrowgate-assist"
  display_name = "Runtime identity for the assistant (calls the model, reads one secret)"
}

resource "google_artifact_registry_repository" "app" {
  #checkov:skip=CKV_GCP_84:synthetic-data images only; customer-managed keys need a rotation process (see Planned)
  repository_id = var.name
  location      = var.region
  format        = "DOCKER"
  docker_config {
    immutable_tags = true
  }
}

resource "google_secret_manager_secret" "policy_key" {
  secret_id = "${var.name}-policy-key"
  replication {
    user_managed {
      replicas {
        location = var.region
      }
    }
  }
}

resource "google_secret_manager_secret_iam_member" "read_key" {
  secret_id = google_secret_manager_secret.policy_key.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.app.email}"
}

resource "google_project_iam_member" "model_user" {
  project = var.project
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.app.email}"
}

resource "google_cloud_run_v2_service" "app" {
  name                = var.name
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_INTERNAL_ONLY"
  deletion_protection = true
  template {
    service_account = google_service_account.app.email
    scaling {
      min_instance_count = 1
      max_instance_count = 3
    }
    containers {
      image = "${var.region}-docker.pkg.dev/${var.project}/${var.name}/api:${var.image_tag}"
      ports {
        container_port = 8080
      }
      env {
        name  = "HARROWGATE_PROVIDER"
        value = "gcp"
      }
      env {
        name  = "GCP_MODEL_ID"
        value = var.model_id
      }
      env {
        name  = "GCP_PROJECT"
        value = var.project
      }
      env {
        name = "HARROWGATE_POLICY_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.policy_key.secret_id
            version = "latest"
          }
        }
      }
    }
  }
}
