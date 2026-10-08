"""Anonymous source-quality fixture; no college documents or staff names."""

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile
import xml.etree.ElementTree as ET

S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
root = ET.Element("worksheet", xmlns=S)
data = ET.SubElement(root, "sheetData")


def row(number, values):
    record = ET.SubElement(data, "row", r=str(number))
    for column, value in values.items():
        attrs = {"r": f"{column}{number}"}
        if isinstance(value, str):
            attrs["t"] = "inlineStr"
            cell = ET.SubElement(record, "c", attrs)
            ET.SubElement(ET.SubElement(cell, "is"), "t").text = value
        else:
            cell = ET.SubElement(record, "c", attrs)
            ET.SubElement(cell, "v").text = str(value)


row(1, {"A": "год набора 2026"})
row(2, {"A": "Индекс", "B": "Дисциплина", "C": "октябрь"})
row(3, {"C": "5-11", "D": "12-18", "E": "19-25", "F": "26-31", "G": "1-7"})
row(4, {"A": "ОП.01", "B": "Анатомия теоретические занятия", "C": 32, "D": 30, "E": 34, "F": 608, "G": 32})
row(5, {"B": "Анатомия самостоятельная работа", "C": 4, "D": 4, "E": 4, "F": 4, "G": 4})
row(6, {"B": "Всего часов в неделю", "C": 36, "D": 34, "E": 38, "F": 612, "G": 40})

path = Path("/tmp/college-e2e-kug.xlsx")
with ZipFile(path, "w", ZIP_DEFLATED) as archive:
    archive.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
    archive.writestr("_rels/.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
    archive.writestr("xl/workbook.xml", f'<?xml version="1.0"?><workbook xmlns="{S}" xmlns:r="{R}"><sheets><sheet name="Проверка импорта" sheetId="1" r:id="rId1"/></sheets></workbook>')
    archive.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
    archive.writestr("xl/worksheets/sheet1.xml", ET.tostring(root, encoding="utf-8", xml_declaration=True))
