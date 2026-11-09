"""Builds tests/fixture.pdf: header/footer, filled box behind text, image stamp,
vector stamp with text over it, mixed bold+regular on one line, a subset-embedded
system font, and rotated text."""
import sys, pymupdf
out = sys.argv[1] if len(sys.argv) > 1 else "tests/fixture.pdf"
doc = pymupdf.open(); p = doc.new_page()
arial = "/System/Library/Fonts/Supplemental/Arial.ttf"
p.insert_font(fontname="ar", fontfile=arial)
p.draw_rect((0, 0, 595, 50), fill=(0.1, 0.2, 0.5), color=None)
p.insert_text((40, 32), "ACME CORP — CONFIDENTIAL", fontname="hebo", fontsize=16, color=(1, 1, 1))
p.draw_rect((40, 90, 400, 130), fill=(1, 0.95, 0.6), color=(0.8, 0.6, 0))
p.insert_text((50, 115), "Invoice No: INV-2041", fontname="ar", fontsize=13)
p.insert_text((50, 160), "Customer:", fontname="hebo", fontsize=12)
p.insert_text((50 + pymupdf.get_text_length("Customer:", "hebo", 12), 160), " Ramesh Kumar", fontname="helv", fontsize=12)
p.insert_text((50, 175), "Amount due: Rs 12,500.00 by 30 Nov 2026", fontname="tiro", fontsize=12, color=(0.6, 0, 0))
pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 60, 60), 0); pix.set_rect(pix.irect, (200, 30, 30))
p.insert_image((420, 140, 500, 220), pixmap=pix)
p.draw_circle((480, 300), 50, color=(0, 0.5, 0), width=3)
p.insert_text((445, 305), "PAID", fontname="hebo", fontsize=22, color=(0, 0.5, 0))
p.insert_text((50, 300), "Paid on stamp line", fontname="helv", fontsize=11)
p.insert_text((30, 600), "ROTATED NOTE", fontname="helv", fontsize=10, rotate=90)
p.draw_line((40, 800), (555, 800), color=(0.5, 0.5, 0.5))
p.insert_text((40, 815), "Page 1 of 1 · footer text", fontname="helv", fontsize=8, color=(0.4, 0.4, 0.4))
doc.subset_fonts()
doc.save(out)
print("wrote", out)
