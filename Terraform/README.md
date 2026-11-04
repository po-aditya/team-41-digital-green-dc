# AWS deployment package

This package prepares the current application for **a different, explicitly
selected AWS account**, using `us-east-1` by default. The owner can clone it on
another computer and deploy it there. **Nothing has been deployed:** no live AWS
plan, apply, account creation, image push or paid inference was run here.

The default publishes an **HTTP synthetic demo at the AWS ALB DNS name**. No
custom domain is required. Operator APIs remain reachable through encrypted SSM
port forwarding; their tokens are never meant to be sent over public HTTP.
Optional trusted HTTPS/custom-domain configuration is included for a later
upgrade. Terraform outputs the future application URL after a real deployment;
there is no live URL now. See [independent validation](VALIDATION.md) for the
local checks, container smoke tests and limits. Public primary/prototype API URL outputs are null
in HTTP mode; use their SSM tunnels until HTTPS is enabled.

## What runs

| Component | Runtime and default access |
| --- | --- |
| Primary MEL application | One API container, SQLite on encrypted EBS; operator token required, SSM access in HTTP mode |
| Kevin prototype | Separate Streamlit container, public synthetic demo; separate token-protected API, SSM-only in HTTP mode |
| FarmerLoop | Separate image, on-demand offline feedback job, no network |

The prototypes remain separate applications. Kevin's UI does not connect to the
primary database/API. Live model-generation UI actions are disabled by the
paid-call gate; public users can inspect datasets, recorded evaluation reports,
and simulate the bundled worked-example surveys/season. This is not a public
live-model inference service. The primary template workflow is available through
its authenticated API over an SSM tunnel.

All three images include the unchanged synthetic participant pack. A clean
context build helper avoids the root `.dockerignore` excluding the data or
prototype sources. The source images target `linux/amd64`. The primary uses
hash-locked dependencies; alternate prototypes retain upstream dependency ranges.
Release identity is the immutable pushed image digest, not a mutable tag.

## Infrastructure and safety boundaries

- Internet-facing Application Load Balancer across two AZs, with port 80 serving
  only the synthetic Streamlit demo in default HTTP mode. No public listener
  forwards to either operator API. No Cognito login or secret transport occurs
  over HTTP. HTTP is unencrypted: synthetic data only, no personal information,
  credentials or live farmer use.
- One x86 Amazon Linux 2023 EC2 host, default `t3.medium`, encrypted gp3 persistent
  EBS and encrypted root storage. Its application ports accept only the ALB
  security group, never arbitrary internet clients. SSH is never opened; use
  SSM. The host has an outbound public IPv4 address for downloads and AWS APIs.
- One primary SQLite writer on one local EBS filesystem. A required storage
  service verifies/mounts the exact volume before Docker can restart, including
  after reboot. Unknown disk signatures are refused; only an empty disk is
  initialized. No EFS, replica scaling, PostgreSQL or high-availability claim.
- Tokens come from an existing Secrets Manager ARN, fetched at future host
  startup into root-only `/run/team41` files. Terraform never reads operator
  token values. Public UI gets **no operator token**. Primary and prototype API
  tokens are separate. Docker/SSM administrators remain trusted.
- IMDSv2 with hop limit 1. Only the trusted primary uses host networking; bridged
  prototype metadata access is blocked. Alternates always have paid calls off;
  FarmerLoop's offline job also has no network. Primary paid inference defaults
  off and is prohibited in HTTP mode, even if accidentally requested. HTTPS
  opt-in needs exact target-authorized Bedrock model/profile ARNs.
- Explicit `target_account_id` provider allowlist rejects credentials for a
  different account. No local/personal profile is assumed; this stack does not
  create AWS accounts or Organizations member accounts.

This deploys the current **SQLite sandbox**, not the documents' preferred
RDS/PostgreSQL design. RDS needs application changes first. It does not resolve
survey relevance, timing-policy, Hindi review or actual Bedrock evaluation gaps.

## Prepare the other computer

These are future destination-owner instructions, not executed deployment steps.

1. Clone this repository. Install Terraform 1.10+, AWS CLI v2, Python 3.12+, Docker
   with linux/amd64 build support, and the AWS Session Manager plugin.
2. Obtain the owner's deployment role/credentials and verify their destination
   account ID. Configure the AWS credential chain explicitly on that computer.
   Never put credentials into Terraform, this repository, image build arguments
   or images. This implementation supports commercial AWS (`arn:aws`).
3. Create an operator secret **outside Terraform**, in the destination account
   and `us-east-1` (or your explicitly selected region). Its JSON has
   `primary_token` and `kevin_token`, separate random ASCII tokens of at least
   16 characters without whitespace. Supply only the ARN here. If a
   customer-managed KMS key encrypts it, supply the key ARN and an allowing key
   policy too.
4. Configure a restricted encrypted remote backend before any apply.
   `backend.s3.hcl.example` describes a preexisting administrator-owned bucket
   and locking. Add a local ignored `backend.tf` containing
   `terraform { backend "s3" {} }` and initialize with the backend settings.
   Keep state and saved plans encrypted and out of Git. Optional HTTPS mode
   creates a Cognito app-client secret that **can appear in Terraform state**;
   only the operator secret values are kept outside Terraform.
5. Copy `terraform.tfvars.example` to ignored `terraform.tfvars`. Replace the
   example target account ID with the authorized one. Keep `deploy_host=false`,
   `enable_https=false` and `allow_paid_inference=false` initially. Set two AZs
   in the selected region. No domain, Route53 zone or certificate is needed for
   HTTP. Obtain a reviewed deployment policy for EC2/VPC/EBS/ECR/IAM/ALB/SSM;
   the optional HTTPS path also needs ACM/Route53/Cognito permissions.

## Local checks that do not deploy

Provider installation downloads from HashiCorp, not AWS. Native tests use a mocked
provider and do not need AWS credentials.

```sh
terraform -chdir=Terraform init -backend=false
terraform -chdir=Terraform fmt -check -recursive
terraform -chdir=Terraform validate
terraform -chdir=Terraform test
python3 -m unittest discover -s Terraform/tests -p 'test_*.py'
```

Backend-disabled initialization is for local validation. Initialize the real,
restricted remote backend separately before a future live plan/apply.

## Future deployment sequence

1. On the destination computer, initialize the real backend and generate/review
   a saved plan with `deploy_host=false`. Apply only after the owner's approval.
   This foundation creates paid ALB/EBS/network/registry/IAM infrastructure but
   no application host. The public URL has no healthy backend until stage two.
2. Read `image_repositories`. Build all three images from the repository root,
   using each corresponding ECR output and a unique release tag:

   ```sh
   python3 Terraform/build_images.py api --tag '<api-repository>:release-001'
   python3 Terraform/build_images.py kevin --tag '<kevin-repository>:release-001'
   python3 Terraform/build_images.py farmerloop --tag '<farmerloop-repository>:release-001'
   ```

   The helper builds only; it never pushes or contacts AWS.
3. Authenticate Docker to destination ECR using the destination credentials and
   selected region: `aws ecr get-login-password --region us-east-1 | docker login
   --username AWS --password-stdin <target-registry>`. Explicitly `docker push`
   each release tag. Record each ECR `imageDigest`; set the three `image_digests`
   values to those `sha256:...` digests. ECR tags are immutable.
4. Supply the existing operator secret ARN; set `deploy_host=true`. Review and
   approve a second saved plan, then apply it on that computer. Bootstrap waits
   for/mounts persistent storage, pulls digest images, retrieves API tokens and
   starts isolated containers. Keep paid inference off.
5. After bootstrap and ALB target health succeed, read `public_application_url`:
   it is `http://<AWS-generated-ALB-DNS-name>` by default. The exact output command is
   `terraform -chdir=Terraform output -raw public_application_url`. This is the public
   synthetic Streamlit demo. View recorded reports or use its worked-example
   season controls; model-generation actions intentionally fail closed. Do not
   enter credentials or personal/farmer data on this HTTP interface.
6. Use `ssm_primary_api_command` to open an encrypted local tunnel to port 8000.
   Visit `http://127.0.0.1:8000/docs` and supply the primary operator header to
   run ingestion/template generation and inspect results. The HTTP localhost
   connection is inside the SSM-encrypted transport, not public HTTP. A similar
   SSM tunnel with remote port 8001 reaches the separate Kevin API with its
   own token. An authorized SSM shell can run `/opt/team41/farmerloop-demo`.
7. Verify schemas, answers, negative-follow-up routing and caps. Inspect
   `journalctl -u team41` and bounded `docker logs` via SSM. Test a reboot and
   confirm the same EBS-backed database is retained before trusting persistence.

## Later upgrade to trusted HTTPS

Have the target owner supply an owned lowercase application hostname and an
existing public Route53 zone authoritative for it and its two child names. Set
`enable_https=true`, `domain_name` and `route53_zone_id`. Review the plan: it adds
ACM DNS validation, HTTPS 443, DNS aliases and an administrator-managed Cognito
user pool, and converts port 80 to HTTPS redirect. DNS delegation/validation must
complete; the raw AWS ALB hostname does not become a trusted custom certificate.

HTTPS hostnames are `https://<domain_name>` for the primary API,
`https://demo.<domain_name>` for Streamlit and
`https://prototype-api.<domain_name>` for Kevin's API. Every application route
requires Cognito first; self-signup is disabled and administrators invite users.
APIs additionally require their operator header. Programmatic clients also need
an ALB authenticated session; no machine-to-machine OAuth workflow is supplied.
Terraform outputs the three URLs and `operator_user_pool_id` after deployment.

Only then consider `allow_paid_inference=true`, an explicitly authorized
`bedrock_model_id` and exact `bedrock_resource_arns`. Cross-region profiles need
the applicable profile and destination model ARNs; verify access and pricing in
the destination account. Changing host configuration replaces the host while
reusing its protected EBS volume, so expect downtime. Primary spending controls
meter only its own runtime; alternate runtimes remain paid-disabled.

## Operations and limits

The ALB is multi-AZ, but a single host/EBS AZ is not highly available. Volume detachment stops the
instance first to avoid hot-detaching active SQLite storage. Host
replacement or failure causes downtime. No backup retention is configured:
implement SQLite-consistent backups and restore tests before non-disposable use.
Use SQLite's backup API or quiesce the application; raw snapshots of a running
SQLite/WAL filesystem are not claimed application-consistent. Volume
`prevent_destroy` intentionally blocks ordinary teardown until an administrator
reviews retention and makes an explicit change.

Root/SSM/Docker administrators can inspect container environments. Secret rotation
needs a reviewed service restart. Cognito does not add per-user roles or attribution
inside shared-token APIs. Logs are bounded locally; no centralized retention or
alarms are configured. Future destination validation must include cloud plan,
DNS/TLS when enabled, auth, bootstrap, reboot/replacement persistence and Bedrock
permission checks. Local/mock verification cannot establish those live properties.

## References checked

- [AWS ALB Cognito requirements](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/listener-authenticate-users.html)
- [AWS Session Manager](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager.html)
- [AWS Terraform provider account guards](https://docs.aws.amazon.com/prescriptive-guidance/latest/terraform-aws-provider-best-practices/security.html)
- [HashiCorp AWS EC2 resource](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/instance)
- [HashiCorp mocked-provider tests](https://developer.hashicorp.com/terraform/language/tests/mocking)
