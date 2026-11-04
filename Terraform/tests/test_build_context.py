"""Do not send untracked credentials/cache files to the Docker daemon."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('build_images', Path(__file__).resolve().parents[1]/'build_images.py')
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)

class BuildContext(unittest.TestCase):
    def test_only_tracked_safe_files_are_copied(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)/'source'; context=Path(directory)/'context'
            root.mkdir();context.mkdir()
            paths=['src/mel_agent/main.py','src/mel_agent/.env','src/mel_agent/credentials.json','src/mel_agent/__pycache__/cache.pyc']
            for path in paths+['src/mel_agent/untracked-key.txt']:
                p=root/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('canary')
            with patch.object(builder,'ROOT',root), patch.object(builder.subprocess,'check_output',return_value='\0'.join(paths)+'\0'):
                builder.stage_context('api',context)
            self.assertTrue((context/paths[0]).is_file())
            self.assertEqual([p.relative_to(context).as_posix() for p in context.rglob('*') if p.is_file()], [paths[0]])

if __name__ == '__main__': unittest.main()
