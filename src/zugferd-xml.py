import os
from decimal import Decimal, ROUND_HALF_UP
import subprocess
import shutil
import sys
import re
import yaml
import pikepdf
import logging
from xml.sax.saxutils import escape
from pathlib import Path
from datetime import datetime, timedelta
import signature
import pycheval
from pycheval import (
    EN16931Invoice,
    TradeParty,
    PostalAddress,
    Tax,
    Money,
    PaymentMeans,
    BankAccount,
    PaymentTerms,
    LineItem,
    generate_xml,
)
from pycheval.type_codes import (
    DocumentTypeCode,
    TaxCategoryCode,
)
from pycheval.quantities import QuantityCode
from pycheval.types import Quantity

"""
zugferd-xml
Version: 1.6.0
Author: Andreas Günther
License: GNU General Public License v3.0 or later

Creates ZUGFeRD 2.5 invoices from invoice data and a PDF/A-3b source,
supports multiple VAT rates, generates the ZUGFeRD XML, combines PDF
and XML with Mustang Project, and validates the resulting ZUGFeRD PDF
Starting with version 1.5.0, it is also possible to sign the PDF file.
"""

# Function to check for the existence of the Mustang Project on the system
def check_mustang():
    """
    Checks whether the `mustang` command exists on the system, and thus whether the Mustang project is present.
    """
    mustang = shutil.which("mustang")
    if mustang is None:
        raise RuntimeError(
            "Mustang ist nicht installiert. "
            "Bitte gemäss README systemweit installieren."
        )  

# Check whether the config file is available in the .config folder.
def check_config():
    """
    Checks whether the YAML file containing the configuration values ​​already exists.
    """
    global configfile
    configfile = Path.home() / ".config/zugferd-xml/invoicedata.yaml"

    if not configfile.exists():
        print(f"ERROR: Die Konfigurationsdatei fehlt: {configfile}")
        print(f"Führen Sie zuerst das install-config.sh gemäss der READme aus!")
        sys.exit(1)


# Function to load the YAML configuration
def load_invoice_data(filename):
    """
    Loads and parses the given YAML configuration file into a Python dictionary.

    Args: The path to the YAML configuration file.

    Returns:
        dict: A dictionary representing the contents of the YAML file.
    """
    with open(filename, "r", encoding="utf-8") as file:
        return yaml.safe_load(file)

# Function tests the PDF file for the required version.
def check_pdf(path):
    """
    Check the provided PDF file to ensure it meets the version requirement for Mustang. In this case, that is version PDF/A-3B.
    """
    with pikepdf.open(path) as pdf:
        metadata = pdf.open_metadata()

        if (
            str(pdf.pdf_version) != "1.7"
            or str(metadata.get("pdfaid:part")) != "3"
            or str(metadata.get("pdfaid:conformance", "")).upper() != "B"
        ):
            print("Bitte PDF als PDF/A-3b (1.7) exportieren!")
            logging.error("Benutzte PDF-Version ist keine gültige ZUGFeRD PDF-Version!")
            sys.exit(1)
    logging.info("PDF liegt in der für ZUGFeRD erforderlichen Version PDF/A-3b (1.7) vor.")

# Function for entering invoice details or confirming default values
def read_inputs():
    """
    Here, the data is read in for confirmation or modification. Additional data is requested and
    stored globally so that it is available in the global namespace.
    """
    invoice_data = load_invoice_data(configfile)
    global descriptions
    descriptions = invoice_data["descriptions"]
    
    exclude_inputs = [
        "xml_file",
        "formats",
        "version",
        "attachments",
        "product_name",
        "invoice_date",
        "unit_price",
        "quantity",
        "unit_code",
        "RateApplicablePercent",
        "creditor_reference_id",
        "InvoiceCurrencyCode",
        "information1",
        "information2",
        "Rabatt",
        "Payment_Terms",
        "currencyID",
        "creditor_reference_id",
        "mandateID",
        "schemeID",
        "type_code1",
        "type_code2",
        "type_code3",
        "category_code",
        "seller_name",
        "seller_postcode",
        "seller_street",
        "seller_city",
        "seller_country",
        "schemeID",
        "seller_vat_id",
        "seller_tax_number",
        "StartDateTime",
        "EndDateTime",
        "deliveryDate",
        "iban_id",
        "bic_id"
    ]
    # Standard parameters are adopted or offered, while excluded parameters are not queried.
    for block in invoice_data["invoice"]:
        for level2, fields in block.items():
            for key, value in fields.items():
                globals()[key] = "" if value is None else value 

                if key in exclude_inputs:
                    continue

                value = globals()[key]

                new_value = input(
                    f'Geben Sie den Wert für "{descriptions[key]}" ein '
                    f'oder bestätigen Sie diesen Wert [{value}]: '
                )

                if new_value:
                    globals()[key] = new_value
    # Provision of file names for files to be created and accessed.
    global invoice_number
    invoice_number = f"{invoice_number_pre}_{buyer_id}_{invoice_number}"
    global pdf_file
    pdf_file = f"{invoice_number}.pdf"
    global zugferd_pdf
    zugferd_pdf = f"{invoice_number}-ZUGFeRD.pdf"
    global zugferd_pdf_sign
    zugferd_pdf_sign = f"{invoice_number}-ZUGFeRD_signed.pdf"
    global xml_file
    xml_file = f"{invoice_number}-ZUGFeRD.xml"
    path_pdf = f"{pdf_path}{pdf_file}"
    logging.info(f"Bereitsstellung der Dateinamen {invoice_number}, {pdf_file}, {zugferd_pdf}, {xml_file}, {path_pdf}")

    # Verification of the correct PDF version for invoice PDFs.
    check_pdf(path_pdf)

    # Entry of the invoice date
    while True:
        try:
            global invoice_date
            description = invoice_data["descriptions"]["invoice_date"]
            value = input(f"Geben Sie den Wert für {description} in dem Format dd.mm.YYYY ein: ")

            if not re.fullmatch(r'\d{2}\.\d{2}\.\d{4}', value):
                raise ValueError("Format")

            invoice_date = datetime.strptime(value, '%d.%m.%Y').date()
            break
        except ValueError:
            print("Das Datum muss im Format dd.mm.YYYY eingegeben werden.")

    # Entry of payment terms and validation.
    while True:
        try:
            global paymentterms
            description = invoice_data["descriptions"]["Payment_Terms"]
            value = invoice_data["invoice"][9]["SpecifiedTradePaymentTerms"]["Payment_Terms"]
            paymentterms = input(f"Geben Sie den Wert für {description} ein oder bestätigen Sie [{value}]: ")
            selected = re.findall(r"'([^']+)'", description)
            if paymentterms == "":
                paymentterms = "sofort"
                break
            elif paymentterms not in selected:
                print(f"Nur diese Auswahl ist möglich {selected}! ")
            else:
                break                

        except ValueError:
            print(f"Ungültige Eingabe!")   

    # Entry of either a delivery date or a delivery period
    global StartDateTime
    global EndDateTime
    global deliveryDate
    deliveryDate = input('Für einen Leistungszeitraum, lassen Sie diesen Wert leer, ansonsten erfolgt hier die Eingabe des Leistungsdatum (dd.mm.YYYY): ')
    if deliveryDate:
        deliveryDate = datetime.strptime(deliveryDate, '%d.%m.%Y').strftime('%Y%m%d')
    else:
        deliveryDate = None

    if not deliveryDate:
        StartDateTime = datetime.strptime(input('Startzeitpunkt des Leistungszeitraum (dd.mm.YYYY): '), '%d.%m.%Y').strftime('%Y%m%d')
        EndDateTime = datetime.strptime(input('Zeitpunkt des Endes im Leistungszeitraum (dd.mm.YYYY): '), '%d.%m.%Y').strftime('%Y%m%d')

    # Choice between SEPA Direct Debit and SEPA Credit Transfer
    while True:
        try:
            global type_code2
            type_code2 = int(input('Für SEPA-Lastschrift bitte 59 oder für SEPA-Überweisung 58 eingeben: '))
            if type_code2 in (58, 59):
                break
            print("Bitte entweder 58 oder 59 eingeben! ")
        except ValueError:
            print("Bitte entweder 58 oder 59 eingeben! ")
    
    # Choice between granting a discount and no discount
    while True:
        try:
            global CalculationPercent
            CalculationPercent_input = input('Falls Rabatt gewährt wird, bitte den Rabatt in Prozent eingeben, ansonsten [Enter] eingeben: ').replace(",",".")
            if CalculationPercent_input == "":
                CalculationPercent = Decimal("0.00")
            else:
                CalculationPercent = Decimal(CalculationPercent_input)

            if 0 <= CalculationPercent <= 20:
                global reason
                reason = "Rabatt"
                logging.info(f"CalculationPercent enthält den Wert: {CalculationPercent}")
                break

            raise ValueError
        except ValueError:
                print("Bitte einen Rabatt zwischen 0 und 10 eingeben! ")

    # Choice between prepayment and no prepayment
    while True:
        try:
            global paid_amount
            paid_input = input('Falls bereits eine Anzahlung geleistet wurde, bitte den Abschlagsbetrag eingeben, ansonsten [Enter]: ').replace(",",".")
            if paid_input == "":
                paid_amount = Decimal(0.00)
            else:
                paid_amount = Decimal(paid_input)
            logging.info(f"paid_amount enthält den Wert: {paid_amount}")
            break
        except ValueError:
            print("Bitte einen gültigen Abschlag oder 0 eingeben! ")                

    # Recording the number of invoice line items
    while True:
        """
        Entry of the number of invoice items
        """
        try:
            global positions
            positions = int(input('Wieviele Transaktionen/Positionen wollen Sie in dieser Rechnung abbilden? '))
            if positions > 0:
                break
                raise ValueError
        except ValueError:
            print("Bitte eine ganze Zahl eingeben! ")

    # Initialization of a dictionary to manage one or more VAT rates.
    global vat_breakdowns
    vat_breakdowns = {}

    # Recording of individual invoice items with different VAT rates
    for position in range(1, positions + 1):
        globals()[f"line{position}"] = position
        globals()[f"product_name{position}"] = input("Eingabe von Serviceleistung oder Produkt: ")
        while True:
            try:
                globals()[f"quantityUnit{position}"] = input("Eingabe dieser Position als Stundenanzahl(s) oder als Mengenzahl(m): ")
                if globals()[f"quantityUnit{position}"] in ("s", "m"):
                    break
                raise ValueError
            except ValueError:
                print("Bitte ausschließlich 's' oder 'm' eingeben!" )
        if globals()[f"quantityUnit{position}"] == 's':
            while True:
                try:
                    globals()[f"quantity{position}"] = Decimal(input("Eingabe der Anzahl der Stunden: ").replace(",", "."))
                    break
                except ValueError:
                    print("Bitte eine gültige Stundenanzahl - auch dezimal - eingeben! ")
            globals()[f"unitCode{position}"] = "HUR"
                    
        elif globals()[f"quantityUnit{position}"] == 'm':
            while True:
                try:
                    globals()[f"quantity{position}"] = Decimal(input("Eingabe der Menge: ").replace(",", "."))
                    break
                except ValueError:
                    print("Bitte eine gültige Mengenanzahl - auch dezimal - eingeben! ")
            globals()[f"unitCode{position}"] = "C62"

        while True:
            try:
                globals()[f"unit_price{position}"] = Decimal(input("Eingabe des Nettopreises: ").replace(",", "."))
                break
            except ValueError:
                print("Bitte einen gültigen Nettopreis eingeben! ")
        
        while True:
            try:
                globals()[f"RateApplicablePercent{position}"] = input(
                    f'Geben Sie den Wert für "{descriptions["RateApplicablePercent"]}" ein '
                    f'oder bestätigen Sie diesen Wert [{RateApplicablePercent}]: ')   
                if not globals()[f"RateApplicablePercent{position}"]:   
                    globals()[f"RateApplicablePercent{position}"] = Decimal(RateApplicablePercent) 
                    break
                elif re.fullmatch(r"\d+[.,]\d{2}", globals()[f"RateApplicablePercent{position}"]): 
                    globals()[f"RateApplicablePercent{position}"] = Decimal(globals()[f"RateApplicablePercent{position}"].replace(",", "."))
                    break
                raise ValueError
            except ValueError:
                print("Die Umsatzsteuer bitte im Format 0.00 oder 0,00 eingeben! ")
        
        # Breakdown of VAT by tax rate; each tax rate is created as a key with net and gross amounts of 0.00 each.
        if globals()[f"RateApplicablePercent{position}"] not in vat_breakdowns:
            vat_breakdowns[globals()[f"RateApplicablePercent{position}"]] = {
                "BasisAmount": Decimal("0.00"),
                "CalculatedAmount": Decimal("0.00")
            }

    # Calculation of the totals of all net amounts and all tax amounts, broken down by VAT rate.
    for position in range(1, positions + 1):
        vat_breakdowns[globals()[f"RateApplicablePercent{position}"]]["BasisAmount"] += (
                globals()[f"quantity{position}"] * globals()[f"unit_price{position}"]
            )
        logging.info(f"Erhöhung des BasisAmount innerhalb create_read_inputs().")
        
        vat_breakdowns[globals()[f"RateApplicablePercent{position}"]]["CalculatedAmount"] += (
                globals()[f"quantity{position}"] * globals()[f"unit_price{position}"]
                * globals()[f"RateApplicablePercent{position}"] / Decimal("100")
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        logging.info(f"Erhöhung des CalculatedAmount innerhalb create_read_inputs().")    
    
    # Entry of Mustangproject parameters and additional file attachments.
    print()
    print("#### Geben Sie hier noch Parameter, Attachments für die PDF-Erzeugung ein")
    print()
    global xmlformat
    x_format = input(f"Geben Sie das Format ein " 
                    f"({descriptions['formats']}) "
                    f"[Standard: {formats}]: ")
    xmlformat = x_format or formats     

    global xmlversion
    x_version = input(f"Geben Sie die ZUGFeRD-Version ein "
                      f"({descriptions['version']}) "
                      f"[Standard: {version}]: ")
    xmlversion = x_version or version

    global xmlattachment
    x_attachment = input(f"Geben Sie eine zusätzliche Datei im selben Verzeichnis an "
                         f"({descriptions['attachments']}), bei keinem Anhang [Enter]: ")
    xmlattachment = x_attachment or None
    if xmlattachment is not None:
        xmlattachment = f"{pdf_path}{xmlattachment}"

def setup_logging(file):
    with open(file, "r", encoding="utf-8") as config_file:
        config = yaml.safe_load(config_file)

    log_dir = Path.home() / f".{config['logging']['logpath']}"
    log_dir.mkdir(parents=True, exist_ok=True)

    logfile = log_dir / config["logging"]["logfile"]

    logging.basicConfig(
        filename=logfile.parent / (datetime.now().strftime("%d_%m_%Y") + "-" + logfile.name),
        filemode="a",
        level=logging.INFO,
        style="{",
        format="{asctime} [{levelname:8}] [{funcName}] {message}",
        datefmt="%d.%m.%Y %H:%M:%S"
    )

# Generating the XML file using the pycheval library
def create_zugferd_xml(
    line_total_amount,
    discount_actual_amount,
    tax_basis_amount,
    tax_total_amount,
    grand_total_amount,
    due_payable_amount):

    taxes = []

    for rate, data in vat_breakdowns.items():
        taxes.append(
            Tax(
                calculated_amount=Money(
                    str(data["CalculatedAmount"]),
                    InvoiceCurrencyCode
                ),
                basis_amount=Money(
                    str(data["BasisAmount"]),
                    InvoiceCurrencyCode
                ),
                rate_percent=Decimal(str(rate)),
                category_code=TaxCategoryCode.STANDARD_RATE
            )
        )

    invoice = EN16931Invoice(
        invoice_number = invoice_number,
        type_code = DocumentTypeCode.INVOICE,
        invoice_date = invoice_date,

        seller = TradeParty(
            name = seller_name,
            address =  PostalAddress(
                country_code = seller_country,
                post_code = seller_postcode,
                city = seller_city,
                line_one = seller_street,
            ),
            tax_number = seller_tax_number,
            vat_id = seller_vat_id,
        ),

        buyer= TradeParty(
            name = buyer_name,
            address =  PostalAddress(
                country_code = buyer_country,
                post_code = buyer_postcode,
                city = buyer_city,
                line_one = buyer_street,
            ),
        ),

        currency_code = currencyID,
        tax = taxes,

        line_total_amount = Money(str(line_total_amount), InvoiceCurrencyCode),
        tax_basis_total_amount = Money(str(tax_basis_amount), InvoiceCurrencyCode),
        tax_total_amounts = [
            Money(str(vat_breakdowns[rate]["CalculatedAmount"]), InvoiceCurrencyCode)
            for rate in vat_breakdowns
        ],
        grand_total_amount = Money(str(grand_total_amount), InvoiceCurrencyCode),
        due_payable_amount = Money(str(due_payable_amount), InvoiceCurrencyCode),
        allowance_total_amount = Money(str(discount_actual_amount), InvoiceCurrencyCode),
        prepaid_amount = Money(str(paid_amount), InvoiceCurrencyCode),

        delivery_date = (
            deliveryDate
            if deliveryDate
            else None
        ),

        billing_period = (
            (StartDateTime, EndDateTime)
            if not StartDateTime 
            and EndDateTime
            else None
        ),

        seller_sepa_creditor_id = (
            creditor_reference_id
            if type_code2 == 59                
            else None    
        ),

        payment_reference = invoice_number,

        payment_means = (
            [
                PaymentMeans(
                    type_code = type_code2,
                    payee_account = BankAccount(
                        iban = iban_id,
                        name = seller_name,
                        bank_id = iban_id,
                    ),
                    payee_bic = bic_id,
                    information = mandateID,
                )
            ]
            if type_code2 == 59
            else []
        ),

        payment_terms = PaymentTerms(
            description = f"Zahlungsziel: {escape(str(paymentterms))}",
            due_date = (
                invoice_date + timedelta(days=2)
                if paymentterms == "sofort"
                else invoice_date + timedelta(days=int(paymentterms))
                if paymentterms in re.findall(
                    r"'(\d+)'", 
                    descriptions["Payment_Terms"]
                )
                else None
            ), 
            direct_debit_mandate_id = mandateID,
        ),

        line_items = [
            LineItem(
                id = str(globals()[f"line{position}"]),
                name = globals()[f"product_name{position}"],
                net_price = Money(
                    str(globals()[f"unit_price{position}"]),
                    InvoiceCurrencyCode,
                ),
                billed_quantity = (
                    Decimal(str(globals()[f"quantity{position}"])),
                    QuantityCode.HOUR
                    if globals()[f"unitCode{position}"] == "HUR"
                    else QuantityCode.ONE
                ),
                billed_total = Money(
                    str(
                        (globals()[f"unit_price{position}"] * globals()[f"quantity{position}"]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP,)
                    ),
                    InvoiceCurrencyCode,
                ),
                tax_rate = globals()[f"RateApplicablePercent{position}"],
                tax_category = TaxCategoryCode.STANDARD_RATE,
            )
            for position in range(1, positions + 1)
        ],
    )

    # Generate and save ZUGFeRD XML
    xml_string = generate_xml(invoice)

    with open(f"{xml_path}{xml_file}", "w", encoding="utf-8") as file:
        file.write(xml_string)

    logging.info(
        f"ZUGFeRD XML erfolgreich erstellt: {xml_path}{xml_file}"
    )

# Rounding function for monetary amounts to two decimal places.
def rounded(value):
    return Decimal(value).quantize(Decimal("0.00"), rounding=ROUND_HALF_UP)

# Calculation of the total of all invoice line item amounts, taking into account multiple VAT rates.
def create_line_total_amount(vat_breakdowns):
    global line_total_amount
    line_total_amount = Decimal("0.00")
    for position in range(1, positions +1):
        line_total_amount += Decimal(LineAmount[position])

    return line_total_amount

# Generation of the invoice line items for the ZUGFeRD XML
def create_trade_line_item():
    global LineAmount
    LineAmount = {}
    for position in range(1, positions + 1):
        unit_price = Decimal(str(globals()[f"unit_price{position}"]))
        quantity = Decimal(str(globals()[f"quantity{position}"]))
        LineAmount[position] = str((unit_price * quantity).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))    

# Calculation of discounts with different VAT rates
def create_discount(vat_breakdowns, vat_rate):
    global discount_actual_amount
    discount_basis_amount = vat_breakdowns[vat_rate]["BasisAmount"]
    discount_actual_amount = 0
    discount_actual_amount = (discount_basis_amount * CalculationPercent / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return discount_actual_amount

# Calculation of total invoice amounts taking into account multiple VAT rates, including discount, tax, and payment amount.
def calculate_amounts():
    global line_total_amount
    global discount_actual_amount
    global tax_basis_amount
    global tax_total_amount

    line_total_amount = rounded(create_line_total_amount(vat_breakdowns))
    logging.info(f"Gesamt-Nettobetrag (line_total_amount): {line_total_amount:.2f}")
    discount_actual_amount = rounded(sum(vat_breakdowns[rate]["BasisAmount"] * CalculationPercent / Decimal("100") for rate in vat_breakdowns))
    logging.info(f"Gesamter Rabatt/Nachlass (discount_actual_amount): {discount_actual_amount:.2f}")

    tax_basis_amount = rounded(line_total_amount - discount_actual_amount)
    logging.info(f"Steuerbasis, steuerpflichtiger Nettobetrag (tax_basis_amount): {tax_basis_amount:.2f}")
    calculated_amount = rounded(sum(rounded((vat_breakdowns[rate]["BasisAmount"] - vat_breakdowns[rate]["BasisAmount"] * CalculationPercent / Decimal("100")) * rate / Decimal("100")) for rate in vat_breakdowns))
    logging.info(f"Gesamtbetrag der Umsatzsteuer (calculated_amount): {calculated_amount:.2f}")
    tax_total_amount = calculated_amount
    logging.info(f"Summe aller Umsatzsteuerbeträge (tax_total_amount): {tax_total_amount:.2f}")
    grand_total_amount = rounded(tax_basis_amount + calculated_amount)  
    logging.info(f"Bruttogesamtbetrag (grand_total_amount): {grand_total_amount:.2f}")
    due_payable_amount = rounded(grand_total_amount - paid_amount)
    logging.info(f"Bereits geleistete Vorauszahlungen (paid_amount): {paid_amount:.2f}")
    logging.info(f"Zahlbarer Restbetrag (due_payable_amount): {due_payable_amount:.2f}")

    return {
        "line_total_amount": line_total_amount,
        "discount_actual_amount": discount_actual_amount,
        "tax_basis_amount": tax_basis_amount,
        "calculated_amount": calculated_amount,
        "tax_total_amount": tax_total_amount,
        "grand_total_amount": grand_total_amount,
        "due_payable_amount": due_payable_amount,
    }

# Generation of the ZUGFeRD PDF file with the corresponding parameters.
def create_pdfdocument():
    print()
    print("**** Erzeugen des ZUGFeRD PDF-Dokumente ****")
    print()
    if xmlattachment is not None:
        attachment_attr = ["--attachments", xmlattachment]
        logging.info(f"Zusätzlicher Anhang in PDF-Datei: {xmlattachment}")
    else:
        attachment_attr = ["--no-additional-attachments"]
        logging.info(f"mustang-Befehl enthält Option: {attachment_attr}")

    try:
        if os.path.exists(f"{pdf_path}{zugferd_pdf}"):
            os.remove(f"{pdf_path}{zugferd_pdf}")
            logging.info(f"Existierende Datei {pdf_path}{zugferd_pdf} wurde gelöscht.")
        subprocess.run([
            "mustang",
            "--action", "combine",
            "--format", xmlformat,
            "--version", xmlversion,
            "--profile", "T",
            *attachment_attr,
            "--source", f"{pdf_path}{pdf_file}",
            "--source-xml", f"{xml_path}{xml_file}",
            "--out", f"{pdf_path}{zugferd_pdf}",
        ], check=True)
        logging.info(f"Die PDF-ZUFeRD-Datei {pdf_path}{zugferd_pdf} wurde erstellt!")
    except subprocess.CalledProcessError as error:
        logging.error(f"Die Erstellung der PDF-ZUFeRD-Datei {pdf_path}{zugferd_pdf} ist fehlgeschlagen!")
        raise

# Validation of the generated PDF file
def validate_zugferd_pdf():
    print()
    print("**** Validierung der ZUGFeRD-PDF ****")
    print()

    try:
        subprocess.run([
            "mustang",
            "--action", "validate",
            "--source", f"{pdf_path}{zugferd_pdf_sign}",
        ], check=True)

        logging.info(
            f"ZUGFeRD-Validierung erfolgreich: "
            f"{pdf_path}{zugferd_pdf_sign}"
        )

    except subprocess.CalledProcessError:
        logging.exception(
            f"ZUGFeRD-Validierung fehlgeschlagen: "
            f"{pdf_path}{zugferd_pdf_sign}"
        )
        raise


def main():

    check_config()
    check_mustang()
    setup_logging(configfile)

    logging.info("===========================================================")
    logging.info(f"Start der ZUGFeRD-PDF-Generierung um {datetime.now():%H:%M:%S} Uhr")

    invoice_data = load_invoice_data(configfile)

    for block in invoice_data["invoice"]:
        for level2, fields in block.items():
            for key, value in fields.items():
                globals()[key] = "" if value is None else value            

    read_inputs()
    create_trade_line_item()
    amounts = calculate_amounts()

    # Construction of the ZUGFeRD XML with Pycheval
    create_zugferd_xml(
        line_total_amount=amounts["line_total_amount"],
        discount_actual_amount=amounts["discount_actual_amount"],
        tax_basis_amount=amounts["tax_basis_amount"],
        tax_total_amount=amounts["tax_total_amount"],
        grand_total_amount=amounts["grand_total_amount"],
        due_payable_amount=amounts["due_payable_amount"]
    )
    create_pdfdocument()

    """
    Creation of an X.509 certificate and signing of the PDF file
    """
    while True:
        # Checking user input for yes/no
        try:
            sign_ask = input(F"Soll die eben erstellte Datei {zugferd_pdf} zusätzlich mit einer Signatur abgesichert werden? [ja/nein]: ").strip().lower()
            if sign_ask not in ("ja", "j", "nein", "n"):
                raise ValueError
            break    

        except ValueError:
            print("Bitte mit 'ja' oder 'nein' antworten! ")

    if sign_ask in ("ja", "j"):
        logging.info(f"Start der Signierung von {zugferd_pdf}.")
        signature.main(
            f"{pdf_path}{zugferd_pdf}",
            f"{pdf_path}{zugferd_pdf_sign}"
        )
    elif sign_ask in ("nein", "n"):
        logging.info(f"Keine Signierung von {zugferd_pdf}.")

    validate_zugferd_pdf()
if __name__ == "__main__":
    main()
