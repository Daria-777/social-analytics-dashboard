"""Atomic private .env writer; values never enter logs or error strings."""
import os
from pathlib import Path
import re
import tempfile


def save_env(path,updates):
    path=Path(path)
    if path.name!=".env" and not path.name.startswith(".env."):
        raise ValueError("Use an ignored .env or .env.* secret file")
    if path.name==".env.example" or path.is_symlink():
        raise ValueError("Refusing to store secrets in example files or symlinks")
    if any(any(char in str(value) for char in "\n\r$'") for value in updates.values()):
        raise ValueError("Unexpected secret file value format")
    contents=path.read_text() if path.exists() else ""
    lines=[line for line in contents.splitlines() if not any(re.match(rf"\s*(?:export\s+)?{key}\s*=",line) for key in updates)]
    contents="\n".join(lines+[f"{key}='{item}'" for key,item in updates.items()])+"\n"
    temp_name=None
    try:
        with tempfile.NamedTemporaryFile(mode="w",dir=path.parent,prefix=".instagram-secret-",delete=False) as temporary:
            temp_name=temporary.name
            os.chmod(temp_name,0o600)
            temporary.write(contents);temporary.flush();os.fsync(temporary.fileno())
        os.replace(temp_name,path)
        temp_name=None
    finally:
        if temp_name: os.unlink(temp_name)
