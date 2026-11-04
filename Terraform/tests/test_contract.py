"""Offline infrastructure contract tests, written before Terraform implementation."""
from pathlib import Path
import json
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]

class InfrastructureContract(unittest.TestCase):
    def test_target_account_guard_is_required(self):
        provider = (ROOT/'versions.tf').read_text()
        self.assertIn('allowed_account_ids = [var.target_account_id]', provider)
        self.assertNotIn('profile', provider)
        self.assertNotIn('access_key', provider)

    def test_no_public_ingress_and_sqlite_single_host(self):
        main = (ROOT/'main.tf').read_text()
        self.assertNotRegex(main, r'(?s)ingress\s*\{[^}]*cidr_blocks')
        public = (ROOT/'public.tf').read_text()
        self.assertIn('referenced_security_group_id = aws_security_group.alb.id', public)
        application_rule = re.search(r'resource "aws_vpc_security_group_ingress_rule" "application" \{(.*?)\n\}', public, re.S).group(1)
        self.assertNotIn('cidr_', application_rule)
        self.assertNotIn('aws_efs_', main)
        self.assertIn('http_tokens                 = "required"', main)
        self.assertIn('prevent_destroy = true', main)
        self.assertIn('encrypted         = true', main)

    def test_paid_inference_off_and_secret_not_in_terraform(self):
        variables = (ROOT/'variables.tf').read_text()
        self.assertRegex(variables, r'(?s)variable "allow_paid_inference".*?default\s*= false')
        all_tf = '\n'.join(p.read_text() for p in ROOT.glob('*.tf'))
        self.assertNotIn('aws_secretsmanager_secret_version', all_tf)
        self.assertNotIn('secret_string', all_tf)
        self.assertIn('var.enable_https && var.allow_paid_inference', (ROOT/'iam.tf').read_text())
        script = (ROOT/'templates/bootstrap.sh.tftpl').read_text()
        self.assertIn('get-secret-value', script)
        self.assertNotIn('set -x', script)
        self.assertIn('chmod 600', script)

    def test_runtime_images_have_data_and_distinct_modules(self):
        for name in ('api', 'kevin', 'farmerloop'):
            text = (ROOT/'images'/f'{name}.Dockerfile').read_text()
            self.assertIn('data/participant-pack', text)
            self.assertIn('USER 10001', text)
        self.assertIn('prototypes/kevin', (ROOT/'images/kevin.Dockerfile').read_text())
        self.assertIn('farmerloop', (ROOT/'images/farmerloop.Dockerfile').read_text())

    def test_storage_precedes_container_restart(self):
        script = (ROOT/'templates/bootstrap.sh.tftpl').read_text()
        self.assertIn('Requires=team41-storage.service', script)
        self.assertIn('Before=docker.service', script)
        self.assertIn('After=team41-storage.service', script)
        self.assertIn('trap \'docker logout', script)

    def test_optional_tls_and_authentication(self):
        public = (ROOT/'public.tf').read_text()
        self.assertRegex(public, r'type\s*=\s*"authenticate-cognito"')
        self.assertIn('allow_admin_create_user_only = true', public)
        self.assertRegex(public, r'protocol\s*=\s*"HTTPS"')
        self.assertIn('ssl_policy', public)
        self.assertIn('aws_acm_certificate_validation', public)

    def test_bootstrap_shell_syntax(self):
        text = (ROOT/'templates/bootstrap.sh.tftpl').read_text()
        # Replace only Terraform interpolation; shell variables are escaped as $${...}.
        text = re.sub(r'(?<!\$)\$\{[^}]+\}', 'placeholder', text).replace('$${', '${')
        result = subprocess.run(['bash', '-n'], input=text, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

if __name__ == '__main__':
    unittest.main()
