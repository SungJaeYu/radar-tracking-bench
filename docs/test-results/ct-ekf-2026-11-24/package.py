"""Archive the completed recording and verify its extracted independent reanalysis."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

HERE = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('recording', type=Path)
    parser.add_argument('--output', type=Path, default=HERE)
    args = parser.parse_args()
    base, out = args.recording.resolve(), args.output.resolve()
    manifest = json.loads((base/'board/manifest.json').read_text())
    assert manifest['complete'] and manifest['restored']
    files = sorted(p for p in base.rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    inventory = [dict(path=str(p.relative_to(base)), bytes=p.stat().st_size, sha256=digest(p)) for p in files]
    archive = out/'evidence.tar.gz'
    with tarfile.open(archive, 'w:gz') as stream:
        for path in files:
            stream.add(path, arcname=str(Path('recording')/path.relative_to(base)), recursive=False)
    (out/'archive-inventory.json').write_text(json.dumps(inventory, indent=2)+'\n')
    outputs = ['summary.json','summary.csv','host-aggregate.csv','paired.csv','board-series.csv.gz']
    with tempfile.TemporaryDirectory(prefix='ct-reanalysis-') as temporary:
        extracted = Path(temporary)
        with tarfile.open(archive) as stream:
            stream.extractall(extracted, filter='data')
        for item in inventory:
            path = extracted/'recording'/item['path']
            assert path.stat().st_size == item['bytes'] and digest(path) == item['sha256']
        subprocess.run([sys.executable,str(HERE/'analyze.py'),str(extracted/'recording'),
                        '--output',str(extracted/'analysis')],check=True)
        for name in outputs:
            assert (out/name).read_bytes() == (extracted/'analysis'/name).read_bytes(), name
    verification = dict(archive_sha256=digest(archive), archive_bytes=archive.stat().st_size,
                        files_verified=len(inventory), byte_identical_reanalysis=outputs,
                        complete=True, restored=True)
    (out/'verification.json').write_text(json.dumps(verification,indent=2)+'\n')
    print(json.dumps(verification))

if __name__ == '__main__':
    main()
