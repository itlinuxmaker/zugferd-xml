from decimal import Decimal, ROUND_HALF_UP
import unittest


class TestInvoiceAmounts(unittest.TestCase):

    def test_line_amount_rounding(self):
        quantity = Decimal("15.75")
        unit_price = Decimal("89.50")

        line_amount = (quantity * unit_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        self.assertEqual(line_amount, Decimal("1409.63"))

    def test_line_total_amount(self):
        line1 = Decimal("2532.87")
        line2 = Decimal("1409.63")

        line_total = line1 + line2

        self.assertEqual(line_total, Decimal("3942.50"))

    def test_discount_per_vat_rate(self):
        basis_19 = Decimal("2532.87")
        basis_16 = Decimal("1409.63")
        discount = Decimal("5.50")

        discount_19 = (
            basis_19 * discount / Decimal("100")
        ).quantize(Decimal("0.01"))

        discount_16 = (
            basis_16 * discount / Decimal("100")
        ).quantize(Decimal("0.01"))

        self.assertEqual(discount_19, Decimal("139.31"))
        self.assertEqual(discount_16, Decimal("77.53"))

    def test_total_discount(self):
        discount_19 = Decimal("139.31")
        discount_16 = Decimal("77.53")

        discount_total = discount_19 + discount_16

        self.assertEqual(discount_total, Decimal("216.84"))

    def test_tax_basis(self):
        line_total = Decimal("3942.50")
        discount_total = Decimal("216.84")

        tax_basis = line_total - discount_total

        self.assertEqual(tax_basis, Decimal("3725.66"))

    def test_vat_19_percent(self):
        tax_basis_19 = Decimal("2532.87") - Decimal("139.31")

        vat_19 = (
            tax_basis_19 * Decimal("19.00") / Decimal("100")
        ).quantize(Decimal("0.01"))

        self.assertEqual(tax_basis_19, Decimal("2393.56"))
        self.assertEqual(vat_19, Decimal("454.78"))

    def test_vat_16_percent(self):
        tax_basis_16 = Decimal("1409.63") - Decimal("77.53")

        vat_16 = (
            tax_basis_16 * Decimal("16.00") / Decimal("100")
        ).quantize(Decimal("0.01"))

        self.assertEqual(tax_basis_16, Decimal("1332.10"))
        self.assertEqual(vat_16, Decimal("213.14"))

    def test_total_vat(self):
        vat_19 = Decimal("454.78")
        vat_16 = Decimal("213.14")

        tax_total = vat_19 + vat_16

        self.assertEqual(tax_total, Decimal("667.92"))

    def test_grand_total(self):
        tax_basis = Decimal("3725.66")
        tax_total = Decimal("667.92")

        grand_total = tax_basis + tax_total

        self.assertEqual(grand_total, Decimal("4393.58"))

    def test_due_payable_amount(self):
        grand_total = Decimal("4393.58")
        prepaid = Decimal("500.50")

        due = grand_total - prepaid

        self.assertEqual(due, Decimal("3893.08"))


if __name__ == "__main__":
    unittest.main()