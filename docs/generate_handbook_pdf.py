from pathlib import Path
import re
import textwrap


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "mid_defense_handbook.md"
OUTPUT = ROOT / "RinSathi_Mid_Defense_Handbook.pdf"


def escape_pdf_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def markdown_to_lines(markdown: str) -> list[tuple[str, int]]:
    lines: list[tuple[str, int]] = []
    in_code = False

    for raw in markdown.splitlines():
        line = raw.rstrip()

        if line.startswith("```"):
            in_code = not in_code
            continue

        if in_code:
            wrapped = textwrap.wrap(line, width=88, replace_whitespace=False) or [""]
            for item in wrapped:
                lines.append((item, 9))
            continue

        if not line:
            lines.append(("", 10))
            continue

        if line == "---":
            lines.append(("-" * 88, 9))
            continue

        heading = re.match(r"^(#{1,3})\s+(.*)$", line)
        if heading:
            level = len(heading.group(1))
            text = heading.group(2)
            size = 17 if level == 1 else 14 if level == 2 else 12
            lines.append((text, size))
            lines.append(("", 6))
            continue

        bullet = re.match(r"^-\s+(.*)$", line)
        if bullet:
            text = "- " + re.sub(r"`([^`]*)`", r"\1", bullet.group(1))
            wrapped = textwrap.wrap(text, width=92, subsequent_indent="  ")
            for item in wrapped:
                lines.append((item, 10))
            continue

        numbered = re.match(r"^(\d+)\.\s+(.*)$", line)
        if numbered:
            text = f"{numbered.group(1)}. " + re.sub(r"`([^`]*)`", r"\1", numbered.group(2))
            wrapped = textwrap.wrap(text, width=92, subsequent_indent="   ")
            for item in wrapped:
                lines.append((item, 10))
            continue

        clean = re.sub(r"\*\*([^*]+)\*\*", r"\1", line)
        clean = re.sub(r"`([^`]*)`", r"\1", clean)
        wrapped = textwrap.wrap(clean, width=96) or [""]
        for item in wrapped:
            lines.append((item, 10))

    return lines


def build_pdf(lines: list[tuple[str, int]]) -> bytes:
    page_width = 612
    page_height = 792
    left = 54
    top = 744
    bottom = 54

    pages: list[list[tuple[str, int, int]]] = []
    current: list[tuple[str, int, int]] = []
    y = top

    for text, size in lines:
        leading = max(size + 4, 12)
        if y - leading < bottom:
            pages.append(current)
            current = []
            y = top
        current.append((text, size, y))
        y -= leading

    if current:
        pages.append(current)

    objects: list[bytes] = []

    def add(obj: bytes) -> int:
        objects.append(obj)
        return len(objects)

    catalog_id = add(b"<< /Type /Catalog /Pages 2 0 R >>")
    pages_id = add(b"")
    font_id = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    page_ids: list[int] = []
    content_ids: list[int] = []

    for page_number, page in enumerate(pages, start=1):
        commands = ["BT", f"/F1 10 Tf"]
        for text, size, y in page:
            if text:
                commands.append(f"/F1 {size} Tf")
                commands.append(f"1 0 0 1 {left} {y} Tm ({escape_pdf_text(text)}) Tj")
        commands.append(f"/F1 8 Tf")
        commands.append(f"1 0 0 1 {left} 30 Tm (RinSathi Mid-Defense Handbook | Page {page_number}) Tj")
        commands.append("ET")
        stream = "\n".join(commands).encode("latin-1", errors="replace")
        content_id = add(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
        page_id = add(
            f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {page_width} {page_height}] "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {content_id} 0 R >>".encode()
        )
        content_ids.append(content_id)
        page_ids.append(page_id)

    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects[pages_id - 1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode()

    pdf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{index} 0 obj\n".encode())
        pdf.extend(obj)
        pdf.extend(b"\nendobj\n")

    xref_pos = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode())
    pdf.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF\n".encode()
    )
    return bytes(pdf)


def main() -> None:
    markdown = SOURCE.read_text(encoding="utf-8")
    lines = markdown_to_lines(markdown)
    OUTPUT.write_bytes(build_pdf(lines))
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    main()
