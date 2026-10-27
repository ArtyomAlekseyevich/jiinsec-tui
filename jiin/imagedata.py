# Read a photo's metadata and write a clean copy. All local, nothing uploaded.
# JPEG and PNG are cleaned losslessly (metadata dropped, pixels untouched); other formats are re-encoded.
from __future__ import annotations

import io
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path

from PIL import ExifTags, Image, IptcImagePlugin

SEV_RANK = {"high": 3, "med": 2, "low": 1}


@dataclass
class Finding:
    group: str
    label: str
    value: str
    why: str
    sev: str


@dataclass
class Report:
    path: Path
    fmt: str
    size: int
    width: int
    height: int
    findings: list[Finding] = field(default_factory=list)
    gps: tuple[float, float] | None = None
    orientation: int = 1
    extra_bytes: int = 0

    @property
    def risk(self) -> str:
        if any(f.sev == "high" for f in self.findings):
            return "high"
        if any(f.sev == "med" for f in self.findings):
            return "med"
        return "clean"

    def summary(self) -> str:
        F = self.findings
        if not F:
            return "No hidden location, device, time or personal data was found in this file."
        parts = []
        if self.gps:
            parts.append("your exact GPS location")
        elif any(f.group == "Location" and SEV_RANK[f.sev] >= 2 for f in F):
            parts.append("a written location")
        if any(f.group == "Embedded preview" and f.sev == "high" for f in F):
            parts.append("a preview that may show what you cropped out")
        if any(f.label in ("Camera owner name", "Author", "Named people (face regions)") for f in F):
            parts.append("names")
        if any(f.group == "Device" and SEV_RANK[f.sev] >= 2 for f in F):
            parts.append("device identifiers")
        if any(f.group == "Time" and SEV_RANK[f.sev] >= 2 for f in F):
            parts.append("when it was taken")
        if not parts:
            return "Only minor technical details were found (camera model, software and similar)."
        t = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
        return f"This file contains {t}."


# helpers

def _s(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bytes):
        # XP* tags are UTF-16LE; UserComment starts with an 8-byte charset header
        if v[:8] in (b"ASCII\0\0\0", b"UNICODE\0", b"\0" * 8):
            body = v[8:]
            v = body.decode("utf-16" if v[:8] == b"UNICODE\0" else "latin-1", "ignore")
        else:
            try:
                v = v.decode("utf-16-le") if len(v) % 2 == 0 and b"\0" in v else v.decode("utf-8", "ignore")
            except UnicodeDecodeError:
                v = v.decode("latin-1", "ignore")
    elif isinstance(v, tuple) and v and isinstance(v[0], int) and all(0 <= x < 256 for x in v):
        return _s(bytes(v))
    return str(v).replace("\0", "").strip()


def _f(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0


def _dms(vals, ref) -> float | None:
    try:
        d, m, s = (_f(x) for x in vals)
    except (TypeError, ValueError):
        return None
    v = d + m / 60 + s / 3600
    return -v if str(ref).upper().startswith(("S", "W")) else v


def _dms_text(v: float, pos: str, neg: str) -> str:
    t = round(abs(v) * 36000)
    d, m, s = t // 36000, (t % 36000) // 600, (t % 600) / 10
    return f"{d}°{m:02d}′{s:04.1f}″{pos if v >= 0 else neg}"


def _dt(s: str) -> str:
    m = re.match(r"^(\d{4}):(\d\d):(\d\d)[ T](\d\d:\d\d:\d\d)", s or "")
    return f"{m[1]}-{m[2]}-{m[3]} {m[4]}" if m else (s or "")


def _compass(d: float) -> str:
    pts = "N NNE NE ENE E ESE SE SSE S SSW SW WSW W WNW NW NNW".split()
    return pts[round((d % 360) / 22.5) % 16]


def _uniq(*vals) -> str:
    out = []
    for v in vals:
        v = _s(v)
        if v and v not in out:
            out.append(v)
    return " / ".join(out)


# XMP

def _xmp_packet(raw: bytes) -> str:
    a = raw.find(b"<x:xmpmeta")
    if a < 0:
        a = raw.find(b"<rdf:RDF")
    if a < 0:
        return ""
    b = raw.find(b"</x:xmpmeta>", a)
    if b < 0:
        b = raw.find(b"</rdf:RDF>", a)
    if b < 0:
        return ""
    return raw[a:b + 12].decode("utf-8", "ignore")


def _xmp_get(x: str, name: str) -> str:
    # attribute form:  ns:Name="value"
    m = re.search(r'\b' + re.escape(name) + r'="([^"]*)"', x)
    if m:
        return m.group(1).strip()
    # element form: <ns:Name>value</ns:Name>  or with rdf:Alt/Seq/Bag lists
    m = re.search(r"<" + re.escape(name) + r"\b[^>]*>(.*?)</" + re.escape(name) + ">", x, re.S)
    if not m:
        return ""
    inner = m.group(1)
    items = re.findall(r"<rdf:li\b[^>]*>(.*?)</rdf:li>", inner, re.S)
    txt = ", ".join(i.strip() for i in items if i.strip()) if items else inner
    return re.sub(r"<[^>]+>", "", txt).strip()


def _xmp_gps(s: str) -> float | None:
    # XMP GPS looks like "52,30.123N" or "52,30,7.4N"
    m = re.match(r"^\s*(\d+),(\d+(?:\.\d+)?)(?:,(\d+(?:\.\d+)?))?([NSEW])\s*$", s or "")
    if not m:
        return None
    v = int(m[1]) + float(m[2]) / 60 + (float(m[3]) / 3600 if m[3] else 0)
    return -v if m[4] in "SW" else v


# JPEG structure

def _jpeg_segments(a: bytes):
    """Yield (marker, start, data_start, end) for header segments up to SOS; then ('SOS', pos)."""
    i = 2
    n = len(a)
    while i + 4 <= n:
        if a[i] != 0xFF:
            return
        m = a[i + 1]
        if m == 0xFF:
            i += 1
            continue
        if m in (0xD8, 0x01) or 0xD0 <= m <= 0xD7:
            i += 2
            continue
        ln = struct.unpack(">H", a[i + 2:i + 4])[0]
        yield m, i, i + 4, i + 2 + ln
        if m == 0xDA:
            return
        i += 2 + ln


def _jpeg_end(a: bytes) -> int:
    """Byte offset just past the EOI of the main image (walks progressive scans too)."""
    sos = None
    for m, s, d, e in _jpeg_segments(a):
        if m == 0xDA:
            sos = e
    if sos is None:
        return len(a)
    i, n = sos, len(a)
    while i < n - 1:
        if a[i] == 0xFF:
            m = a[i + 1]
            if m == 0x00 or 0xD0 <= m <= 0xD7 or m == 0xFF:
                i += 1 if m == 0xFF else 2
                continue
            if m == 0xD9:
                return i + 2
            if i + 4 > n:
                break
            ln = struct.unpack(">H", a[i + 2:i + 4])[0]   # DHT / SOS / DRI between progressive scans
            i += 2 + ln
            continue
        i += 1
    return n


def _min_exif_orientation(orient: int) -> bytes:
    tiff = b"MM\0*" + struct.pack(">I", 8) + struct.pack(">H", 1) + struct.pack(">HHIHH", 0x0112, 3, 1, orient, 0) + struct.pack(">I", 0)
    return tiff


def clean_jpeg(a: bytes, orient: int) -> bytes:
    out = [b"\xFF\xD8"]
    sos = None
    for m, s, d, e in _jpeg_segments(a):
        if m == 0xDA:
            sos = s
            break
        keep = True
        if m == 0xE0:
            keep = a[d:d + 5] == b"JFIF\0"
        elif m == 0xE2:
            keep = a[d:d + 12] == b"ICC_PROFILE\0"
        elif m == 0xEE:
            keep = a[d:d + 5] == b"Adobe"
        elif 0xE1 <= m <= 0xEF or m == 0xFE:
            keep = False
        if keep:
            out.append(a[s:e])
    if sos is None:
        raise ValueError("This JPEG has no readable image data.")
    if orient != 1:
        body = b"Exif\0\0" + _min_exif_orientation(orient)
        out.insert(2 if len(out) > 1 and out[1][1] == 0xE0 else 1, b"\xFF\xE1" + struct.pack(">H", len(body) + 2) + body)
    out.append(a[sos:_jpeg_end(a)])
    return b"".join(out)


PNG_KEEP = {b"IHDR", b"PLTE", b"IDAT", b"IEND", b"tRNS", b"cHRM", b"gAMA", b"iCCP", b"sBIT", b"sRGB",
            b"cICP", b"mDCv", b"cLLi", b"bKGD", b"pHYs", b"acTL", b"fcTL", b"fdAT"}


def clean_png(a: bytes, orient: int) -> bytes:
    import zlib
    out = [a[:8]]
    i, n, placed = 8, len(a), False
    while i + 12 <= n:
        ln = struct.unpack(">I", a[i:i + 4])[0]
        t = a[i + 4:i + 8]
        end = i + 12 + ln
        if end > n:
            break
        if t == b"IDAT" and orient != 1 and not placed:
            blk = _min_exif_orientation(orient)
            out.append(struct.pack(">I", len(blk)) + b"eXIf" + blk + struct.pack(">I", zlib.crc32(b"eXIf" + blk)))
            placed = True
        if t in PNG_KEEP:
            out.append(a[i:end])
        i = end
        if t == b"IEND":
            break
    return b"".join(out)


def _png_chunks(a: bytes):
    i, n = 8, len(a)
    while i + 12 <= n:
        ln = struct.unpack(">I", a[i:i + 4])[0]
        t = a[i + 4:i + 8]
        yield t, a[i + 8:i + 8 + ln]
        i += 12 + ln
        if t == b"IEND":
            yield b"__END__", i.to_bytes(8, "big")
            return


# analysis

def analyse(path: str | Path) -> Report:
    p = Path(path).expanduser()
    raw = p.read_bytes()
    try:
        im = Image.open(io.BytesIO(raw))
        im.load()
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"Not an image Pillow can read ({e.__class__.__name__}). JPEG, PNG, WebP, TIFF and GIF work.") from e
    fmt = (im.format or "?").lower()
    R = Report(path=p, fmt=fmt, size=len(raw), width=im.width, height=im.height)
    F = R.findings

    def add(g, k, v, why, s):
        v = _s(v) if not isinstance(v, str) else v.strip()
        if v:
            F.append(Finding(g, k, v, why, s))

    ex = im.getexif()
    base = dict(ex)
    try:
        exif = dict(ex.get_ifd(ExifTags.IFD.Exif))
    except Exception:  # noqa: BLE001
        exif = {}
    try:
        gps = dict(ex.get_ifd(ExifTags.IFD.GPSInfo))
    except Exception:  # noqa: BLE001
        gps = {}
    R.orientation = int(base.get(0x0112, 1) or 1)
    xmp = _xmp_packet(raw)
    try:
        iptc = IptcImagePlugin.getiptcinfo(im) or {}
    except Exception:  # noqa: BLE001
        iptc = {}

    def ip(ds):
        v = iptc.get((2, ds))
        if isinstance(v, list):
            v = b", ".join(v)
        return _s(v)

    G = ExifTags.GPS
    B = ExifTags.Base
    # Location
    lat = lon = None
    if G.GPSLatitude in gps and G.GPSLongitude in gps:
        lat = _dms(gps[G.GPSLatitude], gps.get(G.GPSLatitudeRef, "N"))
        lon = _dms(gps[G.GPSLongitude], gps.get(G.GPSLongitudeRef, "E"))
    if lat is not None and lon is not None and (abs(lat) > 1e-7 or abs(lon) > 1e-7):
        R.gps = (lat, lon)
        add("Location", "GPS position", f"{lat:.6f}, {lon:.6f}  ({_dms_text(lat, 'N', 'S')} {_dms_text(lon, 'E', 'W')})",
            "Paste these numbers into any map and it shows where the photo was taken - often a home, school or workplace.", "high")
    elif lat is not None:
        add("Location", "GPS fields present but empty", "0, 0", "Location tagging was on, but no real position is stored.", "low")
    else:
        xl, xo = _xmp_gps(_xmp_get(xmp, "exif:GPSLatitude")), _xmp_gps(_xmp_get(xmp, "exif:GPSLongitude"))
        if xl is not None and xo is not None:
            R.gps = (xl, xo)
            add("Location", "GPS position (XMP)", f"{xl:.6f}, {xo:.6f}", "An exact map position stored in the XMP block.", "high")
    if R.gps and lat is not None:
        if G.GPSHPositioningError in gps:
            add("Location", "Position accuracy", f"within about {round(_f(gps[G.GPSHPositioningError]))} m", "A small number means a building-level fix.", "low")
        if G.GPSAltitude in gps:
            alt = _f(gps[G.GPSAltitude]) * (-1 if gps.get(G.GPSAltitudeRef) in (1, b"\x01") else 1)
            add("Location", "Altitude", f"{round(alt)} m {'below' if alt < 0 else 'above'} sea level", "Can hint at a floor of a building or a hillside.", "low")
        if G.GPSImgDirection in gps:
            d = _f(gps[G.GPSImgDirection])
            add("Location", "Direction the camera faced", f"{round(d)}° ({_compass(d)})", "Shows which way you were pointing.", "med")
        if G.GPSSpeed in gps and _f(gps[G.GPSSpeed]):
            add("Location", "Speed", f"{round(_f(gps[G.GPSSpeed]))} {_s(gps.get(G.GPSSpeedRef, 'K'))}", "Shows you were moving.", "low")
        add("Location", "Position method", gps.get(G.GPSProcessingMethod), "How the position was found (GPS, Wi-Fi, network).", "low")
        add("Location", "Area name", gps.get(G.GPSAreaInformation), "A named area stored with the photo.", "med")
    for key, label, sev, xk in (("sub", "Place name (street or venue)", "high", "Iptc4xmpCore:Location"),
                                ("city", "City", "med", "photoshop:City"),
                                ("state", "State or region", "med", "photoshop:State"),
                                ("country", "Country", "low", "photoshop:Country")):
        ds = {"sub": 92, "city": 90, "state": 95, "country": 101}[key]
        v, src = ip(ds), "IPTC"
        if not v:
            v, src = _xmp_get(xmp, xk), "XMP"
        add("Location", f"{label} ({src})", v, "A written place name tells people where you were without needing a map.", sev)

    # Device
    make, model = _s(base.get(B.Make)), _s(base.get(B.Model))
    add("Device", "Phone or camera", " ".join(x for x in (make, model) if x) or _xmp_get(xmp, "tiff:Model"),
        "Narrows down which device you own.", "low")
    add("Device", "Lens", " ".join(x for x in (_s(exif.get(B.LensMake)), _s(exif.get(B.LensModel))) if x) or _xmp_get(xmp, "aux:Lens"),
        "Another clue about your equipment.", "low")
    add("Device", "Body serial number", _s(exif.get(B.BodySerialNumber)) or _xmp_get(xmp, "aux:SerialNumber"),
        "Unique to your camera: it links your photos together and can be traced to a purchase.", "med")
    add("Device", "Lens serial number", exif.get(B.LensSerialNumber), "Unique to your lens; links your photos together.", "med")
    add("Device", "Unique image ID", exif.get(B.ImageUniqueID), "Can match this exact picture wherever copies appear.", "med")
    add("Device", "Camera owner name", _s(exif.get(B.CameraOwnerName)) or _xmp_get(xmp, "aux:OwnerName"), "Your name, written by the camera.", "high")
    mn = exif.get(B.MakerNote)
    if mn:
        add("Device", f"Maker note ({len(mn):,} bytes)", "Present", "A vendor block that can hold serial numbers and device settings.", "med")
    add("Device", "Editing software", _s(base.get(B.Software)) or _xmp_get(xmp, "xmp:CreatorTool"), "Which app or device made or edited the picture.", "low")
    add("Device", "Computer", base.get(B.HostComputer), "The name of the device that processed the picture.", "low")
    add("Device", "Document ID", _xmp_get(xmp, "xmpMM:DocumentID") or _xmp_get(xmp, "xmpMM:OriginalDocumentID"), "Links copies and edits of the picture.", "low")
    agents = re.findall(r'stEvt:softwareAgent="([^"]+)"', xmp) + re.findall(r"<stEvt:softwareAgent>([^<]+)<", xmp)
    if agents:
        add("Device", "Editing history", ", ".join(dict.fromkeys(agents)), "The programs the picture passed through.", "low")
    if b"c2pa" in raw[:200000] and b"jumb" in raw[:200000]:
        add("Device", "Content Credentials (C2PA)", "Present", "A signed record of origin and edits; can name who made it.", "low")

    # Time
    off = _s(exif.get(B.OffsetTimeOriginal))
    dto = _s(exif.get(B.DateTimeOriginal))
    if dto:
        add("Time", "Date and time taken", _dt(dto) + (f"  (UTC{off})" if off else ""), "Places you somewhere at an exact time.", "med")
    elif _xmp_get(xmp, "exif:DateTimeOriginal"):
        add("Time", "Date and time taken (XMP)", _xmp_get(xmp, "exif:DateTimeOriginal").replace("T", " "), "Places you somewhere at an exact time.", "med")
    if off and not dto:
        add("Time", "Time zone", off, "Hints at which part of the world you were in.", "low")
    dtd, dtm = _s(exif.get(B.DateTimeDigitized)), _s(base.get(B.DateTime))
    if dtd and dtd != dto:
        add("Time", "Date digitised", _dt(dtd), "When the picture was saved as a file.", "low")
    if dtm and dtm != dto:
        add("Time", "Date last changed", _dt(dtm), "When the file was last edited.", "low")
    if G.GPSTimeStamp in gps:
        try:
            h, mi, se = (_f(x) for x in gps[G.GPSTimeStamp])
            ds = _s(gps.get(G.GPSDateStamp)).replace(":", "-")
            add("Time", "GPS clock (UTC)", f"{ds} {int(h):02d}:{int(mi):02d}:{int(se):02d}".strip(), "Satellite time - exact and can't be faked by hand.", "med")
        except (TypeError, ValueError):
            pass
    if ip(55):
        add("Time", "Date created (IPTC)", ip(55), "When the picture was created.", "med")

    # Embedded preview
    try:
        ifd1 = ex.get_ifd(ExifTags.IFD.IFD1)
    except Exception:  # noqa: BLE001
        ifd1 = {}
    if ifd1:
        tw = th = None
        thumb = None
        try:
            off_ = ifd1.get(0x0201)
            ln = ifd1.get(0x0202)
            exif_raw = im.info.get("exif") or b""
            if off_ and ln and exif_raw:
                tiff = exif_raw[6:] if exif_raw.startswith(b"Exif") else exif_raw
                thumb = tiff[off_:off_ + ln]
                with Image.open(io.BytesIO(thumb)) as t:
                    tw, th = t.size
        except Exception:  # noqa: BLE001
            pass
        if tw and th and R.width and R.height:
            tr, mr = tw / th, R.width / R.height
            if not (abs(tr / mr - 1) < 0.02 or abs(tr * mr - 1) < 0.02):
                add("Embedded preview", "Preview doesn't match the photo", f"preview {tw}×{th}, photo {R.width}×{R.height}",
                    "The photo was probably cropped, but the hidden preview may still show the uncropped original.", "high")
            else:
                add("Embedded preview", "Embedded preview picture", f"{tw}×{th} pixels", "A small copy of the picture is stored in the file.", "low")
        else:
            add("Embedded preview", "Thumbnail in header", "present", "A small copy of the picture is stored in the file.", "low")

    # Other
    add("Other", "Author", _uniq(base.get(B.Artist), base.get(0x9C9D), _xmp_get(xmp, "dc:creator"), ip(80)), "A name that identifies who took it.", "high")
    add("Other", "Copyright", _uniq(base.get(B.Copyright), _xmp_get(xmp, "dc:rights"), ip(116)), "Often contains a real name or website.", "med")
    add("Other", "Credit / source", _uniq(_xmp_get(xmp, "photoshop:Credit"), ip(110), _xmp_get(xmp, "photoshop:Source"), ip(115)),
        "Names the person or organisation behind it.", "med")
    add("Other", "Description", _uniq(base.get(B.ImageDescription), _xmp_get(xmp, "dc:description"), ip(120), base.get(0x9C9F)),
        "Free text that can say who or where.", "med")
    add("Other", "Title", _uniq(_xmp_get(xmp, "dc:title"), ip(5), ip(105), base.get(0x9C9B)), "A title stored with the picture.", "low")
    add("Other", "Comment", _uniq(exif.get(B.UserComment), base.get(0x9C9C), im.info.get("comment")), "Free text the author typed.", "med")
    add("Other", "Keywords / tags", _uniq(base.get(0x9C9E), _xmp_get(xmp, "dc:subject"), ip(25))[:300], "Tags can include names, places or events.", "low")
    faces = re.findall(r'mwg-rs:Name="([^"]+)"', xmp) + re.findall(r"<mwg-rs:Name>([^<]+)<", xmp) + re.findall(r'MPRI:PersonDisplayName="([^"]+)"', xmp)
    if faces:
        add("Other", "Named people (face regions)", ", ".join(dict.fromkeys(faces)), "Photo apps stored the names of recognised people.", "high")
    elif "mwg-rs:Regions" in xmp:
        add("Other", "Face regions (unnamed)", "present", "Where faces are in the picture.", "low")
    add("Other", "People shown", _xmp_get(xmp, "Iptc4xmpExt:PersonInImage"), "Names of people the picture shows.", "high")
    if fmt == "png":
        for k, v in (getattr(im, "text", None) or {}).items():
            if k.lower() in ("xml:com.adobe.xmp",):
                continue
            kl = k.lower()
            sev = "high" if kl == "author" else "med" if re.search(r"prompt|parameters|workflow|comment|description|copyright|creation", kl) else "low"
            add("Other", f"{k} (PNG text)", _s(v)[:300], "Text stored inside the PNG - can include the prompt/settings used to make it.", sev)

    # trailing data after the image
    if fmt == "jpeg":
        R.extra_bytes = max(0, len(raw) - _jpeg_end(raw))
        apps = set()
        for m, s, d, e in _jpeg_segments(raw):
            if 0xE3 <= m <= 0xEF and m not in (0xEE,):
                tag = re.match(rb"[\x20-\x7e]{2,20}", raw[d:d + 20])
                apps.add(f"APP{m - 0xE0}" + (f" {tag.group().decode()}" if tag else ""))
            if m == 0xE2 and raw[d:d + 4] == b"MPF\0":
                apps.add("MPF (multi-picture)")
        if apps:
            add("Other", "Other metadata blocks", ", ".join(sorted(apps)), "Vendor blocks that can hold camera or editing data.", "low")
    elif fmt == "png":
        for t, d in _png_chunks(raw):
            if t == b"__END__":
                R.extra_bytes = max(0, len(raw) - int.from_bytes(d, "big"))
    if R.extra_bytes > 0:
        add("Other", "Extra data after the picture", f"{R.extra_bytes:,} bytes",
            "Hidden data after the image (e.g. a motion-photo video or a second copy).", "med")

    F.sort(key=lambda f: -SEV_RANK[f.sev])
    return R


def clean_copy(rep: Report) -> tuple[Path, bool]:
    """Write <name>-clean.<ext> next to the original. Returns (path, lossless)."""
    raw = rep.path.read_bytes()
    stem = rep.path.stem
    if rep.fmt == "jpeg":
        data, lossless, ext = clean_jpeg(raw, rep.orientation), True, rep.path.suffix or ".jpg"
    elif rep.fmt == "png":
        data, lossless, ext = clean_png(raw, rep.orientation), True, ".png"
    else:
        with Image.open(io.BytesIO(raw)) as im:
            from PIL import ImageOps
            im = ImageOps.exif_transpose(im)
            buf = io.BytesIO()
            fmt = {"mpo": "JPEG"}.get(rep.fmt, rep.fmt.upper())
            if fmt == "WEBP":
                im.save(buf, "WEBP", quality=95)
            elif fmt in ("JPEG",):
                im.convert("RGB").save(buf, "JPEG", quality=95)
            elif fmt in ("GIF", "TIFF", "BMP"):
                im.save(buf, fmt)
            else:
                im.save(buf, "PNG")
                fmt = "PNG"
            data, lossless = buf.getvalue(), False
            ext = "." + {"JPEG": "jpg"}.get(fmt, fmt.lower())
    out = rep.path.with_name(f"{stem}-clean{ext}")
    n = 2
    while out.exists():
        out = rep.path.with_name(f"{stem}-clean-{n}{ext}")
        n += 1
    out.write_bytes(data)
    return out, lossless


def preview_lines(path: Path, cols: int = 48, rows: int = 18):
    # draw the picture as rows of half-block characters
    from PIL import ImageOps
    from rich.text import Text
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        w, h = im.size
        scale = min(cols / w, (rows * 2) / h)
        nw, nh = max(1, int(w * scale)), max(2, int(h * scale) // 2 * 2)
        im = im.resize((nw, nh), Image.LANCZOS)
        px = im.load()
    lines = []
    for y in range(0, nh, 2):
        t = Text()
        for x in range(nw):
            r1, g1, b1 = px[x, y]
            r2, g2, b2 = px[x, y + 1] if y + 1 < nh else (0, 0, 0)
            t.append("▀", style=f"rgb({r1},{g1},{b1}) on rgb({r2},{g2},{b2})")
        lines.append(t)
    return lines
