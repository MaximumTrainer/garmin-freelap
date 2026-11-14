#!/usr/bin/env python3
"""Capture an FxChip's broadcasts without Android developer mode.

Two routes, both ending in the capture TSV that `decode_capture.py` and
`fake_chip.py --replay` read - one row per Freelap manufacturer entry,

    <epoch>\t<label>\t<hex payload, company id 63 03 first>

**From nRF Connect (a phone, no laptop at the track).** After each rep, open
the chip's RAW view in nRF Connect, copy the hex, and paste it into a notes
file as one line per rep:

    10:42:17  B1  0x0201061BFF6303...

The time is the phone's clock (or epoch seconds), the label is optional, and
the hex is the whole raw record as nRF Connect shows it. On most Android phones
that record holds the advertisement and the scan response back to back, so a
line can produce two rows: `B1 1/2`, `B1 2/2`. Then

    ble_capture.py raw notes.txt > captures/<dir>/B1.tsv

**Live, from a laptop's own Bluetooth (continuous).**

    pip install bleak
    ble_capture.py live --out captures/<dir>/session.tsv [--seconds 600]

Scans actively, writes every callback carrying Freelap's company id, and prints
a line whenever a new frame decodes. The label column holds the chip's address,
its local name if one has been seen, and the packet type where the operating
system exposes it. Limitation: bleak hands over one manufacturer entry per
company per callback, so where the advertisement and scan response are merged
by the OS only one may survive. The nRF Connect RAW route keeps both, which is
why that route is the one #60 and #78 should quote.
"""
import argparse
import re
import sys
import time

import freelap_frame as ff

AD_MANUFACTURER = 0xFF
COMPANY_LE = bytes([ff.COMPANY_ID & 0xFF, (ff.COMPANY_ID >> 8) & 0xFF])

_HEX_TOKEN = re.compile(r"^(0x)?[0-9a-fA-F]+$")
_CLOCK = re.compile(r"^(\d{1,2}):(\d{2}):(\d{2}(?:\.\d+)?)$")


# ---- pure ------------------------------------------------------------------

def ad_structures(raw):
    """A raw advertising record -> [(ad_type, data), ...].

    Stops at a zero length byte (padding) and drops a structure that runs off
    the end, rather than reading garbage as data.
    """
    out = []
    i = 0
    while i < len(raw):
        length = raw[i]
        if length == 0:
            break
        end = i + 1 + length
        if end > len(raw):
            break
        out.append((raw[i + 1], bytes(raw[i + 2:end])))
        i = end
    return out


def freelap_payloads(raw):
    """Every Freelap manufacturer entry in a raw record, company id included."""
    return [data for ad_type, data in ad_structures(raw)
            if ad_type == AD_MANUFACTURER and data[:2] == COMPANY_LE]


def parse_hex(text):
    """Hex as a copy-paste produces it: 0x prefix, spaces, colons or dashes."""
    text = text.strip()
    if text[:2].lower() == "0x":
        text = text[2:]
    return bytes.fromhex(re.sub(r"[\s:\-]", "", text))


def parse_time(token):
    """Epoch seconds, or a clock time HH:MM:SS[.f] as seconds since midnight.

    Only differences between rows are ever used, so seconds since midnight is
    as good as an epoch within one session. None if it is neither.
    """
    match = _CLOCK.match(token)
    if match:
        h, m, s = match.groups()
        return int(h) * 3600 + int(m) * 60 + float(s)
    try:
        return float(token)
    except ValueError:
        return None


def format_row(when, label, payload):
    return "%.3f\t%s\t%s" % (when, label, payload.hex())


def _split_notes_line(line):
    """`<time> [label] <hex>` -> (seconds, label, hex text), or None.

    Where the label ends and the hex begins, in order of preference: tabs if
    the line has them; a token starting `0x`, which is how nRF Connect shows
    raw data; otherwise the last token, if it is one long run of hex; and
    failing that the trailing run of two-character byte tokens ("02 01 06"),
    in which case a label must not itself look like a byte.
    """
    line = line.strip()
    if not line:
        return None
    if "\t" in line:
        fields = [f.strip() for f in line.split("\t")]
        if len(fields) < 2:
            return None
        when = parse_time(fields[0])
        return None if when is None else (when, " ".join(fields[1:-1]), fields[-1])
    tokens = line.split()
    when = parse_time(tokens[0])
    if when is None or len(tokens) < 2:
        return None
    rest = tokens[1:]
    for i, token in enumerate(rest):
        if token[:2].lower() == "0x":
            return when, " ".join(rest[:i]), "".join(rest[i:])
    if len(rest[-1]) > 2:
        return when, " ".join(rest[:-1]), rest[-1]
    start = len(rest)
    while start > 0 and len(rest[start - 1]) == 2 and _HEX_TOKEN.match(rest[start - 1]):
        start -= 1
    return when, " ".join(rest[:start]), "".join(rest[start:])


def rows_from_raw_notes(lines):
    """Lines of `<time> [label] <raw hex>` -> capture TSV rows.

    A line with no recognisable time, or no Freelap entry, is skipped: notes
    taken at a track have headings and asides in them.
    """
    rows = []
    for line in lines:
        split = _split_notes_line(line)
        if split is None:
            continue
        when, label, hex_text = split
        try:
            raw = parse_hex(hex_text)
        except ValueError:
            continue
        payloads = freelap_payloads(raw)
        for n, payload in enumerate(payloads, 1):
            rows.append(format_row(when, "%s %d/%d" % (label or "nrfconnect", n,
                                                       len(payloads)),
                                   payload))
    return rows


def live_rows(when, label, manufacturer_data):
    """One bleak callback's {company_id: data} -> capture rows for Freelap."""
    data = manufacturer_data.get(ff.COMPANY_ID)
    if data is None:
        return []
    return [format_row(when, label, COMPANY_LE + bytes(data))]


def describe(payload):
    """A one-line summary for the console, or None if it does not decode."""
    adv = ff.decode_advertisement(payload)
    if adv is not None:
        return "advertisement %s lap#%d split=%s" % (
            adv.chip, adv.lap_number,
            ff.format_time(ff.to_centiseconds(adv.split())))
    laps = ff.decode_scan_response(payload)
    if laps:
        return "scan response, %d intermediate(s)" % len(laps)
    return None


# ---- the radio -------------------------------------------------------------

def _packet_type(advertisement_data):
    """The advertisement/scan-response distinction, where the OS exposes it.

    Only WinRT does, through bleak's platform data. Elsewhere this is blank
    and the row cannot say which half it came from.
    """
    platform = getattr(advertisement_data, "platform_data", None) or ()
    for item in platform:
        kind = getattr(item, "advertisement_type", None)
        if kind is not None:
            return str(kind).rsplit(".", 1)[-1]
    return ""


def run_live(out_path, seconds):
    try:
        import asyncio
        from bleak import BleakScanner
    except ImportError:
        print("live capture needs bleak: pip install bleak", file=sys.stderr)
        return 2

    seen = set()
    names = {}

    def on_result(device, advertisement_data):
        if advertisement_data.local_name:
            names[device.address] = advertisement_data.local_name
        label = " ".join(x for x in (device.address,
                                     names.get(device.address, ""),
                                     _packet_type(advertisement_data)) if x)
        rows = live_rows(time.time(), label,
                         advertisement_data.manufacturer_data)
        for row in rows:
            out.write(row + "\n")
            out.flush()
            payload = bytes.fromhex(row.rsplit("\t", 1)[1])
            if payload not in seen:
                seen.add(payload)
                print("%s  %s" % (time.strftime("%H:%M:%S"),
                                  describe(payload) or payload.hex()))

    async def scan():
        scanner = BleakScanner(on_result, scanning_mode="active")
        await scanner.start()
        try:
            if seconds:
                await asyncio.sleep(seconds)
            else:
                while True:
                    await asyncio.sleep(3600)
        finally:
            await scanner.stop()

    with open(out_path, "a", encoding="utf-8") as out:
        print("scanning; wake the chip and cross FINISH. Ctrl+C to stop.")
        try:
            asyncio.run(scan())
        except KeyboardInterrupt:
            pass
    print("%d distinct Freelap frame(s) written to %s" % (len(seen), out_path))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    raw = sub.add_parser("raw", help="nRF Connect RAW hex pasted into a notes file")
    raw.add_argument("notes", help="the notes file, or - for stdin")
    live = sub.add_parser("live", help="scan with this computer's Bluetooth")
    live.add_argument("--out", required=True, help="TSV to append to")
    live.add_argument("--seconds", type=float, default=0,
                      help="stop after this long (default: until Ctrl+C)")
    args = parser.parse_args(argv)

    if args.mode == "live":
        return run_live(args.out, args.seconds)
    handle = sys.stdin if args.notes == "-" else open(args.notes, encoding="utf-8")
    with handle:
        for row in rows_from_raw_notes(handle):
            print(row)
    return 0


if __name__ == "__main__":
    sys.exit(main())
