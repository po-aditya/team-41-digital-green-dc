# Terraform package validation

Independently reviewed and tested on 4 November 2026. This package prepares a
future deployment into an explicitly selected AWS account. **No live AWS plan,
apply, account creation, registry push, AWS API request or paid inference was
performed during this validation.** Provider packages and public Python/container
build dependencies were downloaded for local tests only.

The final default is **HTTP in us-east-1**, exposing only Kevin's synthetic-data
Streamlit demo through the ALB DNS name. The primary and prototype operator APIs
have no public listener in this mode; operators use encrypted SSM tunnels. Public
UI containers receive no operator token or AWS credentials, and their paid calls
remain disabled. The optional custom-domain HTTPS mode adds ACM DNS validation
and Cognito authentication before forwarding to the three application runtimes.
There is no live application URL until the target owner deploys the package.

## Completed checks

| Check | Result |
| --- | --- |
| Terraform formatting | `terraform fmt -check -recursive` passed |
| Provider/schema validation | Passed with Terraform 1.15.6 and locked AWS provider 6.71.0 |
| Native mocked-provider cases | **9 passed, 0 failed**; no live provider resource actions |
| Packaging/security contract tests | **8 passed** |
| Root README, packaging and workspace preservation regressions | **57 passed** |
| Actual Terraform template rendering | Passed using Terraform's `templatefile` function with synthetic fixture values |
| Bash syntax | Outer rendered bootstrap and all three embedded shell scripts passed `bash -n` |
| ShellCheck | Outer bootstrap, storage script, startup script and FarmerLoop job passed with warning severity enabled |
| Primary deployment image | Actual local linux/amd64 build passed; dependency integrity and `pip check` passed |
| Kevin deployment image | Actual local linux/amd64 build passed; dependency integrity check passed |
| FarmerLoop deployment image | Actual local linux/amd64 build passed; dependency integrity check passed |

The nine native cases cover default no-host/paid-off behavior, encrypted local
EBS, ALB-only application ingress, a single host with IMDSv2 and hop limit 1,
immutable image references, refusal of a foreign-account secret, missing image
digests, insufficient paid-model configuration, shell metacharacters and a
placeholder account ID. They also cover optional HTTPS/Cognito routing and the
HTTP-only synthetic UI route. Computed mock identities are distinct fixtures;
routing and policy relationships are asserted from the actual configuration.

All local images used unique test tags. No existing application containers were
stopped, no registry authentication or push was performed, and the user's Docker
configuration was not changed. Builds used an isolated empty Docker credential
configuration. The Linux images ran under emulation on the existing local daemon;
expected emulation/deprecation warnings did not cause failed assertions.

## Actual container smoke tests

Tests used disposable containers with **network disabled**, a read-only root
filesystem, UID 10001, dropped capabilities, no-new-privileges, writable temporary
runtime storage, no AWS credentials and paid inference disabled.

- **Primary:** health endpoint returned 200; an unauthenticated operational read
  returned 401; a synthetic test operator token allowed the read. All eight
  end-to-end offline demo cases passed with the bundled participant pack. The
  final tracked-context image was checked again after its rebuild.
- **Kevin:** Streamlit AppTest rendered all four pages without app exceptions:
  Agent, Season simulation, Evaluation and Dataset. The public UI environment
  contained no operator token. Separate private API probes returned public health
  200, unset operator configuration 503, missing authorization 401 and authorized
  read 200. The real model wrapper refused a paid call before reaching a client.
- **FarmerLoop:** the offline feedback demo completed with 20 schema-valid
  records, checked provenance and a negative-outcome follow-up signal.

## Security and persistence review

The source review covered IAM scope, account guards, runtime secrets, shell
interpolation, file permissions, container identity/networking, public routing,
EBS lifecycle and build-context contents. The final package has no apparent real
credential literals or developer-specific absolute paths in executable deployment
code. Commands use argument arrays rather than a constructed shell invocation.
The build helper copies selected Git-tracked files, rejects symlink inputs and
excludes secret/cache filenames; a canary regression checks those exclusions.

The review identified and verified repairs for these concrete integration issues:

1. Docker restart policies could start the primary before persistent storage was
   mounted on reboot. A required storage service now precedes Docker and refuses
   an unexpected volume/filesystem. Detachment requests stop the instance first;
   the protected data volume is not silently destroyed. These ordering controls
   were checked in configuration and rendered scripts, not on a live EC2 reboot.
2. Flattening Kevin's code into `/app` caused an eager path expression to fail
   despite its data environment override. The deployment image now preserves the
   prototype directory layout. Rebuilding and executing all UI pages confirmed
   the correction without modifying the original application source.
3. The public UI originally shared the private prototype API's token environment.
   Its startup arguments now receive no token file; only private API containers
   receive the corresponding runtime token.
4. Broad source-directory copies could include untracked/generated local files.
   The helper now stages selected tracked files with explicit secret/cache
   exclusions and tests this behavior.

Operator secret values are fetched only at future host startup; Terraform does
not read them or write them into user data. Container/host administrators remain
trusted and can inspect runtime environments. The optional Cognito app client
has a generated secret in Terraform state: use the documented encrypted,
restricted, locked remote backend. The package does not claim that state is
secret-free.

No new blocking issue remains for publishing this **undeployed sandbox package**
within the reviewed scope. This is not a production security certification or an
online dependency vulnerability database audit.

## Reproduce the local checks

From a clean Git clone with Terraform 1.10+, Python 3.12+, Git, Bash, ShellCheck
and a working Docker daemon:

```sh
terraform -chdir=Terraform init -backend=false
terraform -chdir=Terraform fmt -check -recursive
terraform -chdir=Terraform validate
terraform -chdir=Terraform test
python3 -m unittest discover -s Terraform/tests -p 'test_*.py'
python3 Terraform/build_images.py api --tag team41-local-test-api:review
python3 Terraform/build_images.py kevin --tag team41-local-test-kevin:review
python3 Terraform/build_images.py farmerloop --tag team41-local-test-farmerloop:review
```

The native Terraform test file mocks AWS. These commands do not constitute
approval to run a live plan or deployment. The image helper builds locally and
never pushes. See the [deployment instructions](README.md) for the separate
future target-owner procedure and inputs.

## Properties still requiring target-account validation

No local test establishes target IAM/model access, AMI/package bootstrap success,
ALB reachability, actual DNS/certificate issuance, Cognito login, live SSM access,
EBS reboot/replacement behavior or paid Bedrock behavior. Review a target-account
plan and run those smoke/restore checks on the deployment computer before relying
on the service. HTTP remains unencrypted and suitable only for the synthetic demo.

The single EC2 host and single-AZ SQLite volume are not highly available. No
central log retention, backup retention, restore proof or production identity/role
model was added. The alternate Python dependency ranges remain unpinned; publish
immutable image digests to identify a tested release. This Terraform work does
not close the previously documented survey-quality, timing or Hindi-review gaps.
