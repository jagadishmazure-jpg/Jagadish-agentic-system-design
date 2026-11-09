output "service_account" {
  description = "The only identity allowed to call the model."
  value       = google_service_account.app.email
}
