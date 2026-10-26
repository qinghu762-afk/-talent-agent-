from pathlib import Path
p=Path(__file__).parent/'generate_compose.py';s=p.read_text('utf-8-sig');s=s.replace("'MYSQL_DATABASE':'talent'", "'MYSQL_ROOT_HOST':'%','MYSQL_DATABASE':'talent'");p.write_text(s,encoding='utf-8')
for name in ['backup.ps1','restore.ps1']:
 p=Path(__file__).parents[1]/'scripts'/name;s=p.read_text('utf-8-sig');s=s.replace('run --rm --network none','run --rm --pull never --network none');p.write_text(s,encoding='utf-8')
