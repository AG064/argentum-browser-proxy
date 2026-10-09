"""Contained file access for the proxy's generated streams and static assets."""
from pathlib import Path, PureWindowsPath
import shutil
from werkzeug.exceptions import NotFound


def contained_file(directory, filename, *, hls=False):
    try:
        if not filename or '\x00' in filename or '\\' in filename or ':' in filename:
            raise NotFound()
        if Path(filename).is_absolute() or PureWindowsPath(filename).is_reserved():
            raise NotFound()
        if hls and (Path(filename).name != filename or Path(filename).suffix not in {'.m3u8', '.ts'}):
            raise NotFound()
        root = Path(directory).resolve(strict=True)
        path = (root / filename).resolve(strict=True)
        if path == root or not path.is_relative_to(root) or not path.is_file():
            raise NotFound()
        return str(path)
    except (OSError, ValueError):
        raise NotFound() from None


def remove_stream_directory(directory, stream_root):
    root = Path(stream_root).resolve(strict=True)
    requested = Path(directory)
    target = requested.resolve(strict=True)
    if target == root or not target.is_relative_to(root) or requested.is_symlink():
        raise ValueError('Refusing to remove a directory outside the stream root')
    shutil.rmtree(target)
