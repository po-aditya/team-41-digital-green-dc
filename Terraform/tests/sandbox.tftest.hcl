mock_provider "aws" {
  override_during = plan
  mock_resource "aws_acm_certificate" {
    defaults = {
      arn = "arn:aws:acm:us-west-2:123456789012:certificate/12345678-1234-1234-1234-123456789012"
      domain_validation_options = [
        { domain_name = "mel.example.org", resource_record_name = "_api.mel.example.org", resource_record_type = "CNAME", resource_record_value = "_api.acm-validations.aws" },
        { domain_name = "demo.mel.example.org", resource_record_name = "_demo.demo.mel.example.org", resource_record_type = "CNAME", resource_record_value = "_demo.acm-validations.aws" },
        { domain_name = "prototype-api.mel.example.org", resource_record_name = "_prototype.prototype-api.mel.example.org", resource_record_type = "CNAME", resource_record_value = "_prototype.acm-validations.aws" }
      ]
    }
  }
  mock_data "aws_iam_policy_document" {
    defaults = { json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}" }
  }
  mock_data "aws_ssm_parameter" {
    defaults = { value = "ami-0123456789abcdef0" }
  }
  mock_resource "aws_ecr_repository" {
    defaults = {
      repository_url = "123456789012.dkr.ecr.us-west-2.amazonaws.com/team41/runtime"
      arn            = "arn:aws:ecr:us-west-2:123456789012:repository/team41/runtime"
    }
  }
}
variables {
  target_account_id        = "123456789012"
  aws_region               = "us-west-2"
  availability_zone        = "us-west-2a"
  second_availability_zone = "us-west-2b"
  domain_name              = "mel.example.org"
  route53_zone_id          = "Z0123456789ABC"
  operator_secret_arn      = "arn:aws:secretsmanager:us-west-2:123456789012:secret:team41/operators-abc123"
  image_digests = {
    api        = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    kevin      = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    farmerloop = "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
  }
}
run "foundation_is_inert" {
  command = plan
  assert {
    condition     = length(aws_instance.host) == 0 && var.allow_paid_inference == false
    error_message = "Default foundation must not start an application host or enable paid inference."
  }
  assert {
    condition     = aws_ebs_volume.data.encrypted && aws_ebs_volume.data.type == "gp3"
    error_message = "Persistent SQLite must use encrypted local EBS."
  }
  assert {
    condition     = alltrue([for rule in aws_vpc_security_group_ingress_rule.application : rule.referenced_security_group_id == aws_security_group.alb.id])
    error_message = "Application ingress must come only from the ALB security group, never public CIDRs."
  }
}
run "single_host_configuration" {
  command = plan
  variables { deploy_host = true }
  assert {
    condition     = length(aws_instance.host) == 1 && aws_instance.host[0].metadata_options[0].http_tokens == "required" && aws_instance.host[0].metadata_options[0].http_put_response_hop_limit == 1
    error_message = "Use a single SQLite writer and IMDSv2 with bridge isolation."
  }
  assert {
    condition     = alltrue([for ref in values(local.image_refs) : can(regex("@sha256:[a-f0-9]{64}$", ref))])
    error_message = "Every runtime must use an immutable image digest."
  }
}
run "foreign_secret_is_refused" {
  command = plan
  variables {
    deploy_host         = true
    operator_secret_arn = "arn:aws:secretsmanager:us-west-2:999999999999:secret:team41/operators-abc123"
  }
  expect_failures = [aws_instance.host[0]]
}
run "missing_images_are_refused" {
  command = plan
  variables {
    deploy_host   = true
    image_digests = {}
  }
  expect_failures = [aws_instance.host[0]]
}
run "paid_requires_exact_models" {
  command = plan
  variables {
    deploy_host          = true
    allow_paid_inference = true
  }
  expect_failures = [aws_instance.host[0]]
}
run "shell_metacharacters_refused" {
  command = plan
  variables { bedrock_model_id = "model';touch /tmp/injected;#" }
  expect_failures = [var.bedrock_model_id]
}
run "placeholder_account_refused" {
  command = plan
  variables { target_account_id = "000000000000" }
  expect_failures = [var.target_account_id]
}

run "public_tls_and_authentication" {
  command = plan
  variables { enable_https = true }
  assert {
    condition     = aws_lb.application.internal == false && aws_lb_listener.https[0].protocol == "HTTPS" && aws_lb_listener.https[0].port == 443
    error_message = "Internet access must terminate at HTTPS ALB."
  }
  assert {
    condition     = length(aws_lb.application.subnets) == 2 && aws_cognito_user_pool.operators[0].admin_create_user_config[0].allow_admin_create_user_only
    error_message = "Use two AZs and administrator-managed Cognito users."
  }
  assert {
    condition     = alltrue([for rule in aws_lb_listener_rule.application : rule.action[0].type == "authenticate-cognito" && rule.action[1].type == "forward"])
    error_message = "Every public application route must authenticate before forwarding."
  }
  assert {
    condition     = alltrue([for rule in aws_vpc_security_group_ingress_rule.application : rule.referenced_security_group_id == aws_security_group.alb.id])
    error_message = "Application ports must be reachable from the ALB security group only."
  }
}

run "http_exposes_only_synthetic_ui" {
  command = plan
  assert {
    condition     = length(aws_lb_listener.https) == 0 && length(aws_cognito_user_pool.operators) == 0 && aws_lb_listener.http.default_action[0].target_group_arn == aws_lb_target_group.application["kevin"].arn
    error_message = "HTTP must expose only synthetic UI, no operator API or Cognito login."
  }
  assert {
    condition     = length(aws_lb_listener_rule.application) == 0
    error_message = "Operator API forwarding requires HTTPS."
  }
}

# Stable identities let plan-only tests verify relationships without mocking policy results.
override_resource {
  target          = aws_security_group.alb
  override_during = plan
  values          = { id = "sg-00000000000000001" }
}
override_resource {
  target          = aws_security_group.host
  override_during = plan
  values          = { id = "sg-00000000000000002" }
}
override_resource {
  target          = aws_subnet.sandbox
  override_during = plan
  values          = { id = "subnet-00000000000000001" }
}
override_resource {
  target          = aws_subnet.alb_second
  override_during = plan
  values          = { id = "subnet-00000000000000002" }
}
override_resource {
  target          = aws_lb_target_group.application["api"]
  override_during = plan
  values          = { arn = "arn:aws:elasticloadbalancing:us-west-2:123456789012:targetgroup/team41-api/0123456789abcdef" }
}
override_resource {
  target          = aws_lb_target_group.application["kevin"]
  override_during = plan
  values          = { arn = "arn:aws:elasticloadbalancing:us-west-2:123456789012:targetgroup/team41-ui/1123456789abcdef" }
}
override_resource {
  target          = aws_lb_target_group.application["prototype_api"]
  override_during = plan
  values          = { arn = "arn:aws:elasticloadbalancing:us-west-2:123456789012:targetgroup/team41-prototype/2123456789abcdef" }
}
