#!/usr/bin/env python3
"""Local export audit, not a guarantee of legal clearance or perfect secret detection."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
ROOT=Path(__file__).resolve().parents[1]
ALLOWED_DIRS={'docs','prompts','schemas','src','tests','scripts','examples','reports'}
ROOT_FILES={'README.md','.gitignore','AGENTS.md','requirements.txt','source_manifest.json','.env.example'}
SKIP={'.git','.DS_Store','__pycache__','.venv','venv','private_data','local_only','data','inputs','gold','runs','results','exports','cache'}
SECRET=re.compile(r'(?:sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{25,}|github_pat_[A-Za-z0-9_]{25,}|AKIA[A-Z0-9]{16})')
PRIVATE_PATH=re.compile(r'/(?:Users|home)/[^/\s]+/')
def main():
    problems=[];count=0;size=0
    # Check tracked paths even when a later ignore rule would hide them.
    result=subprocess.run(['git','ls-files','-z'],cwd=ROOT,capture_output=True)
    if result.returncode:raise SystemExit('Cannot inspect Git index; preparation audit incomplete.')
    tracked={p for p in result.stdout.decode().split('\0') if p}
    for p in ROOT.rglob('*'):
        rel=p.relative_to(ROOT)
        if any(x in SKIP for x in rel.parts):
            if rel.as_posix() not in tracked:continue
            problems.append(str(rel)+': tracked private/cache path (ignore does not remove Git history)')
        if p.is_symlink():problems.append(str(rel)+': symlink');continue
        if not p.is_file():continue
        count+=1;size+=p.stat().st_size
        if (len(rel.parts)==1 and p.name not in ROOT_FILES) or (len(rel.parts)>1 and rel.parts[0] not in ALLOWED_DIRS):problems.append(str(rel)+': not allowlisted')
        if p.suffix.lower() in {'.ipynb','.xlsx','.xls','.pdf','.zip','.log','.pem','.key'} or (p.name.startswith('.env') and p.name!='.env.example'):problems.append(str(rel)+': private/binary file type')
        try:text=p.read_text(encoding='utf-8')
        except UnicodeDecodeError:problems.append(str(rel)+': unexpected binary');continue
        if SECRET.search(text):problems.append(str(rel)+': possible credential (value withheld)')
        if PRIVATE_PATH.search(text):problems.append(str(rel)+': absolute personal path')
        if p.suffix=='.jsonl':
            if rel.parts[0]!='examples':problems.append(str(rel)+': JSONL outside synthetic examples')
            else:
                try:
                    if not all(json.loads(line).get('synthetic') is True for line in text.splitlines() if line.strip()):problems.append(str(rel)+': JSONL not explicitly synthetic')
                except ValueError:problems.append(str(rel)+': malformed synthetic JSONL')
    manifest=json.loads((ROOT/'source_manifest.json').read_text(encoding='utf-8'))
    for name,info in manifest['copied_or_extracted_files'].items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=info['sha256']:problems.append(name+': frozen-source hash differs')
    cases=json.loads((ROOT/'examples/synthetic_cases.json').read_text(encoding='utf-8'))
    if not all(c['record_id'].startswith('SYNTHETIC_') for c in cases):problems.append('examples: non-synthetic article')
    case_index=json.loads((ROOT/'examples/case_index.json').read_text(encoding='utf-8'))
    if len(case_index['cases'])!=8:problems.append('real case index: expected eight cases')
    for p in [ROOT/'README.md',*(ROOT/'docs').glob('*.md')]:
        for link in re.findall(r'\]\(([^)]+)\)',p.read_text(encoding='utf-8')):
            if '://' in link or link.startswith('#'):continue
            if not (p.parent/link.split('#',1)[0]).exists():problems.append(str(p.relative_to(ROOT))+': broken local link '+link)
    if problems:raise SystemExit('AUDIT FAILED\n'+'\n'.join(problems))
    print('AUDIT PASS:',count,'allowlisted text files,',size,'bytes; no detected credential, private path or corpus payload.')
    print('This is a preparation scan, not permission to publish confidential/copyrighted material.')
if __name__=='__main__':main()
