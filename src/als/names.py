"""Package-name normalization and the import-name -> distribution alias table."""

from __future__ import annotations

import re
import sys

ECOSYSTEMS = ("pypi", "npm")

_PEP503 = re.compile(r"[-_.]+")


def normalize(name: str, ecosystem: str = "pypi") -> str:
    """Canonical key for a package name.

    PyPI: PEP 503 - lowercase, runs of ``-``/``_``/``.`` collapse to ``-``.
    npm: names are case-sensitive historically but new names must be lowercase;
    we lowercase for keying and keep the scope (``@scope/name``).
    """
    name = name.strip()
    if ecosystem == "pypi":
        return _PEP503.sub("-", name).lower()
    if ecosystem == "npm":
        return name.lower()
    raise ValueError(f"unknown ecosystem {ecosystem!r}")


# Import name -> PyPI distribution, for the cases where they differ.
# Keys are top-level module names. An import NOT in this table and not in the
# stdlib is recorded with resolution="identity" (import name assumed to equal the
# distribution name) and is never counted as a hallucination on its own: if the
# assumed distribution is missing from PyPI we bucket it `unresolved`.
IMPORT_ALIASES: dict[str, str] = {
    "cv2": "opencv-python",
    "sklearn": "scikit-learn",
    "yaml": "PyYAML",
    "PIL": "Pillow",
    "bs4": "beautifulsoup4",
    "dateutil": "python-dateutil",
    "dotenv": "python-dotenv",
    "jwt": "PyJWT",
    "Crypto": "pycryptodome",
    "Cryptodome": "pycryptodomex",
    "OpenSSL": "pyOpenSSL",
    "serial": "pyserial",
    "usb": "pyusb",
    "magic": "python-magic",
    "docx": "python-docx",
    "pptx": "python-pptx",
    "fitz": "PyMuPDF",
    "skimage": "scikit-image",
    "google.protobuf": "protobuf",
    "attr": "attrs",
    "nacl": "PyNaCl",
    "gi": "PyGObject",
    "wx": "wxPython",
    "Levenshtein": "python-Levenshtein",
    "telegram": "python-telegram-bot",
    "discord": "discord.py",
    "socketio": "python-socketio",
    "engineio": "python-engineio",
    "multipart": "python-multipart",
    "jose": "python-jose",
    "slugify": "python-slugify",
    "pkg_resources": "setuptools",
    "setuptools": "setuptools",
    "zmq": "pyzmq",
    "smbus": "smbus2",
    "RPi": "RPi.GPIO",
    "mpl_toolkits": "matplotlib",
    "osgeo": "GDAL",
    "Bio": "biopython",
    "pydantic_core": "pydantic-core",
    "win32api": "pywin32",
    "win32con": "pywin32",
    "pythoncom": "pywin32",
    "ldap": "python-ldap",
    "snappy": "python-snappy",
    "lz4": "lz4",
    "speech_recognition": "SpeechRecognition",
    "sentencepiece": "sentencepiece",
    "faiss": "faiss-cpu",
    "dns": "dnspython",
    "Xlib": "python-xlib",
    "vlc": "python-vlc",
    "editor": "python-editor",
    "git": "GitPython",
    "github": "PyGithub",
    "gitlab": "python-gitlab",
    "jenkins": "python-jenkins",
    "kafka": "kafka-python",
    "nmap": "python-nmap",
    "can": "python-can",
    "mido": "mido",
    "pyaudio": "PyAudio",
    "sounddevice": "sounddevice",
    "simpleaudio": "simpleaudio",
    "pygame": "pygame",
    "tflite_runtime": "tflite-runtime",
    "MySQLdb": "mysqlclient",
    "psycopg2": "psycopg2-binary",
    "pymysql": "PyMySQL",
    "markdown": "Markdown",
    "jinja2": "Jinja2",
    "markupsafe": "MarkupSafe",
    "werkzeug": "Werkzeug",
    "flask": "Flask",
    "pyximport": "Cython",
    "Cython": "Cython",
    "grpc": "grpcio",
    "websocket": "websocket-client",
    "zstandard": "zstandard",
    "brotli": "Brotli",
    "ffmpeg": "ffmpeg-python",
    "moviepy": "moviepy",
    "pydub": "pydub",
    "mutagen": "mutagen",
    "tinytag": "tinytag",
    "pyperclip": "pyperclip",
    "scapy": "scapy",
    "paho": "paho-mqtt",
    "netifaces": "netifaces",
    "Adafruit_DHT": "Adafruit-DHT",
    "board": "adafruit-blinka",
    "busio": "adafruit-blinka",
    "digitalio": "adafruit-blinka",
    "machine": None,  # MicroPython builtin, not a PyPI dist
    "micropython": None,
    "utime": None,
    "network": None,
    "ujson": None,
}

# Node.js builtins never count as npm packages.
NODE_BUILTINS = frozenset(
    "assert async_hooks buffer child_process cluster console constants crypto dgram "
    "diagnostics_channel dns domain events fs http http2 https inspector module net os "
    "path perf_hooks process punycode querystring readline repl stream string_decoder "
    "sys timers tls trace_events tty url util v8 vm wasi worker_threads zlib test".split()
)

PY_STDLIB = frozenset(sys.stdlib_module_names) | {"__future__"}


def import_to_distribution(module: str) -> tuple[str | None, str]:
    """Map a Python import path to (distribution, resolution).

    resolution is one of:
      - "stdlib"   : part of the standard library (distribution None)
      - "builtin"  : platform builtin with no PyPI dist (MicroPython etc.)
      - "alias"    : mapped via IMPORT_ALIASES
      - "identity" : unmapped; distribution assumed equal to the import name
    """
    parts = module.split(".")
    top = parts[0]
    if top in PY_STDLIB:
        return None, "stdlib"
    # Longest dotted prefix wins: google.protobuf.message -> google.protobuf
    for i in range(len(parts), 0, -1):
        prefix = ".".join(parts[:i])
        if prefix in IMPORT_ALIASES:
            dist = IMPORT_ALIASES[prefix]
            return (dist, "alias") if dist else (None, "builtin")
    return top, "identity"


def npm_package_from_specifier(spec: str) -> str | None:
    """`lodash/fp` -> `lodash`; `@scope/pkg/sub` -> `@scope/pkg`; relative/builtin -> None."""
    spec = spec.strip()
    if not spec or spec.startswith((".", "/", "~")) or ":" in spec and spec.split(":")[0] in ("node", "http", "https", "file", "data"):
        return None
    parts = spec.split("/")
    if spec.startswith("@"):
        if len(parts) < 2 or not parts[1]:
            return None
        pkg = "/".join(parts[:2])
    else:
        pkg = parts[0]
    if pkg in NODE_BUILTINS:
        return None
    return pkg
