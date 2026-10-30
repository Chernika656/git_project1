"""Безопасная online-копия базы Facet через SQLite backup API."""
import argparse
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--database',type=Path,default=Path('/data/workspace.sqlite3'))
    parser.add_argument('--directory',type=Path,default=Path('/data/backups'))
    parser.add_argument('--keep',type=int,default=14)
    args=parser.parse_args()
    if not args.database.is_file():
        raise SystemExit(f'База не найдена: {args.database}')
    args.directory.mkdir(parents=True,exist_ok=True)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    target=args.directory/f'workspace-{stamp}.sqlite3'
    with sqlite3.connect(args.database) as source,sqlite3.connect(target) as destination:
        source.backup(destination)
        if destination.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
            raise SystemExit('Проверка резервной копии не пройдена.')
    target.chmod(0o600)
    backups=sorted(args.directory.glob('workspace-*.sqlite3'),reverse=True)
    for old in backups[max(1,args.keep):]:
        old.unlink()
    print(target)


if __name__=='__main__':
    main()
