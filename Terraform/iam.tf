data "aws_iam_policy_document" "assume_ec2" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}
resource "aws_iam_role" "host" {
  name_prefix        = "${var.name}-host-"
  assume_role_policy = data.aws_iam_policy_document.assume_ec2.json
}
resource "aws_iam_instance_profile" "host" { role = aws_iam_role.host.name }
resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.host.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}
data "aws_iam_policy_document" "runtime" {
  statement {
    sid       = "EcrLogin"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }
  statement {
    sid       = "PullOnlyTeamImages"
    actions   = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer", "ecr:BatchCheckLayerAvailability"]
    resources = [for repo in aws_ecr_repository.images : repo.arn]
  }
  dynamic "statement" {
    for_each = var.operator_secret_arn == "" ? [] : [var.operator_secret_arn]
    content {
      sid       = "ReadOnlyOperatorSecret"
      actions   = ["secretsmanager:GetSecretValue"]
      resources = [statement.value]
    }
  }
  dynamic "statement" {
    for_each = var.operator_secret_kms_key_arn == "" ? [] : [var.operator_secret_kms_key_arn]
    content {
      sid       = "DecryptOnlyOperatorSecretKey"
      actions   = ["kms:Decrypt"]
      resources = [statement.value]
      condition {
        test     = "StringEquals"
        variable = "kms:ViaService"
        values   = ["secretsmanager.${var.aws_region}.amazonaws.com"]
      }
    }
  }
  dynamic "statement" {
    for_each = var.enable_https && var.allow_paid_inference && length(var.bedrock_resource_arns) > 0 ? [1] : []
    content {
      sid       = "ExplicitBedrockModels"
      actions   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
      resources = var.bedrock_resource_arns
    }
  }
}
resource "aws_iam_role_policy" "runtime" {
  role   = aws_iam_role.host.id
  policy = data.aws_iam_policy_document.runtime.json
}
