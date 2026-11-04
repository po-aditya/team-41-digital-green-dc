output "image_repositories" {
  description = "Build/push all three images with unique immutable tags, then set their digests before enabling the host."
  value       = { for name, repo in aws_ecr_repository.images : name => repo.repository_url }
}
output "host_instance_id" {
  value = try(aws_instance.host[0].id, null)
}
output "persistent_volume_id" {
  value = aws_ebs_volume.data.id
}
output "ssm_primary_api_command" {
  description = "Run later with explicitly authorized destination credentials. Does not expose a token."
  value       = var.deploy_host ? "aws --region ${var.aws_region} ssm start-session --target ${aws_instance.host[0].id} --document-name AWS-StartPortForwardingSession --parameters '{\"portNumber\":[\"8000\"],\"localPortNumber\":[\"8000\"]}'" : null
}

output "primary_application_url" { value = var.enable_https ? "https://${var.domain_name}" : null }
output "kevin_demo_url" { value = var.enable_https ? "https://${local.public_hosts.kevin}" : "http://${aws_lb.application.dns_name}" }
output "kevin_api_url" { value = var.enable_https ? "https://${local.public_hosts.prototype_api}" : null }
output "operator_user_pool_id" { value = var.enable_https ? aws_cognito_user_pool.operators[0].id : null }

output "public_application_url" { value = var.enable_https ? "https://${local.public_hosts.kevin}" : "http://${aws_lb.application.dns_name}" }
