locals {
  public_hosts = {
    api           = var.domain_name
    kevin         = "demo.${var.domain_name}"
    prototype_api = "prototype-api.${var.domain_name}"
  }
  https_hosts   = var.enable_https ? local.public_hosts : {}
  service_ports = { api = 8000, kevin = 8501, prototype_api = 8001 }
}
resource "aws_subnet" "alb_second" {
  vpc_id                  = aws_vpc.sandbox.id
  cidr_block              = "10.41.2.0/24"
  availability_zone       = var.second_availability_zone
  map_public_ip_on_launch = false
  lifecycle {
    precondition {
      condition     = var.second_availability_zone != var.availability_zone && startswith(var.second_availability_zone, var.aws_region)
      error_message = "ALB needs two distinct availability zones in the selected region."
    }
  }
}
resource "aws_route_table_association" "alb_second" {
  subnet_id      = aws_subnet.alb_second.id
  route_table_id = aws_route_table.egress.id
}
resource "aws_security_group" "alb" {
  name_prefix = "${var.name}-alb-"
  description = "Public HTTP synthetic demo by default; optional HTTPS with HTTP redirect."
  vpc_id      = aws_vpc.sandbox.id
}
resource "aws_vpc_security_group_ingress_rule" "https" {
  count             = var.enable_https ? 1 : 0
  security_group_id = aws_security_group.alb.id
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = "0.0.0.0/0"
}
resource "aws_vpc_security_group_ingress_rule" "http_redirect" {
  security_group_id = aws_security_group.alb.id
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
  cidr_ipv4         = "0.0.0.0/0"
}
resource "aws_vpc_security_group_ingress_rule" "application" {
  for_each                     = local.service_ports
  security_group_id            = aws_security_group.host.id
  referenced_security_group_id = aws_security_group.alb.id
  ip_protocol                  = "tcp"
  from_port                    = each.value
  to_port                      = each.value
}
resource "aws_vpc_security_group_egress_rule" "alb_application" {
  for_each                     = local.service_ports
  security_group_id            = aws_security_group.alb.id
  referenced_security_group_id = aws_security_group.host.id
  ip_protocol                  = "tcp"
  from_port                    = each.value
  to_port                      = each.value
}
resource "aws_vpc_security_group_egress_rule" "cognito_https" {
  count             = var.enable_https ? 1 : 0
  security_group_id = aws_security_group.alb.id
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = "0.0.0.0/0"
}
resource "aws_acm_certificate" "application" {
  count                     = var.enable_https ? 1 : 0
  domain_name               = var.domain_name
  subject_alternative_names = [local.public_hosts.kevin, local.public_hosts.prototype_api]
  validation_method         = "DNS"
  lifecycle {
    create_before_destroy = true
    precondition {
      condition     = var.domain_name != "" && var.route53_zone_id != ""
      error_message = "HTTPS requires an owned hostname and existing authoritative public Route53 zone."
    }
  }
}
resource "aws_route53_record" "certificate" {
  for_each = local.https_hosts

  zone_id         = var.route53_zone_id
  name            = one([for option in aws_acm_certificate.application[0].domain_validation_options : option.resource_record_name if option.domain_name == each.value])
  type            = one([for option in aws_acm_certificate.application[0].domain_validation_options : option.resource_record_type if option.domain_name == each.value])
  records         = [one([for option in aws_acm_certificate.application[0].domain_validation_options : option.resource_record_value if option.domain_name == each.value])]
  ttl             = 60
  allow_overwrite = false
}
resource "aws_acm_certificate_validation" "application" {
  count                   = var.enable_https ? 1 : 0
  certificate_arn         = aws_acm_certificate.application[0].arn
  validation_record_fqdns = [for record in aws_route53_record.certificate : record.fqdn]
}
resource "aws_cognito_user_pool" "operators" {
  count = var.enable_https ? 1 : 0
  name  = "${var.name}-operators"
  admin_create_user_config { allow_admin_create_user_only = true }
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]
  password_policy {
    minimum_length                   = 14
    require_lowercase                = true
    require_numbers                  = true
    require_symbols                  = true
    require_uppercase                = true
    temporary_password_validity_days = 3
  }
  mfa_configuration = "OPTIONAL"
  software_token_mfa_configuration { enabled = true }
  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }
}
resource "aws_cognito_user_pool_domain" "operators" {
  count        = var.enable_https ? 1 : 0
  domain       = "${var.name}-${var.target_account_id}"
  user_pool_id = aws_cognito_user_pool.operators[0].id
}
resource "aws_cognito_user_pool_client" "alb" {
  count                                = var.enable_https ? 1 : 0
  name                                 = "${var.name}-alb"
  user_pool_id                         = aws_cognito_user_pool.operators[0].id
  generate_secret                      = true
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email", "profile"]
  supported_identity_providers         = ["COGNITO"]
  callback_urls                        = [for host in values(local.public_hosts) : "https://${host}/oauth2/idpresponse"]
  logout_urls                          = [for host in values(local.public_hosts) : "https://${host}/"]
  prevent_user_existence_errors        = "ENABLED"
  enable_token_revocation              = true
  explicit_auth_flows                  = ["ALLOW_REFRESH_TOKEN_AUTH", "ALLOW_USER_SRP_AUTH"]
}
resource "aws_lb" "application" {
  name                       = var.name
  internal                   = false
  load_balancer_type         = "application"
  security_groups            = [aws_security_group.alb.id]
  subnets                    = [aws_subnet.sandbox.id, aws_subnet.alb_second.id]
  idle_timeout               = 300
  drop_invalid_header_fields = true
}
resource "aws_lb_target_group" "application" {
  for_each    = local.service_ports
  name_prefix = substr(replace(each.key, "_", ""), 0, 6)
  port        = each.value
  protocol    = "HTTP"
  vpc_id      = aws_vpc.sandbox.id
  target_type = "instance"
  health_check {
    path                = each.key == "api" ? "/healthz" : (each.key == "kevin" ? "/_stcore/health" : "/health")
    matcher             = "200"
    interval            = 30
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}
resource "aws_lb_target_group_attachment" "application" {
  for_each         = var.deploy_host ? local.service_ports : {}
  target_group_arn = aws_lb_target_group.application[each.key].arn
  target_id        = aws_instance.host[0].id
  port             = each.value
}
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.application.arn
  port              = 80
  protocol          = "HTTP"
  default_action {
    type             = var.enable_https ? "redirect" : "forward"
    target_group_arn = var.enable_https ? null : aws_lb_target_group.application["kevin"].arn
    dynamic "redirect" {
      for_each = var.enable_https ? [1] : []
      content {
        port        = "443"
        protocol    = "HTTPS"
        status_code = "HTTP_301"
      }
    }
  }
}
resource "aws_lb_listener" "https" {
  count             = var.enable_https ? 1 : 0
  load_balancer_arn = aws_lb.application.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = aws_acm_certificate_validation.application[0].certificate_arn
  default_action {
    type = "fixed-response"
    fixed_response {
      content_type = "text/plain"
      message_body = "Unknown application hostname"
      status_code  = "404"
    }
  }
}
resource "aws_lb_listener_rule" "application" {
  for_each     = local.https_hosts
  listener_arn = aws_lb_listener.https[0].arn
  priority     = index(sort(keys(local.public_hosts)), each.key) + 10
  condition {
    host_header { values = [each.value] }
  }
  action {
    type = "authenticate-cognito"
    authenticate_cognito {
      user_pool_arn              = aws_cognito_user_pool.operators[0].arn
      user_pool_client_id        = aws_cognito_user_pool_client.alb[0].id
      user_pool_domain           = aws_cognito_user_pool_domain.operators[0].domain
      on_unauthenticated_request = "authenticate"
      scope                      = "openid email profile"
      session_timeout            = 3600
    }
  }
  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.application[each.key].arn
  }
}
resource "aws_route53_record" "application" {
  for_each = local.https_hosts
  zone_id  = var.route53_zone_id
  name     = each.value
  type     = "A"
  alias {
    name                   = aws_lb.application.dns_name
    zone_id                = aws_lb.application.zone_id
    evaluate_target_health = true
  }
}
