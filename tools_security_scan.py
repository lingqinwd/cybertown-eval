from pathlib import Path
for p in Path('.').rglob('*'):
    if p.is_file() and any(x in p.parts for x in ['.git','.venv']): continue
    if p.suffix in {'.py','.md','.json','.txt','.yml','.yaml','.env'}:
        t=p.read_text(encoding='utf-8',errors='ignore').lower()
        for bad in ['sk-', 'api_key=', 'password=', 'cookie=']:
            if bad in t and p.name not in {'.env.example','SECURITY.md'}:
                print('review:',p,bad)
print('scan complete')
