"""Archive large raw sessions without deleting local originals; verify each file."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile

OUT=Path(__file__).resolve().parent
ROOT=OUT.parents[2]
archives={}
for relative in ('noise','spike','perf-load/session'):
    directory=OUT/relative
    destination=OUT/(relative.replace('/','-')+'.tar.gz')
    originals={str(p.relative_to(OUT)):hashlib.sha256(p.read_bytes()).hexdigest()
               for p in directory.rglob('*') if p.is_file()}
    with tarfile.open(destination,'w:gz') as archive:
        archive.add(directory,arcname=relative)
    restored={}
    with tarfile.open(destination,'r:gz') as archive:
        for member in archive.getmembers():
            if member.isfile():
                restored[member.name]=hashlib.sha256(archive.extractfile(member).read()).hexdigest()
    assert restored==originals
    archives[destination.name]=dict(sha256=hashlib.sha256(destination.read_bytes()).hexdigest(),
                                    files=len(originals),uncompressed_file_sha256=originals)
for folder,filename in [('noise','sweep.json'),('spike','spikes.json')]:
    source,=list((OUT/folder).glob('*/'+filename))
    shutil.copyfile(source,OUT/(folder+'-summary.json'))
paths=subprocess.check_output(['git','ls-files','pc_sim','fcc_app/src','fcc_app/*.conf','fcc_app/Kconfig'],cwd=ROOT,text=True).splitlines()
source_hashes={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in paths if (ROOT/name).is_file()}
manifest=dict(base_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
              source_sha256=source_hashes,archives=archives)
(OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps({name:{'files':item['files'],'sha256':item['sha256']} for name,item in archives.items()},indent=2))
