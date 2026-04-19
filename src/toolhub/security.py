from __future__ import annotations

import io
import ipaddress
import re
import shutil
import socket
import tarfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable
from urllib.parse import quote, urlsplit, urlunsplit

from .config import ConvertXRuntimeSettings, Settings, WebCaptureRuntimeSettings
from .errors import (
    FileTooLargeError,
    FormatNotSupportedError,
    InvalidFilenameError,
    InvalidUrlError,
    OutputExistsError,
    PathNotAllowedError,
    UnsafeArchiveError,
    UrlNotAllowedError,
)
from .models import OutputFile


Resolver = Callable[[str, int | None], Iterable[str]]
OUTPUT_EXTENSIONS = {"pdf": "pdf", "png": "png", "md": "md"}


class PathPolicy:
    def __init__(self, settings: Settings | ConvertXRuntimeSettings) -> None:
        runtime = settings.convertx() if isinstance(settings, Settings) else settings
        self.settings = runtime
        self.input_roots = [self._root(root) for root in runtime.allowed_input_roots]
        self.output_roots = [self._root(root) for root in runtime.allowed_output_roots]

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


@dataclass(frozen=True)
class CheckedUrl:
    raw_url: str
    normalized_url: str
    hostname: str
    port: int | None


class WebCapturePathPolicy:
    def __init__(self, settings: Settings | WebCaptureRuntimeSettings) -> None:
        runtime = settings.webcapture() if isinstance(settings, Settings) else settings
        self.settings = runtime
        self.output_roots = [self._root(root) for root in runtime.allowed_output_roots]

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
        raise PathNotAllowedError(
            f"{kind} path is outside allowed roots: {path}",
            details={"path": str(path), "allowed_roots": [str(root) for root in roots]},
        )

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

    def validate_filename_stem(self, value: str | None) -> str | None:
        if value is None:
            return None
        if not value or value != value.strip():
            raise InvalidFilenameError(
                "filename_stem must be a non-empty basename without surrounding whitespace.",
                details={"filename_stem": value},
            )
        if "/" in value or "\\" in value or "\x00" in value:
            raise InvalidFilenameError(
                "filename_stem must not contain path separators.",
                details={"filename_stem": value},
            )
        if value in {".", ".."}:
            raise InvalidFilenameError(
                "filename_stem must not be '.' or '..'.",
                details={"filename_stem": value},
            )
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._ -]{0,127}", value):
            raise InvalidFilenameError(
                "filename_stem contains unsupported characters.",
                details={"filename_stem": value},
            )
        return value

    def build_output_path(
        self,
        *,
        normalized_url: str,
        output_format: str,
        output_dir: str | Path | None = None,
        filename_stem: str | None = None,
        overwrite: bool = False,
    ) -> Path:
        extension = OUTPUT_EXTENSIONS.get(output_format)
        if extension is None:
            raise FormatNotSupportedError(
                f"Unsupported web capture output format: {output_format}",
                details={"output_format": output_format, "supported_formats": sorted(OUTPUT_EXTENSIONS)},
            )

        directory = self.validate_output_dir(output_dir)
        stem = self.validate_filename_stem(filename_stem) or default_capture_filename(
            normalized_url
        )
        target = directory.joinpath(f"{stem}.{extension}").resolve(strict=False)
        self._require_under(target, [directory.resolve(strict=False)], "output file")
        self._require_under(target, self.output_roots, "output file")
        if target.exists() and not overwrite:
            raise OutputExistsError(
                f"Output file already exists: {target}",
                details={"path": str(target)},
            )
        return target


def _quote_userinfo(value: str | None) -> str | None:
    if value is None:
        return None
    return quote(value, safe="")


def _blocked_ip_reason(ip: ipaddress._BaseAddress) -> str | None:
    checks = (
        ("loopback", ip.is_loopback),
        ("private", ip.is_private),
        ("link_local", ip.is_link_local),
        ("multicast", ip.is_multicast),
        ("unspecified", ip.is_unspecified),
        ("reserved", ip.is_reserved),
    )
    for label, blocked in checks:
        if blocked:
            return label
    if getattr(ip, "is_site_local", False):
        return "site_local"
    return None


def resolve_host_addresses(hostname: str, port: int | None) -> Iterable[str]:
    service = port or 80
    results = socket.getaddrinfo(hostname, service, type=socket.SOCK_STREAM)
    return [item[4][0] for item in results]


def _validate_host_is_public(
    hostname: str,
    *,
    port: int | None,
    resolver: Resolver,
) -> None:
    lowered = hostname.lower()
    if lowered == "localhost" or lowered.endswith(".localhost") or lowered.endswith(".local"):
        raise UrlNotAllowedError(
            f"Host is not allowed for web capture: {hostname}",
            details={"hostname": hostname, "reason": "localhost"},
        )

    stripped = lowered[1:-1] if lowered.startswith("[") and lowered.endswith("]") else lowered
    try:
        literal_ip = ipaddress.ip_address(stripped)
    except ValueError:
        literal_ip = None

    if literal_ip is not None:
        reason = _blocked_ip_reason(literal_ip)
        if reason is not None:
            raise UrlNotAllowedError(
                f"Host is not allowed for web capture: {hostname}",
                details={"hostname": hostname, "ip": str(literal_ip), "reason": reason},
            )
        return

    try:
        resolved = sorted(set(resolver(hostname, port)))
    except socket.gaierror as exc:
        raise UrlNotAllowedError(
            f"Host could not be resolved for web capture: {hostname}",
            details={"hostname": hostname, "reason": "resolution_failed", "error": str(exc)},
        ) from exc
    except OSError as exc:
        raise UrlNotAllowedError(
            f"Host could not be resolved for web capture: {hostname}",
            details={"hostname": hostname, "reason": "resolution_failed", "error": str(exc)},
        ) from exc

    for address in resolved:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            continue
        reason = _blocked_ip_reason(ip)
        if reason is not None:
            raise UrlNotAllowedError(
                f"Host resolved to a blocked address for web capture: {hostname}",
                details={"hostname": hostname, "ip": str(ip), "reason": reason},
            )


def validate_web_url(
    url: str,
    *,
    block_private_networks: bool = True,
    resolver: Resolver | None = None,
    allowed_schemes: Iterable[str] | None = None,
) -> CheckedUrl:
    raw = url.strip()
    if not raw:
        raise InvalidUrlError("URL is required.", details={"url": url})

    parts = urlsplit(raw)
    scheme = parts.scheme.lower()
    supported_schemes = tuple(allowed_schemes or ("http", "https"))
    if scheme not in supported_schemes:
        rendered_schemes = " and ".join(supported_schemes)
        raise InvalidUrlError(
            f"Only {rendered_schemes} URLs are supported.",
            details={
                "url": url,
                "scheme": parts.scheme,
                "allowed_schemes": list(supported_schemes),
            },
        )
    if not parts.hostname:
        raise InvalidUrlError("URL must include a hostname.", details={"url": url})
    try:
        port = parts.port
    except ValueError as exc:
        raise InvalidUrlError("URL contains an invalid port.", details={"url": url}) from exc

    userinfo = ""
    if parts.username is not None:
        userinfo = _quote_userinfo(parts.username) or ""
        if parts.password is not None:
            userinfo = f"{userinfo}:{_quote_userinfo(parts.password) or ''}"
        userinfo = f"{userinfo}@"

    hostname = parts.hostname.lower()
    netloc_host = hostname
    if ":" in hostname and not hostname.startswith("["):
        netloc_host = f"[{hostname}]"
    netloc = f"{userinfo}{netloc_host}"
    if port is not None:
        netloc = f"{netloc}:{port}"

    normalized = urlunsplit(
        (
            scheme,
            netloc,
            parts.path or "/",
            parts.query,
            "",
        )
    )

    if block_private_networks:
        _validate_host_is_public(
            hostname,
            port=port or (443 if scheme == "https" else 80),
            resolver=resolver or resolve_host_addresses,
        )

    return CheckedUrl(
        raw_url=url,
        normalized_url=normalized,
        hostname=hostname,
        port=port,
    )


def default_capture_filename(normalized_url: str) -> str:
    parts = urlsplit(normalized_url)
    host = re.sub(r"[^a-z0-9]+", "-", parts.hostname.lower()).strip("-") if parts.hostname else "page"
    path_bits = [
        re.sub(r"[^a-z0-9]+", "-", bit.lower()).strip("-")
        for bit in parts.path.split("/")
        if bit and bit != "/"
    ]
    path_part = "-".join(bit for bit in path_bits if bit) or "root"
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{host}-{path_part}-{timestamp}"


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
