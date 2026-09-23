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

"""
zugferd-xml
Version: 1.3.5
Author: Andreas Günther
License: GNU General Public License v3.0 or later

Creates ZUGFeRD 2.5 invoices from invoice data and a PDF/A-3b source,
supports multiple VAT rates, generates the ZUGFeRD XML, combines PDF
and XML with Mustang Project, and validates the resulting ZUGFeRD PDF.
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
    invoice_data = load_invoice_data("invoicedata.yaml")
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
        "PaymentTerms",
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
    global pdf_file
    pdf_file = f"{invoice_number_pre}_{buyer_id}_{invoice_number}.pdf"
    global zugferd_pdf
    zugferd_pdf = f"{invoice_number_pre}_{buyer_id}_{invoice_number}-ZUGFeRD.pdf"
    global xml_file
    xml_file = f"{invoice_number_pre}_{buyer_id}_{invoice_number}-ZUGFeRD.xml"
    path_pdf = f"{pdf_path}{pdf_file}"
    logging.info(f"Bereitsstellung der Dateinamen {pdf_file}, {zugferd_pdf}, {xml_file}, {path_pdf}")

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

            invoice_date = datetime.strptime(value, '%d.%m.%Y').strftime('%Y%m%d')
            break
        except ValueError:
            print("Das Datum muss im Format dd.mm.YYYY eingegeben werden.")

    # Entry of payment terms and validation.
    while True:
        try:
            global paymentterms
            description = invoice_data["descriptions"]["PaymentTerms"]
            value = invoice_data["invoice"][9]["SpecifiedTradePaymentTerms"]["PaymentTerms"]
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

# Creation of the guideline/profile identifier (GuidelineSpecifiedDocumentContextParameter)
def create_context(file):
    file.write('    <!-- ZUGFeRD 2.5 / EN16931 -->\n')
    file.write('    <rsm:ExchangedDocumentContext>\n')
    file.write('        <ram:GuidelineSpecifiedDocumentContextParameter>\n')
    file.write('            <ram:ID>')
    file.write('urn:cen.eu:en16931:2017#conformant#urn:factur-x.eu:1p0:extended')
    file.write('</ram:ID>\n')
    file.write('        </ram:GuidelineSpecifiedDocumentContextParameter>\n')
    file.write('    </rsm:ExchangedDocumentContext>\n')

# Generation of the ExchangedDocument for the ZUGFeRD XML
def create_document(file):
    file.write('    <rsm:ExchangedDocument>\n')
    file.write(f'        <ram:ID>{invoice_number_pre}_{buyer_id}_{invoice_date}</ram:ID>\n')
    file.write(f'        <ram:TypeCode>{type_code1}</ram:TypeCode>\n')
    file.write('        <ram:IssueDateTime>\n')
    file.write(f'            <udt:DateTimeString format="102">{invoice_date}</udt:DateTimeString>\n')
    file.write('        </ram:IssueDateTime>\n')
    file.write('    </rsm:ExchangedDocument>\n')    

# Generation of the invoice line items for the ZUGFeRD XML
def create_trade_line_item(file):
    global LineAmount
    LineAmount = {}
    for position in range(1, positions + 1):
        unit_price = Decimal(str(globals()[f"unit_price{position}"]))
        quantity = Decimal(str(globals()[f"quantity{position}"]))
        LineAmount[position] = str((unit_price * quantity).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        
        file.write('        <ram:IncludedSupplyChainTradeLineItem>\n')
        file.write('            <ram:AssociatedDocumentLineDocument>\n')
        file.write(f'                <ram:LineID>{globals()[f"line{position}"]}</ram:LineID>\n')
        file.write('            </ram:AssociatedDocumentLineDocument>\n')
        file.write('            <ram:SpecifiedTradeProduct>\n')
        file.write(f'                <ram:Name>{escape(str(globals()[f"product_name{position}"]))}</ram:Name>\n')
        file.write('            </ram:SpecifiedTradeProduct>\n')
        file.write('            <ram:SpecifiedLineTradeAgreement>\n')
        file.write('                <ram:NetPriceProductTradePrice>\n')
        file.write(f'                    <ram:ChargeAmount>{globals()[f"unit_price{position}"]:.2f}</ram:ChargeAmount>\n')
        file.write('                </ram:NetPriceProductTradePrice>\n')
        file.write('            </ram:SpecifiedLineTradeAgreement>\n')
        file.write('            <ram:SpecifiedLineTradeDelivery>\n')
        file.write(f'                <ram:BilledQuantity unitCode="{globals()[f"unitCode{position}"]}">{globals()[f"quantity{position}"]}</ram:BilledQuantity>\n')
        file.write('            </ram:SpecifiedLineTradeDelivery>\n')
        file.write('            <ram:SpecifiedLineTradeSettlement>\n')
        file.write('                <ram:ApplicableTradeTax>\n')
        file.write(f'                    <ram:TypeCode>{type_code3}</ram:TypeCode>\n')
        file.write(f'                    <ram:CategoryCode>{category_code}</ram:CategoryCode>\n')
        file.write(f'                    <ram:RateApplicablePercent>{globals()[f"RateApplicablePercent{position}"]}</ram:RateApplicablePercent>\n')
        file.write('                </ram:ApplicableTradeTax>\n')
        file.write('                <ram:SpecifiedTradeSettlementLineMonetarySummation>\n')
        file.write(f'                    <ram:LineTotalAmount>{LineAmount[position]}</ram:LineTotalAmount>\n')
        file.write('                </ram:SpecifiedTradeSettlementLineMonetarySummation>\n')
        file.write('            </ram:SpecifiedLineTradeSettlement>\n')
        file.write('        </ram:IncludedSupplyChainTradeLineItem>\n')

# Generation of the invoice issuer (SellerTradeParty) of the ZUGFeRD-XML
def create_seller(file):
    file.write('            <ram:SellerTradeParty>\n')
    file.write(f'                <ram:Name>{escape(str(seller_name))}</ram:Name>\n')
    file.write('                <ram:PostalTradeAddress>\n')
    file.write(f'                    <ram:PostcodeCode>{escape(str(seller_postcode))}</ram:PostcodeCode>\n')
    file.write(f'                    <ram:LineOne>{escape(str(seller_street))}</ram:LineOne>\n')
    file.write(f'                    <ram:CityName>{escape(str(seller_city))}</ram:CityName>\n')
    file.write(f'                    <ram:CountryID>{escape(str(seller_country))}</ram:CountryID>\n')
    file.write('                </ram:PostalTradeAddress>\n') 
    file.write('                <ram:SpecifiedTaxRegistration>\n')
    file.write(f'                    <ram:ID schemeID="{schemeID}">{escape(str(seller_vat_id))}</ram:ID>\n')
    file.write('                </ram:SpecifiedTaxRegistration>\n')
    file.write('            </ram:SellerTradeParty>\n')

# Generation of the invoice recipient (BuyerTradeParty)
def create_buyer(file):
    file.write('            <ram:BuyerTradeParty>\n')
    file.write(f'                <ram:Name>{escape(str(buyer_name))}</ram:Name>\n')
    file.write('                <ram:PostalTradeAddress>\n')
    file.write(f'                    <ram:PostcodeCode>{escape(str(buyer_postcode))}</ram:PostcodeCode>\n')
    file.write(f'                    <ram:LineOne>{escape(str(buyer_street))}</ram:LineOne>\n')
    file.write(f'                    <ram:CityName>{escape(str(buyer_city))}</ram:CityName>\n')
    file.write(f'                    <ram:CountryID>{escape(str(buyer_country))}</ram:CountryID>\n')
    file.write('                </ram:PostalTradeAddress>\n')
    file.write('            </ram:BuyerTradeParty>\n')

# Generation of payment information or payment terms (PaymentMeans)
def create_credit_transfer(file):
    file.write('            <ram:SpecifiedTradeSettlementPaymentMeans>\n')
    file.write(f'                <ram:TypeCode>{type_code2}</ram:TypeCode>\n')
    file.write(f'                <ram:Information>{escape(str(information1))}</ram:Information>\n')
    file.write('                <ram:PayeePartyCreditorFinancialAccount>\n')
    file.write(f'                    <ram:IBANID>{escape(str(iban_id))}</ram:IBANID>\n')
    file.write('                </ram:PayeePartyCreditorFinancialAccount>\n')
    file.write('                <ram:PayeeSpecifiedCreditorFinancialInstitution>\n')
    file.write(f'                    <ram:BICID>{escape(str(bic_id))}</ram:BICID>\n')
    file.write('                </ram:PayeeSpecifiedCreditorFinancialInstitution>\n')
    file.write('            </ram:SpecifiedTradeSettlementPaymentMeans>\n')
    logging.info(f"Eintrag von PayeePartyCreditorFinancialAccount, da Typ Überweisung.")

# Generation of the SEPA Direct Debit payment method
def create_direct_debit(file):
    file.write('            <ram:SpecifiedTradeSettlementPaymentMeans>\n')
    file.write(f'                <ram:TypeCode>{type_code2}</ram:TypeCode>\n')
    file.write(f'                <ram:Information>{escape(str(information2))}</ram:Information>\n')
    file.write('            </ram:SpecifiedTradeSettlementPaymentMeans>\n')
    logging.info(f"Eintraggenerierung für den Typ SEPA-Lastschrift.")

# Generation of the SEPA direct debit mandate reference (DirectDebitMandateID)
def create_direct_debit_mandatID(file):  
    file.write('                <ram:DirectDebitMandateID>\n')
    file.write(f'                    {escape(str(mandateID))}\n')
    file.write('                </ram:DirectDebitMandateID>\n')

# Generation of the delivery date (ActualDeliverySupplyChainEvent)
def create_actual_delivery_event(file):
    #file.write('        <ram:ApplicableHeaderTradeDelivery>\n')
    file.write('            <ram:ActualDeliverySupplyChainEvent>\n')
    file.write('                <ram:OccurrenceDateTime>\n')
    file.write(f'                   <udt:DateTimeString format="102">{deliveryDate}</udt:DateTimeString>\n')
    file.write('                </ram:OccurrenceDateTime>\n')
    file.write('            </ram:ActualDeliverySupplyChainEvent>\n')
    #file.write('        </ram:ApplicableHeaderTradeDelivery>\n')  

# Generation of the billing period (BillingSpecifiedPeriod)
def create_billing_specified_period(file):
    file.write('        <ram:BillingSpecifiedPeriod>\n')
    file.write('            <ram:StartDateTime>\n')
    file.write(f'               <udt:DateTimeString format="102">{StartDateTime}</udt:DateTimeString>\n')
    file.write('            </ram:StartDateTime>\n')
    file.write('            <ram:EndDateTime>\n')
    file.write(f'               <udt:DateTimeString format="102">{EndDateTime}</udt:DateTimeString>\n')
    file.write('            </ram:EndDateTime>\n')
    file.write('        </ram:BillingSpecifiedPeriod>\n')

# Rounding function for monetary amounts to two decimal places.
def rounded(value):
    return Decimal(value).quantize(Decimal("0.00"), rounding=ROUND_HALF_UP)

# Calculation of the total of all invoice line item amounts, taking into account multiple VAT rates.
def create_line_total_amount(file, vat_breakdowns):
    global line_total_amount
    line_total_amount = Decimal("0.00")
    for position in range(1, positions +1):
        line_total_amount += Decimal(LineAmount[position])

    return line_total_amount

# Calculation of discounts with different VAT rates
def create_discount(file, vat_breakdowns, vat_rate):
    global discount_actual_amount
    discount_basis_amount = vat_breakdowns[vat_rate]["BasisAmount"]
    discount_actual_amount = 0
    discount_actual_amount = (discount_basis_amount * CalculationPercent / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return discount_actual_amount

# Generation of the invoice discount (allowance) per VAT rate with calculation basis, discount amount and associated VAT rate.
def create_discount_position(file):
    for position in range(1, len(vat_breakdowns) + 1):
        vat_rate = list(vat_breakdowns.keys())[position - 1]

        discount_actual_amount = create_discount(file, vat_breakdowns, vat_rate)
        discount_basis_amount = vat_breakdowns[vat_rate]["BasisAmount"]

        file.write('            <ram:SpecifiedTradeAllowanceCharge>\n')
        file.write('                <ram:ChargeIndicator>\n')
        file.write('                    <udt:Indicator>false</udt:Indicator>\n')
        file.write('                </ram:ChargeIndicator>\n')
        file.write(f'                <ram:CalculationPercent>{CalculationPercent:.2f}</ram:CalculationPercent>\n')
        file.write(f'                <ram:BasisAmount currencyID="{currencyID}">{discount_basis_amount:.2f}</ram:BasisAmount>\n')
        file.write(f'                <ram:ActualAmount currencyID="{currencyID}">{discount_actual_amount:.2f}</ram:ActualAmount>\n')
        file.write(f'                <ram:Reason>{reason}</ram:Reason>\n')
        file.write('                <ram:CategoryTradeTax>\n')
        file.write(f'                    <ram:TypeCode>{type_code3}</ram:TypeCode>\n')
        file.write(f'                    <ram:CategoryCode>{category_code}</ram:CategoryCode>\n')
        file.write(f'                    <ram:RateApplicablePercent>{vat_rate:.2f}</ram:RateApplicablePercent>\n')
        file.write('                </ram:CategoryTradeTax>\n')
        file.write('            </ram:SpecifiedTradeAllowanceCharge>\n')
        file.write('\n')

# Determination and output of the payment term, including the due date, as well as the distinction between bank transfer and SEPA direct debit
def create_payment_terms(file):
    invoiceDate = datetime.strptime(invoice_date, "%Y%m%d")
    PaymentTerms = paymentterms
    if PaymentTerms == "sofort":
        due_date = invoiceDate + timedelta(days=2)
        logging.info(f"PaymentTerms ist: {PaymentTerms}")
    elif PaymentTerms in re.findall(r"'(\d+)'", descriptions["PaymentTerms"]):
        due_date = invoiceDate + timedelta(days=int(PaymentTerms))
        logging.info(f"PaymentTerms ist in elif: {PaymentTerms}")

    due_date = due_date.strftime("%Y-%m-%d")            

    file.write('            <ram:SpecifiedTradePaymentTerms>\n')
    file.write('                <ram:Description>\n')
    if PaymentTerms == "sofort":
        file.write(f'                    Zahlungsziel: {escape(str(PaymentTerms))} (fällig am {due_date})\n')
    else:
        file.write(f'                    Zahlungsziel: {escape(str(PaymentTerms))} Tage (fällig am {due_date})\n')
    file.write('                </ram:Description>\n')
    if type_code2 == 59:
        create_direct_debit_mandatID(file)
        logging.info(f"Eintrag der DirectDebitMandateID")
    else:
        logging.info(f"Kein Eintrag der DirectDebitMandateID, da Typ Überweisung.")        
    file.write('            </ram:SpecifiedTradePaymentTerms>\n')

# Calculation of total invoice amounts taking into account multiple VAT rates, including discount, tax, and payment amount.
def calculate_amounts(file):
    global line_total_amount
    global discount_actual_amount
    global tax_basis_amount
    global tax_total_amount

    line_total_amount = rounded(create_line_total_amount(file, vat_breakdowns))
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

# Generation of the `SpecifiedTradeSettlementHeaderMonetarySummation`—that is, the summation of the total monetary amounts in the invoice header.
def create_monetary_summation(file, amounts):
    file.write('            <ram:SpecifiedTradeSettlementHeaderMonetarySummation>\n')
    file.write(f'                <ram:LineTotalAmount>{amounts["line_total_amount"]:.2f}</ram:LineTotalAmount>\n')
    file.write(f'                <ram:AllowanceTotalAmount>{amounts["discount_actual_amount"]:.2f}</ram:AllowanceTotalAmount>\n')
    file.write(f'                <ram:TaxBasisTotalAmount>{amounts["tax_basis_amount"]:.2f}</ram:TaxBasisTotalAmount>\n')
    file.write(f'                <ram:TaxTotalAmount currencyID="{currencyID}">{amounts["calculated_amount"]:.2f}</ram:TaxTotalAmount>\n')
    file.write(f'                <ram:GrandTotalAmount>{amounts["grand_total_amount"]:.2f}</ram:GrandTotalAmount>\n')
    file.write(f'                <ram:TotalPrepaidAmount>{paid_amount:.2f}</ram:TotalPrepaidAmount>\n')
    file.write(f'                <ram:DuePayableAmount>{amounts["due_payable_amount"]:.2f}</ram:DuePayableAmount>\n')
    file.write('            </ram:SpecifiedTradeSettlementHeaderMonetarySummation>\n')

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
            "--source", f"{pdf_path}{zugferd_pdf}",
        ], check=True)

        logging.info(
            f"ZUGFeRD-Validierung erfolgreich: "
            f"{pdf_path}{zugferd_pdf}"
        )

    except subprocess.CalledProcessError:
        logging.exception(
            f"ZUGFeRD-Validierung fehlgeschlagen: "
            f"{pdf_path}{zugferd_pdf}"
        )
        raise


def main():
    check_mustang()
    setup_logging("invoicedata.yaml")

    logging.info("===========================================================")
    logging.info(f"Start der ZUGFeRD-PDF-Generierung um {datetime.now():%H:%M:%S} Uhr")

    invoice_data = load_invoice_data("invoicedata.yaml")

    for block in invoice_data["invoice"]:
        for level2, fields in block.items():
            for key, value in fields.items():
                globals()[key] = "" if value is None else value            

    read_inputs()

    # Construction of the ZUGFeRD XML file
    with open(os.path.join(xml_path, xml_file), "w", encoding="utf-8") as file:
        file.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        file.write('<rsm:CrossIndustryInvoice\n')
        file.write('    xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"\n')
        file.write('    xmlns:ram="urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"\n')
        file.write('    xmlns:qdt="urn:un:unece:uncefact:data:standard:QualifiedDataType:100"\n')
        file.write('    xmlns:udt="urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100">\n')
        file.write('\n')

        create_context(file)

        create_document(file)

        file.write('    <rsm:SupplyChainTradeTransaction>\n')
        create_trade_line_item(file)
        amounts = calculate_amounts(file)
        file.write('        <ram:ApplicableHeaderTradeAgreement>\n')
        create_seller(file)
        file.write('\n')
        create_buyer(file)
        file.write('        </ram:ApplicableHeaderTradeAgreement>\n')
        file.write('\n')
        file.write('        <ram:ApplicableHeaderTradeDelivery>\n')
        if deliveryDate:
            create_actual_delivery_event(file)
        file.write('        </ram:ApplicableHeaderTradeDelivery>\n')
        file.write('\n')
        file.write('        <ram:ApplicableHeaderTradeSettlement>\n')
        file.write(f'            <ram:CreditorReferenceID>{creditor_reference_id}</ram:CreditorReferenceID>\n')
        file.write(f'            <ram:PaymentReference>{escape(str(invoice_number_pre))}_{escape(str(buyer_id))}_{invoice_date}</ram:PaymentReference>\n')
        file.write(f'            <ram:InvoiceCurrencyCode>{InvoiceCurrencyCode}</ram:InvoiceCurrencyCode>\n')
        if type_code2 == 58:
            create_credit_transfer(file)
        elif type_code2 == 59:
            create_direct_debit(file)

        # If there are multiple VAT rates, more than one ApplicableTradeTax entry is generated.
        for position in range(1, len(vat_breakdowns) + 1):
            file.write('            <ram:ApplicableTradeTax>\n')
            file.write(f'                <ram:CalculatedAmount>{rounded((vat_breakdowns[list(vat_breakdowns.keys())[position - 1]]["BasisAmount"] - vat_breakdowns[list(vat_breakdowns.keys())[position - 1]]["BasisAmount"] * CalculationPercent / Decimal("100")) * list(vat_breakdowns.keys())[position - 1] / Decimal("100")):.2f}</ram:CalculatedAmount>\n')
            file.write(f'                <ram:TypeCode>{type_code3}</ram:TypeCode>\n')
            file.write(f'                <ram:BasisAmount>{(vat_breakdowns[list(vat_breakdowns.keys())[position - 1]]["BasisAmount"] - vat_breakdowns[list(vat_breakdowns.keys())[position - 1]]["BasisAmount"] * CalculationPercent / Decimal("100")):.2f}</ram:BasisAmount>\n')
            file.write(f'                <ram:CategoryCode>{category_code}</ram:CategoryCode>\n')
            file.write(f'                <ram:RateApplicablePercent>{list(vat_breakdowns.keys())[position - 1]:.2f}</ram:RateApplicablePercent>\n')
            file.write('            </ram:ApplicableTradeTax>\n')

        if not deliveryDate:
            create_billing_specified_period(file)
        
        if CalculationPercent > 0:
            create_discount_position(file)

        create_payment_terms(file)
        create_monetary_summation(file, amounts)
        file.write('        </ram:ApplicableHeaderTradeSettlement>\n')
        file.write('    </rsm:SupplyChainTradeTransaction>\n')
        file.write('</rsm:CrossIndustryInvoice>\n' )

    create_pdfdocument()
    validate_zugferd_pdf()
if __name__ == "__main__":
    main()
