from __future__ import annotations

import json
import re
import unicodedata
import zipfile
from pathlib import PurePosixPath
from typing import BinaryIO

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

MIMES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "pdf": "application/pdf",
    "zip": "application/zip",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "dwg": "image/vnd.dwg",
    "psd": "image/vnd.adobe.photoshop",
    "txt": "text/plain",
    "csv": "text/csv",
    "json": "application/json",
    "xml": "application/xml",
}


def filename(value: str) -> str:
    value = unicodedata.normalize("NFC", value)
    if (
        not value
        or len(value.encode("utf-8")) > 255
        or value.strip() != value
        or any(unicodedata.category(c).startswith("C") for c in value)
        or any(c in value for c in "/\\:")
        or value.startswith(".")
        or value.endswith(".")
    ):
        raise ValueError("Invalid filename")
    if value.rsplit(".", 1)[-1].lower() not in MIMES or "." not in value:
        raise ValueError("Unsupported file format")
    return value


def validate(source: BinaryIO, name: str, max_bytes: int) -> str:
    """Server-side content detection; declared browser MIME is never trusted."""
    extension = filename(name).rsplit(".", 1)[-1].lower()
    source.seek(0, 2)
    size = source.tell()
    if not 0 < size <= max_bytes:
        raise ValueError("Invalid file size")
    source.seek(0)
    head = source.read(1024)
    source.seek(0)
    if extension in {"zip", "docx", "xlsx", "pptx"}:
        try:
            with zipfile.ZipFile(source) as archive:
                entries = archive.infolist()
                if len(entries) > 10000 or not entries:
                    raise ValueError("Archive entry limit")
                expanded = 0
                names: set[str] = set()
                for entry in entries:
                    path = PurePosixPath(entry.filename)
                    if (
                        path.is_absolute()
                        or ".." in path.parts
                        or "\\" in entry.filename
                        or ":" in entry.filename
                        or entry.filename in names
                        or entry.flag_bits & 1
                        or (entry.external_attr >> 16) & 0o170000 == 0o120000
                    ):
                        raise ValueError("Unsafe archive entry")
                    names.add(entry.filename)
                    expanded += entry.file_size
                    if expanded > max_bytes or entry.file_size > max(1, entry.compress_size) * 100:
                        raise ValueError("Archive expansion limit")
                    # Nested archives are disallowed to bound recursive decompression.
                    with archive.open(entry) as member:
                        first = member.read(8)
                        if first.startswith((b"PK\x03\x04", b"7z\xbc\xaf", b"Rar!", b"\x1f\x8b")):
                            raise ValueError("Nested archives are not supported")
                        consumed = len(first)
                        while chunk := member.read(1024 * 1024):
                            consumed += len(chunk)
                            if consumed > entry.file_size or consumed > max_bytes:
                                raise ValueError("Archive expansion limit")
                required = {
                    "docx": "word/document.xml",
                    "xlsx": "xl/workbook.xml",
                    "pptx": "ppt/presentation.xml",
                }
                if extension != "zip" and (
                    "[Content_Types].xml" not in names
                    or required[extension] not in names
                    or any(n.lower().endswith("vbaproject.bin") for n in names)
                ):
                    raise ValueError("Invalid office document")
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
            raise ValueError("Invalid archive") from exc
    elif extension in {"txt", "csv", "json", "xml"}:
        # Structured text parsing is bounded independently of the binary upload limit.
        if size > 32 * 1024 * 1024:
            raise ValueError("Text file exceeds parsing limit")
        try:
            text = source.read().decode("utf-8-sig")
            if "\x00" in text or any(ord(c) < 32 and c not in "\r\n\t" for c in text):
                raise ValueError("Invalid text content")
            if extension == "json":
                json.loads(text)
            if extension == "xml":
                if re.search(r"<!\s*(DOCTYPE|ENTITY)", text, re.IGNORECASE):
                    raise ValueError("XML entities are forbidden")
                ElementTree.fromstring(
                    text, forbid_dtd=True, forbid_entities=True, forbid_external=True
                )
        except (UnicodeError, ElementTree.ParseError, DefusedXmlException, RecursionError) as exc:
            raise ValueError("Invalid text document") from exc
    else:
        valid = {
            "pdf": head.startswith(b"%PDF-"),
            "png": head.startswith(b"\x89PNG\r\n\x1a\n"),
            "jpg": head.startswith(b"\xff\xd8\xff"),
            "jpeg": head.startswith(b"\xff\xd8\xff"),
            "dwg": re.match(rb"AC10[0-9]{2}", head) is not None,
            "psd": head.startswith(b"8BPS\x00\x01"),
        }
        if not valid.get(extension, False):
            raise ValueError("File content does not match format")
    source.seek(0)
    return MIMES[extension]
