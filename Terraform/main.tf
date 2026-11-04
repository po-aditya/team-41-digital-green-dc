locals {
  image_names  = toset(["api", "kevin", "farmerloop"])
  image_refs   = { for name in local.image_names : name => "${aws_ecr_repository.images[name].repository_url}@${lookup(var.image_digests, name, "sha256:missing")}" }
  secret_valid = can(regex("^arn:aws:secretsmanager:${var.aws_region}:${var.target_account_id}:secret:[A-Za-z0-9/_+=.@-]+$", var.operator_secret_arn))
}

data "aws_ssm_parameter" "al2023" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}
resource "aws_ecr_repository" "images" {
  for_each             = local.image_names
  name                 = "${var.name}/${each.key}"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = false
  encryption_configuration { encryption_type = "AES256" }
  image_scanning_configuration { scan_on_push = true }
}
resource "aws_vpc" "sandbox" {
  cidr_block           = "10.41.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true
}
resource "aws_subnet" "sandbox" {
  vpc_id                  = aws_vpc.sandbox.id
  cidr_block              = "10.41.1.0/24"
  availability_zone       = var.availability_zone
  map_public_ip_on_launch = false
}
resource "aws_internet_gateway" "egress" { vpc_id = aws_vpc.sandbox.id }
resource "aws_route_table" "egress" {
  vpc_id = aws_vpc.sandbox.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.egress.id
  }
}
resource "aws_route_table_association" "sandbox" {
  subnet_id      = aws_subnet.sandbox.id
  route_table_id = aws_route_table.egress.id
}
resource "aws_security_group" "host" {
  name_prefix = "${var.name}-"
  description = "Application ingress only from the HTTPS ALB. Administration uses SSM; no SSH."
  vpc_id      = aws_vpc.sandbox.id
  egress {
    description = "HTTPS package downloads and AWS APIs"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
resource "aws_ebs_volume" "data" {
  availability_zone = var.availability_zone
  size              = var.data_volume_gib
  type              = "gp3"
  encrypted         = true
  tags              = { Name = "${var.name}-persistent-data" }
  lifecycle { prevent_destroy = true }
}
resource "aws_instance" "host" {
  count                       = var.deploy_host ? 1 : 0
  ami                         = data.aws_ssm_parameter.al2023.value
  instance_type               = var.instance_type
  subnet_id                   = aws_subnet.sandbox.id
  associate_public_ip_address = true
  vpc_security_group_ids      = [aws_security_group.host.id]
  iam_instance_profile        = aws_iam_instance_profile.host.name
  user_data_replace_on_change = true
  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }
  root_block_device {
    volume_size           = 20
    volume_type           = "gp3"
    encrypted             = true
    delete_on_termination = true
  }
  user_data = templatefile("${path.module}/templates/bootstrap.sh.tftpl", {
    region           = var.aws_region
    registry         = "${var.target_account_id}.dkr.ecr.${var.aws_region}.amazonaws.com"
    volume_id        = aws_ebs_volume.data.id
    api_image        = local.image_refs.api
    kevin_image      = local.image_refs.kevin
    farmerloop_image = local.image_refs.farmerloop
    secret_arn       = var.operator_secret_arn
    paid             = tostring(var.allow_paid_inference)
    model_id         = var.bedrock_model_id
  })
  lifecycle {
    precondition {
      condition     = alltrue([for name in local.image_names : contains(keys(var.image_digests), name)]) && local.secret_valid
      error_message = "Host launch needs all three immutable image digests and a secret ARN in the explicit target account and region."
    }
    precondition {
      condition     = !var.allow_paid_inference || (var.enable_https && length(var.bedrock_resource_arns) > 0 && length(var.bedrock_model_id) > 0)
      error_message = "Paid inference requires HTTPS mode plus an explicit model ID and exact allowed Bedrock ARNs."
    }
  }
  depends_on = [aws_route_table_association.sandbox, aws_iam_role_policy.runtime, aws_iam_role_policy_attachment.ssm]
  tags       = { Name = "${var.name}-sandbox" }
}
resource "aws_volume_attachment" "data" {
  stop_instance_before_detaching = true
  count                          = var.deploy_host ? 1 : 0
  device_name                    = "/dev/sdf"
  volume_id                      = aws_ebs_volume.data.id
  instance_id                    = aws_instance.host[0].id
}
