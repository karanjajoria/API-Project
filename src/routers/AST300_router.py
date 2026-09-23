"""
Capture from the ACPL Capture API and decode the WSQ fingerprint image in one run.
No copy-pasting base64 anywhere - everything happens in-process.

    pip install requests urllib3 pillow wsq
    python capture_and_decode.py

Why this doesn't parse the ISO/IEC 19794-4 FIR header field-by-field: a real
capture came back as version b"010\\x00", and its header layout genuinely
differs from the b"020\\x00" layout documented in the standard's own reference
library - not just the version string, actual field offsets shift. Rather than
keep guessing at a vendor-specific variant, this instead searches for WSQ's own
Start-of-Image marker (0xFFA0), which is self-delimiting: everything from that
marker to the end of the record is a complete, standalone WSQ bitstream, which
the `wsq` library (IDEMIA's Pillow plugin over NIST's own WSQ codec) decodes
directly - regardless of how the FIR header around it is laid out.
"""
import base64
import io
import json
from pathlib import Path
from datetime import datetime

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)  # self-signed cert
parent = "data"

RELEASE_URL = "https://localhost:11200/rd/releasefm220"
CAPTURE_URL = "https://localhost:4443/FM220/gettmpl"
WSQ_SOI_MARKER = b"\xff\xa0"

current_time = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

def extract_wsq(fir_record: bytes) -> bytes:
    """Find the WSQ Start-of-Image marker after the 16-byte FIR general header
    and return everything from there to the end - a complete WSQ bitstream."""
    idx = fir_record.find(WSQ_SOI_MARKER, 16)
    if idx == -1:
        raise ValueError(
            "No WSQ start marker (0xFFA0) found - this capture may not be WSQ-"
            "compressed. Share last_capture.json and I'll check what it actually is."
        )
    return fir_record[idx:]


def main() -> None:
    try:
        r = requests.request("RELEASEFM220", RELEASE_URL, verify=False, timeout=5)
        print(f"Release: HTTP {r.status_code}")
    except requests.RequestException as exc:
        print(f"Release skipped/failed (may be fine): {exc}")

    print("Place your finger on the sensor now...")
    r = requests.get(CAPTURE_URL, verify=False, timeout=15)
    r.raise_for_status()
    result = r.json()

    # Save the FULL response to disk - this is the reliable way to inspect any
    # field in full, instead of copy-pasting a 10,000-character string by hand.
    Path(f"{current_time}.json").write_text(json.dumps(result, indent=2))
    print("Full response saved to last_capture.json")

    if result.get("errorCode") != 0:
        print(f"errorCode = {result.get('errorCode')} (status: {result.get('status')}) - "
              f"capture failed, nothing to decode.")
        return

    iso_b64 = result.get("isoImgBase64", "")
    if not iso_b64:
        print("isoImgBase64 is empty in this response - nothing to decode.")
        return

    fir_record = base64.b64decode(iso_b64)
    if fir_record[:4] != b"FIR\x00":
        print(f"Expected a FIR image record, got bytes starting with {fir_record[:4]!r} "
              f"instead - wrong field? (FMR\\x00 means the minutiae template, not the image)")
        return

    wsq_bytes = extract_wsq(fir_record)
    Path("captured_finger.wsq").write_bytes(wsq_bytes)
    print(f"Extracted {len(wsq_bytes)} bytes of WSQ data -> captured_finger.wsq")

    try:
        import wsq  # noqa: F401  (registers the WSQ format with Pillow on import)
        from PIL import Image
        img = Image.open(io.BytesIO(wsq_bytes))
        img.save(f"{current_time}.png")
        print(f"Decoded: {img.size[0]}x{img.size[1]}, mode {img.mode} -> captured_finger.png")
    except ImportError:
        print("The 'wsq' package isn't installed - run: pip install wsq")
    except Exception as exc:  # noqa: BLE001
        print(f"wsq decoded the bytes but something went wrong: {exc}")
        print("captured_finger.wsq is still saved - share it and I'll investigate directly.")


if __name__ == "__main__":
    main()