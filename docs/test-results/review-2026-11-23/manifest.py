"""Inventory all nonignored changed/new files without changing their contents."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).with_name('working-tree-manifest.json')

def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)

tracked = set(git('ls-files', '-z').decode().split('\0'))
paths = sorted(set(git('ls-files', '-m', '-o', '--exclude-standard', '-z').decode().split('\0')) - {''})
records = []
for name in paths:
    path = ROOT / name
    if path == OUT:
        continue
    records.append(dict(path=name, tracked=name in tracked,
                        category='test-evidence' if name.startswith('docs/test-results/') else 'source-docs-assets',
                        exists=path.is_file(), size_bytes=path.stat().st_size if path.is_file() else None,
                        sha256=hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None))
manifest = dict(generated_utc=datetime.now(timezone.utc).isoformat(),
                base_commit=git('rev-parse', 'HEAD').decode().strip(),
                branch=git('branch', '--show-current').decode().strip(),
                scope='Modified tracked and nonignored untracked files; manifest excludes itself. Prior-turn and current-turn changes included.',
                file_count=len(records), files=records)
OUT.write_text(json.dumps(manifest, indent=2) + '\n')
print(json.dumps({k:v for k,v in manifest.items() if k != 'files'}, indent=2))
