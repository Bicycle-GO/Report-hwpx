"""Normalize only generated packages; do not rewrite uploaded user documents."""
from datetime import datetime, timezone
from io import BytesIO
from zipfile import ZipFile, ZIP_STORED, ZIP_DEFLATED
from lxml import etree as E
from .templates import HP

OPF = "http://www.idpf.org/2007/opf/"

def finalize_package(path, report):
    with ZipFile(path) as z:
        parts = {name: z.read(name) for name in z.namelist()}
    parser = E.XMLParser(resolve_entities=False, no_network=True)
    root = E.fromstring(parts["Contents/content.hpf"], parser)
    root.find(f".//{{{OPF}}}title").text = report.title
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    values = {"creator": report.department, "lastsaveby": "HWPX Studio",
              "CreatedDate": now, "ModifiedDate": now, "date": report.report_date}
    for meta in root.findall(f".//{{{OPF}}}meta"):
        meta.text = values.get(meta.get("name"), "")
    parts["Contents/content.hpf"] = E.tostring(root, encoding="utf-8", xml_declaration=True)
    # No old fixture thumbnail or out-of-date caret positions should survive export.
    parts.pop("Preview/PrvImage.png", None)
    preview = []
    list_id = 1
    for name in list(parts):
        if not name.endswith((".xml", ".hpf")):
            continue
        root = E.fromstring(parts[name], parser)
        if name.startswith("Contents/section"):
            for sub in root.iter(f"{{{HP}}}subList"):
                sub.set("id", str(list_id))
                list_id += 1
            preview.extend("".join(t.itertext()) for t in root.iter(f"{{{HP}}}t"))
        if name == "settings.xml":
            for el in root.iter():
                if E.QName(el).localname == "CaretPosition":
                    for key in ("listIDRef", "paraIDRef", "pos"):
                        el.set(key, "0")
        E.cleanup_namespaces(root)
        parts[name] = E.tostring(root, encoding="utf-8", xml_declaration=True, standalone=True)
    parts["Preview/PrvText.txt"] = "\r\n".join(preview).encode("utf-8")
    data = BytesIO()
    with ZipFile(data, "w") as z:
        z.writestr("mimetype", b"application/hwp+zip", compress_type=ZIP_STORED)
        for name, content in parts.items():
            if name != "mimetype":
                z.writestr(name, content, compress_type=ZIP_DEFLATED)
    path.write_bytes(data.getvalue())
