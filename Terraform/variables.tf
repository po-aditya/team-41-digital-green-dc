variable "target_account_id" {
  description = "Explicit destination AWS account, supplied by its owner. No personal account is selected or discovered by this module."
  type        = string
  validation {
    condition     = can(regex("^[0-9]{12}$", var.target_account_id)) && var.target_account_id != "000000000000"
    error_message = "Supply the authorized destination's 12-digit AWS account ID."
  }
}
variable "aws_region" {
  description = "Destination AWS region; no region is inferred from a local profile."
  type        = string
  default     = "us-east-1"
  validation {
    condition     = can(regex("^[a-z]{2}(-[a-z]+)+-[0-9]+$", var.aws_region))
    error_message = "Supply an AWS region name."
  }
}
variable "availability_zone" {
  description = "A standard AZ in aws_region for the single persistent sandbox host."
  type        = string
}
variable "name" {
  type    = string
  default = "team41-mel"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,30}$", var.name))
    error_message = "Use 3-31 lowercase letters, digits or hyphens, starting with a letter."
  }
}
variable "deploy_host" {
  description = "False creates network, registries, IAM and the protected persistent data volume. Enable only after images and the existing secret are ready."
  type        = bool
  default     = false
}
variable "instance_type" {
  type    = string
  default = "t3.medium"
  validation {
    condition     = contains(["t3.small", "t3.medium", "t3.large"], var.instance_type)
    error_message = "Deployment images are linux/amd64; choose a listed x86 instance type."
  }
}
variable "data_volume_gib" {
  type    = number
  default = 30
  validation {
    condition     = var.data_volume_gib >= 20 && var.data_volume_gib <= 1000 && floor(var.data_volume_gib) == var.data_volume_gib
    error_message = "Choose an integer data volume size from 20 to 1000 GiB."
  }
}
variable "image_digests" {
  description = "Immutable pushed image digests keyed api, kevin and farmerloop. Host launch requires all three."
  type        = map(string)
  default     = {}
  validation {
    condition     = alltrue([for k, v in var.image_digests : contains(["api", "kevin", "farmerloop"], k) && can(regex("^sha256:[0-9a-f]{64}$", v))])
    error_message = "Use only api/kevin/farmerloop keys with sha256 image digests."
  }
}
variable "operator_secret_arn" {
  description = "Existing Secrets Manager secret in the destination account/region, JSON keys primary_token and kevin_token, each at least 16 characters. Values stay outside Terraform."
  type        = string
  default     = ""
}
variable "operator_secret_kms_key_arn" {
  description = "Optional existing customer KMS key ARN used to encrypt the operator secret; grants only decrypt via Secrets Manager."
  type        = string
  default     = ""
  validation {
    condition     = var.operator_secret_kms_key_arn == "" || can(regex("^arn:aws:kms:[a-z0-9-]+:[0-9]{12}:key/[a-zA-Z0-9-]+$", var.operator_secret_kms_key_arn))
    error_message = "Use an exact KMS key ARN, or empty for the AWS managed key."
  }
}
variable "allow_paid_inference" {
  description = "Explicit Bedrock opt-in. Defaults off for every runtime."
  type        = bool
  default     = false
}
variable "bedrock_resource_arns" {
  description = "Explicit foundation-model and inference-profile ARNs authorized by the target owner. For cross-region profiles list destination model ARNs too. Empty grants no inference."
  type        = list(string)
  default     = []
  validation {
    condition     = alltrue([for arn in var.bedrock_resource_arns : can(regex("^arn:aws:bedrock:[a-z0-9-]+:([0-9]{12})?:(foundation-model|inference-profile|application-inference-profile)/[^*]+$", arn))])
    error_message = "Use exact commercial AWS Bedrock model/profile ARNs without wildcards."
  }
}
variable "bedrock_model_id" {
  description = "Explicit target-authorized Bedrock model/profile ID, only used if paid inference enabled."
  type        = string
  default     = ""
  validation {
    condition     = var.bedrock_model_id == "" || can(regex("^[A-Za-z0-9][A-Za-z0-9:./_-]{0,511}$", var.bedrock_model_id))
    error_message = "Use a model/profile ID or ARN with only letters, digits, colon, dot, slash, underscore and hyphen."
  }
}

check "target_configuration" {
  assert {
    condition     = startswith(var.availability_zone, var.aws_region) && can(regex("^[a-z]{2}(-[a-z]+)+-[0-9]+[a-z]$", var.availability_zone))
    error_message = "Choose a standard availability zone in the explicitly selected region."
  }
}
variable "enable_https" {
  description = "Future HTTPS/custom-domain upgrade. HTTP default exposes only synthetic Streamlit demo; operator APIs stay SSM-only."
  type        = bool
  default     = false
}
variable "domain_name" {
  description = "Owned application hostname (for example mel.example.org). Terraform also uses demo.<hostname> and prototype-api.<hostname>. No URL exists until deployment and DNS validation."
  type        = string
  default     = ""
  validation {
    condition     = var.domain_name == "" || can(regex("^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$", var.domain_name))
    error_message = "Supply an owned lowercase DNS hostname without scheme, wildcard or trailing dot."
  }
}
variable "route53_zone_id" {
  description = "Existing public Route53 hosted zone in the explicitly targeted account, required only when enable_https=true."
  type        = string
  default     = ""
  validation {
    condition     = var.route53_zone_id == "" || can(regex("^Z[A-Z0-9]+$", var.route53_zone_id))
    error_message = "Supply an existing Route53 hosted zone ID."
  }
}
variable "second_availability_zone" {
  description = "Second standard AZ in aws_region; ALB requires two AZs."
  type        = string
}
