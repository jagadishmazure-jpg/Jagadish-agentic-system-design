output "repository_url" {
  description = "Where CI would push the image (CI does not push in this repository)."
  value       = aws_ecr_repository.app.repository_url
}

output "task_role_arn" {
  description = "The only identity allowed to call the model."
  value       = aws_iam_role.task.arn
}
