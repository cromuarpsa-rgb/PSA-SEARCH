from pathlib import Path
import json
import zipfile
import xml.etree.ElementTree as ET

BASE_DIR = Path(__file__).resolve().parents[1]
WORKBOOK_PATH = BASE_DIR / "data" / "032026_Sorted PSOC PSIC.xlsx"
OUTPUT_PATH = BASE_DIR / "data" / "psa-data.json"
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def column_index(ref):
    letters = "".join(ch for ch in ref if ch.isalpha()).upper()
    number = 0
    for char in letters:
        number = number * 26 + ord(char) - ord("A") + 1
    return max(0, number - 1)


def text_of(element):
    if element is None:
        return ""
    return "".join(element.itertext())


def read_shared_strings(book):
    try:
        root_xml = ET.fromstring(book.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    return ["".join(item.itertext()) for item in root_xml.findall("m:si", NS)]


from pathlib import PurePosixPath

def normalize_rel_target(target):
    raw = target.lstrip("/")
    parts = []
    path = PurePosixPath(raw)
    if not str(path).startswith("xl/"):
        path = PurePosixPath("xl") / path
    for part in path.parts:
        if part == ".":
            continue
        if part == "..":
            if parts and parts[-1] != "..":
                parts.pop()
            else:
                parts.append(part)
        else:
            parts.append(part)
    return PurePosixPath(*parts).as_posix()


def read_sheet_targets(book):
    workbook = ET.fromstring(book.read("xl/workbook.xml"))
    rels = ET.fromstring(book.read("xl/_rels/workbook.xml.rels"))
    rel_map = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels}
    sheets = []
    rid_key = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    for sheet in workbook.findall("m:sheets/m:sheet", NS):
        target = rel_map.get(sheet.attrib.get(rid_key), "")
        target = normalize_rel_target(target)
        sheets.append((sheet.attrib["name"], target))
    return sheets


def read_cell(cell, strings):
    kind = cell.attrib.get("t")
    value = cell.find("m:v", NS)
    if kind == "s":
        raw = text_of(value)
        if raw.isdigit() and int(raw) < len(strings):
            return strings[int(raw)]
        return raw
    if kind == "inlineStr":
        return text_of(cell.find("m:is", NS))
    if kind == "b":
        return "TRUE" if text_of(value) == "1" else "FALSE"
    return text_of(value)


def parse_sheet(book, target, strings):
    root_xml = ET.fromstring(book.read(target))
    raw_rows = []
    for row in root_xml.findall("m:sheetData/m:row", NS):
        values = []
        for cell in row.findall("m:c", NS):
            index = column_index(cell.attrib.get("r", "")) if cell.attrib.get("r") else len(values)
            while len(values) <= index:
                values.append("")
            values[index] = read_cell(cell, strings).strip()
        if any(values):
            raw_rows.append(values)
    if not raw_rows:
        return {"columns": [], "rows": []}
    width = max(len(row) for row in raw_rows)
    header = raw_rows[0]
    columns = []
    seen = {}
    for index in range(width):
        name = header[index].strip() if index < len(header) else ""
        name = name or f"Column {index + 1}"
        seen[name] = seen.get(name, 0) + 1
        columns.append(name if seen[name] == 1 else f"{name} {seen[name]}")
    rows = []
    for raw in raw_rows[1:]:
        item = {column: raw[index] if index < len(raw) else "" for index, column in enumerate(columns)}
        if any(item.values()):
            rows.append(item)
    return {"columns": columns, "rows": rows}


def export_workbook():
    with zipfile.ZipFile(WORKBOOK_PATH) as book:
        strings = read_shared_strings(book)
        sheets = []
        for name, target in read_sheet_targets(book):
            parsed = parse_sheet(book, target, strings)
            sheets.append({
                "name": name,
                "columns": parsed["columns"],
                "rows": parsed["rows"],
                "count": len(parsed["rows"]),
            })
    payload = {"file": WORKBOOK_PATH.name, "sheets": sheets}
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


if __name__ == "__main__":
    payload = export_workbook()
    print(f"Exported {payload['file']} to {OUTPUT_PATH.relative_to(BASE_DIR)}")
    print(f"Sheets: {len(payload['sheets'])}")
