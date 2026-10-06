"""Create an anonymous DOCX for browser checks; no college source data."""
from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def create(path):
    root = ET.Element(W + "document")
    body = ET.SubElement(root, W + "body")

    def paragraph(parent, value):
        p = ET.SubElement(parent, W + "p")
        ET.SubElement(ET.SubElement(p, W + "r"), W + "t").text = value

    paragraph(body, "I семестр, учебный пример для проверки")
    table = ET.SubElement(body, W + "tbl")
    for values in [
        ["", "Дисциплина", "теория", "практика"],
        ["", "Раздел для проверки Word", "4\n1-9ЛД126 Тестова А.Б.", ""],
    ]:
        tr = ET.SubElement(table, W + "tr")
        for value in values:
            cell = ET.SubElement(tr, W + "tc")
            for line in value.split("\n"):
                paragraph(cell, line)
    with ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", ET.tostring(root))


if __name__ == "__main__":
    create(Path("/tmp/college-e2e-word.docx"))
