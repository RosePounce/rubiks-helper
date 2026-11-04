"""Accès depuis le réseau local (téléphone, tablette).

Les navigateurs n'autorisent la caméra que sur une page sécurisée : en
dehors de `localhost`, il faut donc du HTTPS. Ce module crée un certificat
auto-signé (valable pour les adresses locales de la machine) et liste les
adresses à saisir sur le téléphone. Fonctionne à l'identique sous Windows et
sous Linux : aucun outil externe, seulement le paquet `cryptography`.
"""

from __future__ import annotations

import datetime as dt
import ipaddress
import socket
from pathlib import Path

from .solver import CACHE_DIR

TLS_DIR = CACHE_DIR / "tls"


def local_addresses() -> list[str]:
    """Adresses IPv4 de la machine sur le réseau local (hors boucle locale)."""
    found: list[str] = []
    # interface utilisée pour sortir vers l'extérieur (aucun paquet n'est envoyé)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))
            found.append(s.getsockname()[0])
    except OSError:
        pass
    # Windows (et macOS) : le nom de la machine résout vers toutes ses adresses
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.append(info[4][0])
    except OSError:
        pass
    # Linux : le nom résout souvent vers 127.0.1.1 ; on interroge chaque interface
    found += _linux_interface_addresses()
    out = []
    for a in found:
        if not a.startswith("127.") and a not in out:
            out.append(a)
    return out


def _linux_interface_addresses() -> list[str]:
    try:
        import fcntl
        import struct
    except ImportError:          # Windows
        return []
    out = []
    SIOCGIFADDR = 0x8915
    try:
        names = [n for _, n in socket.if_nameindex()]
    except OSError:
        return []
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        for n in names:
            try:
                raw = fcntl.ioctl(s.fileno(), SIOCGIFADDR, struct.pack("256s", n[:15].encode()))
                out.append(socket.inet_ntoa(raw[20:24]))
            except OSError:      # interface sans adresse IPv4
                continue
    return out


def ensure_certificate(addresses: list[str]) -> tuple[Path, Path]:
    """Certificat auto-signé couvrant `addresses` ; recréé si une adresse manque."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    cert_path, key_path = TLS_DIR / "cert.pem", TLS_DIR / "key.pem"
    wanted = {ipaddress.ip_address(a) for a in [*addresses, "127.0.0.1"]}
    if cert_path.exists() and key_path.exists():
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
        try:
            san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
            have = set(san.get_values_for_type(x509.IPAddress))
        except x509.ExtensionNotFound:
            have = set()
        if wanted <= have and cert.not_valid_after_utc > dt.datetime.now(dt.UTC) + dt.timedelta(days=7):
            return cert_path, key_path

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Rubik Helper (réseau local)")])
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=825))
        .add_extension(x509.SubjectAlternativeName(
            [x509.DNSName("localhost"), *(x509.IPAddress(ip) for ip in sorted(wanted))]), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    TLS_DIR.mkdir(parents=True, exist_ok=True)
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                           serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return cert_path, key_path
