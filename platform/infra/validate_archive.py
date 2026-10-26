"""Validate cold snapshots, including safe plugin virtualenv links."""
from pathlib import PurePosixPath
import posixpath
import sys
import tarfile

RUNTIME_LINKS = {'/usr/local/bin/python3.12','/usr/local/bin/python3','/usr/bin/python3'}


def safe_name(value):
    name = PurePosixPath(value)
    if name.is_absolute() or '..' in name.parts or '\\' in value:
        raise ValueError('Unsafe archive path')
    return name


def validate(path):
    with tarfile.open(path, 'r:gz') as archive:
        members=archive.getmembers()
        links=set()
        seen=set()
        for member in members:
            name=safe_name(member.name)
            if name in seen:
                raise ValueError('Duplicate archive path')
            seen.add(name)
            if member.issym():
                if not member.linkname:raise ValueError('Empty symlink')
                target=posixpath.normpath(posixpath.join(str(name.parent),member.linkname))
                if target not in RUNTIME_LINKS:
                    safe_name(target)
                links.add(name)
            elif member.islnk():
                safe_name(member.linkname)
                links.add(name)
            elif not (member.isfile() or member.isdir()):
                raise ValueError('Device members cannot be restored')
        for member in members:
            if any(parent in links for parent in safe_name(member.name).parents):
                raise ValueError('Archive writes through a link')
        for member in members:
            if member.islnk():
                target=safe_name(member.linkname)
                if target in links or any(parent in links for parent in target.parents):
                    raise ValueError('Unsafe hardlink chain')
    return True


if __name__ == '__main__':
    validate(sys.argv[1])
