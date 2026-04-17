from __future__ import annotations

import io
import shutil
import tarfile
from pathlib import Path, PurePosixPath

from .config import Settings
from .errors import FileTooLargeError, PathNotAllowedError, UnsafeArchiveError
from .models import OutputFile


class PathPolicy:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.input_roots = [self._root(root) for root in settings.allowed_input_roots]
        self.output_roots = [self._root(root) for root in settings.allowed_output_roots]

    @staticmethod
    def _root(path: Path) -> Path:
        return path.expanduser().resolve(strict=False)

    @staticmethod
    def _is_under(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False

    def _require_under(self, path: Path, roots: list[Path], kind: str) -> Path:
        resolved = path.expanduser().resolve(strict=False)
        if any(self._is_under(resolved, root) for root in roots):
            return resolved
        allowed = [str(root) for root in roots]
        raise PathNotAllowedError(
            f"{kind} path is outside allowed roots: {path}",
            details={"path": str(path), "allowed_roots": allowed},
        )

    def validate_input_file(self, path: str | Path) -> Path:
        raw_path = Path(path).expanduser()
        try:
            resolved = raw_path.resolve(strict=True)
        except FileNotFoundError as exc:
            raise PathNotAllowedError(
                f"Input file does not exist: {raw_path}",
                code="input_not_found",
                details={"path": str(raw_path)},
            ) from exc

        self._require_under(resolved, self.input_roots, "input")
        if not resolved.is_file():
            raise PathNotAllowedError(
                f"Input path is not a regular file: {raw_path}",
                code="input_not_file",
                details={"path": str(raw_path)},
            )
        size = resolved.stat().st_size
        if size > self.settings.max_file_bytes:
            raise FileTooLargeError(
                f"Input file exceeds max_file_bytes: {raw_path}",
                details={
                    "path": str(raw_path),
                    "size": size,
                    "max_file_bytes": self.settings.max_file_bytes,
                },
            )
        return resolved

    def validate_output_dir(self, path: str | Path | None = None) -> Path:
        raw_path = Path(path).expanduser() if path else self.output_roots[0]
        resolved = self._require_under(raw_path, self.output_roots, "output")
        resolved.mkdir(parents=True, exist_ok=True)
        if not resolved.is_dir():
            raise PathNotAllowedError(
                f"Output path is not a directory: {raw_path}",
                code="output_not_dir",
                details={"path": str(raw_path)},
            )
        return resolved

    def ensure_output_file_allowed(self, output_dir: Path, relative_name: PurePosixPath) -> Path:
        if relative_name.is_absolute():
            raise UnsafeArchiveError(
                f"Archive member uses an absolute path: {relative_name}",
                details={"member": str(relative_name)},
            )
        if any(part in ("", ".", "..") for part in relative_name.parts):
            raise UnsafeArchiveError(
                f"Archive member contains an unsafe path segment: {relative_name}",
                details={"member": str(relative_name)},
            )
        target = output_dir.joinpath(*relative_name.parts).resolve(strict=False)
        self._require_under(target, [output_dir.resolve(strict=False)], "archive output")
        self._require_under(target, self.output_roots, "output")
        return target


def safe_extract_tar_bytes(
    data: bytes,
    output_dir: Path,
    policy: PathPolicy,
    *,
    overwrite: bool = False,
) -> list[OutputFile]:
    outputs: list[OutputFile] = []
    seen: set[Path] = set()
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as archive:
        for member in archive.getmembers():
            if member.isdir():
                if member.name in ("", "."):
                    continue
                relative_dir = PurePosixPath(member.name)
                target_dir = policy.ensure_output_file_allowed(output_dir, relative_dir)
                target_dir.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                continue

            relative_name = PurePosixPath(member.name)
            target = policy.ensure_output_file_allowed(output_dir, relative_name)
            if target in seen:
                raise UnsafeArchiveError(
                    f"Archive contains duplicate output path: {member.name}",
                    details={"member": member.name},
                )
            seen.add(target)
            if target.exists() and not overwrite:
                raise UnsafeArchiveError(
                    f"Output file already exists: {target}",
                    code="output_exists",
                    details={"path": str(target)},
                )

            source = archive.extractfile(member)
            if source is None:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("wb") as handle:
                shutil.copyfileobj(source, handle)
            outputs.append(OutputFile(path=str(target), filename=target.name))
    return outputs
