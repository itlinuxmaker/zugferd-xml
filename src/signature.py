"""
signature
Version: 1.5.0
Author: Andreas Günther
License: GNU General Public License v3.0 or later

Generates a CA for signing the ZUGFeRD PDF file, given that 
signing the PDF and XML is not provided for in ZUGFeRD 2.5. Subsequently, 
the submitted ZUGFeRD PDF is generated as a signed PDF file.
"""

import logging
from pathlib import Path
from datetime import datetime, timedelta, timezone
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import BestAvailableEncryption
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.sign import signers
from getpass import getpass

def check_ca():
    """
    Checks if a CA key exists in the configuration directory and therefore no 
    ca.crt file exists yet. If not, both files are generated. 
    """
    
    ca_key_path = Path.home() / ".config/zugferd-xml/ca.key"

    if not ca_key_path.exists():
        print(f"ERROR: Der CA-Key fehlt: {ca_key_path}")
        return True

def main(zugferd_pdf, zugferd_pdf_sign):
    if check_ca():
        # Password entry and validation
        while True:
            try:
                password = getpass("Bitte ein Passwort (8 Zeichen, 2 Ziffern, 1 Sonderzeichen) für den CA-Schlüssel eingeben: ")

                if len(password) < 8:
                    raise ValueError("Das Passwort muss genau 8 Zeichen lang sein.")

                if sum(char.isdigit() for char in password) < 2:  
                    raise ValueError("Das Passwort muss mindestens 2 Ziffern enthalten.")
                
                if not any(not char.isalnum() for char in password):
                    raise ValueError("Das Passwort muss mindestens 1 Sonderzeichen enthalten.")

                password_confirm = getpass("Bitte Passwort zur Bestätigung erneut eingeben: ")

                if password != password_confirm:
                    raise ValueError("Die Passwörter stimmen nicht überein.")
                
                password = password.encode()
                logging.info("Anlage eines Passwortes für den CA-Key.")
                break

            except ValueError as error:
                print(f"Fehler: {error}")
                logging.error(f"Fehler: {error}")

        # Contents of the Certification Authority
        country_name = input("Landesschlüssel für 'COUNTRY NAME' der CA eingeben: ")
        organization_name = input("Den Namen der Organisation eingeben: ")
        common_name = input("Eingabe des Common Name: ")
        duration = float(input("Eingabe der Dauer des Zertifikates in Tagen: "))

        # Generation of the CA key
        ca_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=4096
        )

        # Generation of the certificate using the Certification Authority's data
        ca_name = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, f"{country_name}"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, f"{organization_name}"),
            x509.NameAttribute(NameOID.COMMON_NAME, f"{common_name}"),
        ])

        now = datetime.now(timezone.utc)

        ca_cert = (
            x509.CertificateBuilder()
            .subject_name(ca_name)
            .issuer_name(ca_name)
            .public_key(ca_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now)
            .not_valid_after(now + timedelta(days=duration))
            .add_extension(x509.BasicConstraints(ca=True, path_length=1), critical=True,)
            .sign(ca_key, hashes.SHA256())
        )

        ca_path = Path.home() / ".config/zugferd-xml/"
        with open(ca_path / "ca.key", "wb") as b:
            b.write(
                 ca_key.private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.TraditionalOpenSSL,
                    BestAvailableEncryption(password),
                 )
            )

        with open(ca_path  / "ca.crt", "wb") as c:
            c.write(ca_cert.public_bytes(serialization.Encoding.PEM))

    # Creation of the key file and the certificate
    password_sign = getpass("Eingabe des CA-Passwortes: ").encode()
    ca_key_path = Path.home() / ".config/zugferd-xml/ca.key"
    ca_cert_path = Path.home() / ".config/zugferd-xml/ca.crt"

    cms_signer = signers.SimpleSigner.load(
        key_file=str(ca_key_path),
        cert_file=str(ca_cert_path),
        key_passphrase=password_sign,
    )

    with open(zugferd_pdf, "rb") as pdf:
        writer = IncrementalPdfFileWriter(pdf)

        with open(zugferd_pdf_sign, "wb") as output:
            signers.sign_pdf(
                writer,
                signers.PdfSignatureMetadata(
                    field_name="Signature1"
                ),
                signer=cms_signer,
                output=output,
            )
            logging.info(f"Erstellen der signierten {zugferd_pdf_sign} aus {zugferd_pdf}.")

    if __name__ == "__main__":
        main(zugferd_pdf, zugferd_pdf_sign)