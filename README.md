# ZUGFeRD XML and Invoice Generator
Creates ZUGFeRD 2.5 invoices from invoice data and a PDF/A-3b source, supports multiple VAT rates, generates the ZUGFeRD XML, combines PDF and XML with Mustang Project, and validates the resulting ZUGFeRD PDF. Additionally, starting with release 1.5.0, it is possible to sign the ZUGFeRD PDF using a custom Certificate Authority to protect it against subsequent alteration.

## Features
* Input of invoice data via YAML file and CLI
* Generation of ZUGFeRD invoices
* Support for multiple VAT rates
* Discount calculation
* Adding attachments
* PDF/A-3b verification
* Validation with Mustangproject
* Daily logging of key inputs, ensuring that calculated values ​​can also be found in the log.
* Signing the ZUGFeRD PDF using a proprietary Certification Authority.

## Installation
* Python 3.13+
* PyYAML, pikepdf, cryptography and pyHanko must be installed via pip
* Mustangproject 2.5

### Make the YAML file available in the user directory.
This installation script must be run as a normal user.
```
cd zugferd-xml/scripts/
chmod a+x install-config.sh
./install-config.sh
```
This makes the YAML file available for editing under ~/.config/zugferd-xml/.

### Mustang Project
The installation script builds Mustang Project and installs the `mustang` command system-wide as root:
```
cd zugferd-xml/scripts/
chmod a+x install-mustang.sh
su -c "./install-mustang.sh"
```

## Configuration
The file `src/invoicedata.yaml` primarily contains default values ​​for the ZUGFeRD format and fixed user data intended for general use. Otherwise, many inputs are provided interactively via the CLI. To place the file in the correct location within the user's home directory, follow the instructions in the "Installation" section.

## Usage
```
cd src
python3 zugferd-xml.py
```

## Output
Three files are created in the specified directory alongside the existing PDF/A-3b file:  
RE_CustomerNo_InvoiceNo-ZUGFeRD.pdf  
RE_CustomerNo_InvoiceNo-ZUGFeRD_signed.pdf (If signing is selected)
RE_CustomerNo_InvoiceNo-ZUGFeRD.xml
The PDF file contains both the XML file and additional files inserted as attachments (e.g., proof of service).
When creating a certification authority with a key, ca.crt and ca.key are saved in ~/.config/zugferd-xml/.

## ZUGFeRD
ZUGFeRD is a hybrid electronic invoice format that combines a human-readable PDF document with structured invoice data in XML format.
This project generates ZUGFeRD 2.5 invoices based on the European standard EN 16931 and uses the Cross Industry Invoice (CII) XML format.
The generated XML is embedded into a PDF/A-3b document, resulting in a ZUGFeRD invoice that can be read both by humans and by accounting software.
The project supports the ZUGFeRD 2.5 Extended profile.

## Tests
```   
pytest  
```

## Licence
GNU General Public License v3.0 or later.