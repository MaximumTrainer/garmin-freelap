"""Ring 4b: turning what a phone or laptop sees into the capture TSV.

The two capture routes that need no Android developer mode both end in the
same place - `<epoch>\\t<label>\\t<hex>` rows whose payload starts with the
company identifier, which is what `decode_capture.py` and
`fake_chip.py --replay` read. Everything tested here is pure; the radio part
of `ble_capture.py` (bleak) is not imported by these tests.
"""
import freelap_frame as ff
from ble_capture import (ad_structures, freelap_payloads, live_rows,
                         parse_hex, parse_time, rows_from_raw_notes)
from decode_capture import read_rows

ADV = ff.build_advertisement("BC", 9636, 3, 1000, 1000, 7300)
RSP = ff.build_scan_response([3100, 5200])


def ad(ad_type, data):
    return bytes([len(data) + 1, ad_type]) + bytes(data)


FLAGS = ad(0x01, [0x06])
NAME = ad(0x09, b"BC-9636")


# ---- AD structures -------------------------------------------------------

def test_ad_structures_splits_a_scan_record_into_type_and_data():
    raw = FLAGS + ad(0xFF, ADV)

    assert ad_structures(raw) == [(0x01, b"\x06"), (0xFF, ADV)]


def test_ad_structures_stops_at_zero_padding():
    # Android pads a legacy scan record to 62 bytes with zeros.
    raw = FLAGS + ad(0xFF, ADV) + bytes(20)

    assert ad_structures(raw) == [(0x01, b"\x06"), (0xFF, ADV)]


def test_ad_structures_drops_a_truncated_last_structure_rather_than_guessing():
    raw = FLAGS + bytes([0x1B, 0xFF, 0x63, 0x03])

    assert ad_structures(raw) == [(0x01, b"\x06")]


# ---- picking out Freelap's entries ---------------------------------------

def test_both_halves_back_to_back_give_two_payloads_in_order():
    # What nRF Connect's RAW view holds on most Android phones: the
    # advertisement, then the scan response.
    raw = FLAGS + ad(0xFF, ADV) + ad(0xFF, RSP)

    assert freelap_payloads(raw) == [ADV, RSP]


def test_payloads_keep_the_company_id_so_the_decoder_recognises_them():
    payload = freelap_payloads(FLAGS + ad(0xFF, ADV))[0]

    assert payload[:2] == bytes([0x63, 0x03])
    assert ff.decode_advertisement(payload).chip == "BC-9636"


def test_another_companys_manufacturer_data_is_ignored():
    stranger = ad(0xFF, [0x4C, 0x00, 0x02, 0x15, 0x01])

    assert freelap_payloads(FLAGS + stranger + NAME) == []


# ---- reading what was copied out of nRF Connect --------------------------

def test_parse_hex_accepts_the_shapes_a_copy_paste_produces():
    assert parse_hex("0x0201060AFF") == bytes([2, 1, 6, 0x0A, 0xFF])
    assert parse_hex("02 01 06") == bytes([2, 1, 6])
    assert parse_hex("02:01:06") == bytes([2, 1, 6])
    assert parse_hex("02-01-06") == bytes([2, 1, 6])


def test_parse_time_takes_epoch_seconds_or_a_clock_time():
    assert parse_time("1763140937.25") == 1763140937.25
    assert parse_time("10:42:17") == 10 * 3600 + 42 * 60 + 17
    assert parse_time("10:42:17.5") == 10 * 3600 + 42 * 60 + 17.5
    assert parse_time("rep") is None


def test_a_notes_line_becomes_one_row_per_freelap_entry():
    raw = (FLAGS + ad(0xFF, ADV) + ad(0xFF, RSP)).hex().upper()
    lines = ["10:42:17\tB1\t0x" + raw + "\n"]

    rows = rows_from_raw_notes(lines)

    assert len(rows) == 2
    assert rows[0].split("\t")[0] == "38537.000"
    assert rows[0].split("\t")[1] == "B1 1/2"
    assert rows[1].split("\t")[1] == "B1 2/2"


def test_rows_from_notes_read_back_through_decode_capture():
    raw = (FLAGS + ad(0xFF, ADV) + ad(0xFF, RSP)).hex()
    rows = rows_from_raw_notes(["10:42:17 B1 " + raw])

    read = read_rows(rows)

    assert [data for _, data in read] == [ADV, RSP]


def test_a_label_may_be_left_out_and_spaces_inside_the_hex_are_fine():
    raw = " ".join("%02X" % b for b in FLAGS + ad(0xFF, ADV))

    rows = rows_from_raw_notes(["10:42:17 " + raw])

    assert len(rows) == 1
    assert read_rows(rows)[0][1] == ADV


def test_notes_lines_without_a_freelap_entry_or_a_time_are_skipped():
    lines = [
        "# session notes\n",
        "\n",
        "10:40:00 warm-up " + (FLAGS + NAME).hex() + "\n",
        "no time here " + (FLAGS + ad(0xFF, ADV)).hex() + "\n",
    ]

    assert rows_from_raw_notes(lines) == []


# ---- the laptop route ----------------------------------------------------

def test_live_rows_restore_the_company_id_that_bleak_strips():
    # bleak hands manufacturer data as {company_id: bytes after the id}.
    mfg = {0x0363: ADV[2:], 0x004C: b"\x02\x15"}

    rows = live_rows(1763140937.5, "AA:BB adv", mfg)

    assert rows == ["1763140937.500\tAA:BB adv\t" + ADV.hex()]


def test_live_rows_ignore_a_result_with_no_freelap_entry():
    assert live_rows(1.0, "x", {0x004C: b"\x02\x15"}) == []


def test_tab_separated_lines_split_on_tabs_even_with_a_hex_looking_label():
    raw = (FLAGS + ad(0xFF, ADV)).hex()

    rows = rows_from_raw_notes(["10:42:17\tAB\t" + raw])

    assert rows[0].split("\t")[1] == "AB 1/1"


def test_spaced_bytes_after_a_word_label():
    raw = " ".join("%02x" % b for b in FLAGS + ad(0xFF, ADV))

    rows = rows_from_raw_notes(["10:42:17 rep three " + raw])

    assert rows[0].split("\t")[1] == "rep three 1/1"
    assert read_rows(rows)[0][1] == ADV


def test_the_command_line_raw_mode_prints_rows(tmp_path, capsys):
    from ble_capture import main
    notes = tmp_path / "notes.txt"
    notes.write_text("10:42:17 B1 0x" + (FLAGS + ad(0xFF, ADV)).hex() + "\n")

    assert main(["raw", str(notes)]) == 0

    assert capsys.readouterr().out.strip().endswith(ADV.hex())


def test_describe_names_each_half_for_the_console():
    from ble_capture import describe

    assert describe(ADV).startswith("advertisement BC-9636 lap#3")
    assert describe(RSP) == "scan response, 2 intermediate(s)"
