# Testing with a real Freelap system: step by step

This guide is for one specific kit:

* an **FxChip BLE**;
* a **start cone** and **two timing cones** (three transmitters);
* a **phone with nRF Connect** (and MyFreelap);
* a **Garmin fenix 7 Pro**.

There is no sniffer dongle in that list, so every capture here comes from the
phone. Parts 1–5 need no Garmin code changes at all, and they produce the real
frames everything after them is tested against. Part 6 puts the app on the
fenix 7 Pro. Parts 7–8 are the code and the track session that follow.

The technique behind each step lives in [`TESTING.md`](TESTING.md) and
[`REVERSE-ENGINEERING.md`](REVERSE-ENGINEERING.md); this guide is the order to
do it in with this kit. The rule from `AGENTS.md` still applies: **write the
check before the thing it checks.** Here that means writing down what MyFreelap
shows *before* reading any hex, and committing that as a test.

---

## Read this first: what the watch can do today

| Piece | State |
|---|---|
| Frame decoder (`BroadcastFrame.mc`, `tools/freelap_frame.py`) | Built, mirrored, checked against the vendor's worked example. Never seen a real chip. |
| Rep tracking, course, split engine, FIT recorder | Built and tested end to end with generated frames. |
| **Live BLE path (`FreelapBleDelegate.mc`)** | **Still the old connection-oriented design.** `onScanResults` looks for a chip by name and then tries to *pair*. The chip never accepts a connection, and nothing outside the tests calls the decoder. |

So **a build sideloaded onto the fenix 7 Pro today will launch, but it will not
record a rep from the chip.** Part 6 checks the parts that do work on the watch
now; Part 7 is the code that closes the gap, built against the captures from
Parts 2–5.

---

## Part 1 — Setup (an evening)

### 1.1 Write down the kit

Make a folder for the first session now. It is where everything below goes:

```
captures/<YYYY-MM-DD>-<chipid>-fw<firmware>/
```

- [ ] The **id printed on the chip** (two letters and four digits, e.g.
      `BC-9636`).
- [ ] The chip's **firmware version**, from MyFreelap. The frame specification
      applies from a stated minimum; a capture from an older chip proves less.
- [ ] Which cone is which, and the **mode each is set to**. You need exactly
      one **Finish**: without it the chip never enters lap mode and never
      broadcasts. For a three-cone course: start cone = START, timing cone 1 =
      LAP, timing cone 2 = FINISH.
- [ ] Phone make, model and OS version. Android vs iOS matters (1.3).

### 1.2 Lay out a bench course

A corridor or path is enough. Respect the chip's limits: **at least 10 m (or
0.7 s) between two transmitters**, at most 11 in total.

```
START ---- 15 m ---- LAP ---- 15 m ---- FINISH        course: S:0;L:15;F:30
```

Measure with a tape and write the distances in your notes. The same string
becomes the watch's course in Part 6.

### 1.3 The phone

**Android is strongly preferred.** It can record every packet the phone's
Bluetooth controller receives (the HCI snoop log, Part 3), and nRF Connect for
Android shows the full raw bytes of what it received. On most Android phones
that raw view holds the advertisement and the scan response back to back.

**On iOS**, nRF Connect is still fine for Part 2 (is the chip there, what does
it advertise, does it connect). But iOS gives apps a processed view of
advertising data and has no user-accessible packet log, so it may hide whether
something arrived in the advertisement or the scan response. That difference is
the whole point of #60. If you only have an iPhone, do Part 2 on it and borrow
an Android phone, or buy an nRF52840 Dongle, for Part 3.

On Android, before the first session:

1. Install **nRF Connect for Mobile** and **MyFreelap**. Pair the chip with
   MyFreelap the way its manual says.
2. In nRF Connect's settings, set the scanner to run **continuously**, not for a
   fixed period. If it offers a scan mode, choose **low latency**.
3. Enable **Developer options** (tap *Build number* seven times), then turn on
   **Bluetooth HCI snoop log**. If it offers *Filtered* or *Enabled*, choose
   **Enabled**. Filtered mode can cut payloads short. Toggle Bluetooth off and
   on so the setting takes effect.
4. On your computer: install `adb` (Android platform tools) and **Wireshark**
   (which includes `tshark`), and check `adb devices` sees the phone with USB
   debugging on.

### 1.4 The repository

Get both CI test suites green on your machine before touching hardware, so a
later failure is never caused by the setup:

```bash
pip install pytest fitdecode
python tools/validate_resources.py
python -m pytest tools/tests -q
```

If you hold the confidential worked-example fixture, put it at
`tools/tests/data/vendor_frame_example.json` (git-ignored by name) so the tests
in `tools/tests/test_freelap_frame.py` run rather than skip.

### 1.5 Handling the chip (10 minutes, saves a wasted session)

No button: **hold it vertically and shake it horizontally** to wake it, and the
LED flashes. LED colours: green = START, blue = LAP, red = FINISH. It sleeps
after **30 minutes without a crossing** and loses its stored time. Keep it
**30 cm from the phone** while timing. Shaking also puts it in discoverable mode
for about 10 s and re-sends its last time. More in
[`TESTING.md` § Handling the chip](TESTING.md#handling-the-chip).

---

## Part 2 — Look at the chip live in nRF Connect (30 minutes)

The goal is to see the chip with your own eyes before recording anything. Write
down each answer: they are evidence for #4 and #61.

1. **Wake the chip** by shaking it. Open nRF Connect → *Scanner* → *Scan*.
   Sort by signal strength (RSSI) and bring the chip near the phone. Its row
   will be the one whose RSSI climbs.
2. **Discoverable mode.** Within the 10 s after a shake, note the **device name**
   nRF Connect shows. Does it contain the id printed on the case? Screenshot it.
   This is Run D in the run script.
3. **Expand the row** and note what nRF Connect lists:
   *Manufacturer data* with company **0x0363** (it may say *Freelap* or
   *unknown*), whether it says the device is **connectable**, and the
   advertising interval if shown.
4. **Tap RAW.** Screenshot the hex. With MyFreelap and nRF Connect both
   scanning, Android usually shows the advertisement and scan response
   together here.
5. **Cross the FINISH cone** (walk START → LAP → FINISH). The LED should flash
   red at the finish. Back in nRF Connect, the manufacturer data should now
   change: that is a **lap-mode frame**. Screenshot the RAW view again, and note
   what MyFreelap shows for that rep.
6. **Watch it stop.** Leave the scanner running and time how long the frame
   keeps updating after the finish before the chip goes quiet. That is the
   broadcast window from Run E. #9 needs it.
7. **Try to connect.** Tap *Connect*, if the button is there.
   * The expected answer is that it **refuses** or has no Connect button. The
     chip only broadcasts. Record that: it is the evidence #61 needs to delete
     the app's old pairing code.
   * If it **does** connect, that is a significant surprise. Screenshot every
     service and characteristic, enable notifications on any that allow it, and
     cross the cones again. Then put the whole thing on #4 before doing
     anything else.

Screenshots are evidence, but they are not test input. The next part records
something the tests can read.

---

## Part 3 — Record a capture (per run)

The Android HCI snoop log records every advertising packet the phone's
controller hands up, with timestamps, whichever app asked for the scan. With
MyFreelap and nRF Connect both scanning actively, scan responses are captured
too.

### 3.1 Before each run: write the expectation first

For each run you are about to do (3.4), add an entry to `expected.json` in the
session folder. The times come from **MyFreelap, after the run, before you open
any capture**:

```json
{
  "chip": "BC-9636",
  "firmware": "x.y",
  "phone": "Pixel 7, Android 15",
  "course": "S:0;L:15;F:30",
  "runs": [
    {"run": "B1", "file": "B1.tsv",
     "phone_clock_finish": "10:42:17",
     "legs_s": [3.42, 2.71], "total_s": 6.13,
     "notes": "START + LAP + FINISH, walking"}
  ]
}
```

Times are in seconds to the hundredth, exactly as MyFreelap shows them.
`phone_clock_finish` is the phone's clock when you crossed FINISH, read off the
phone or said into a voice memo. It is how you find the run in a log that holds
the whole session.

### 3.2 Run, then pull the log

1. Make sure the HCI snoop log is on (1.3). Open MyFreelap, then nRF Connect's
   scanner, and leave both running.
2. Do the run. Note the phone time at the finish.
3. When the session is over, pull the log:

   ```bash
   adb bugreport session.zip
   ```

   The log is inside the zip, usually at
   `FS/data/misc/bluetooth/logs/btsnoop_hci.log`. The exact path varies by
   phone, so search the zip for `btsnoop`. One bugreport per session is enough,
   because the log holds every run.

   **Never commit the bugreport.** It is full of personal data. Only the
   filtered TSV from 3.3 goes in the repository.

### 3.3 Export to the repository's capture format

`tools/decode_capture.py` and `tools/fake_chip.py --replay` read one row per
packet: `<epoch>\t<anything>\t<hex payload>`. The payload must **start with the
company id in little-endian, `63 03`**, which is how the decoder recognises the
frame.

```bash
tshark -r btsnoop_hci.log \
  -Y 'btcommon.eir_ad.entry.company_id == 0x0363' \
  -T fields -E separator=/t \
  -e frame.time_epoch \
  -e bthci_evt.le_advts_event_type \
  -e btcommon.eir_ad.entry.data \
| awk -F'\t' '{ print $1 "\t" $2 "\t6303" $3 }' > all.tsv
```

* Column 2 is the packet type, so advertisement and scan-response rows are
  told apart in the file. That matters for #78.
* Wireshark shows the company id as its own field and leaves it out of `data`,
  hence the `6303` the `awk` puts back.
* Field names change between Wireshark versions. If a column comes out empty,
  open the log in Wireshark, click the field you want, *Copy → Field Name*, and
  use that. Check the first few rows by eye against your nRF Connect RAW
  screenshot from Part 2. The hex should be recognisably the same.

Then cut `all.tsv` into one file per run (`B1.tsv`, …) using the finish times
you noted. A few seconds either side is plenty.

**No laptop at the track?** For a handful of reps you can copy the hex out of
nRF Connect's RAW view by hand into a row of the same shape. Use any number for
the time, keep `6303…` at the start, and say in `notes` that it was transcribed
by hand.

### 3.4 The runs, adapted to three cones

From the run script in
[`REVERSE-ENGINEERING.md`](REVERSE-ENGINEERING.md#the-runs-that-still-matter-issue-5).
Walk or jog: speed does not matter yet.

| Run | Do this | Settles |
|---|---|---|
| **A** | START → FINISH, walking past the LAP cone off to the side so it does not fire | the minimum frame, with no intermediates |
| **B** | START → LAP → FINISH, three times with a rest between | intermediates in the scan response, and their order |
| **C** | START → LAP → FINISH, three reps back to back with no rest | whether counters reset per rep: `OFFSET` vs `FROMLAP` (#6) |
| **D** | Shake the chip, no crossing | discoverable mode and the local name (Part 2 step 2) |
| **E** | One rep, then leave the scanner running for 2 minutes | how long the broadcast window lasts (#9) |
| **G** | Walk out of range of the phone mid-rep, finish, come back | whether a missed crossing can be recovered |
| **H** | Run a rep with both apps **closed**, then open them and shake the chip | shake recovery of the last time (#9) |

Run F needs a second chip. Skip it until you can borrow one.

The **mask** question in #6 only shows up after a counter has been running for
a long time. At some point, leave the chip awake for a few hours, crossing a
cone now and then so it does not sleep. Capture a rep at the end and mark it
`"long_running": true`.

---

## Part 4 — Turn the captures into tests

### 4.1 The failing test, first

Add `tools/tests/test_real_captures.py`, parametrised over every
`captures/*/expected.json`. For each run it:

- decodes the run's TSV with `freelap_frame.py`, the same functions
  `decode_capture.py` uses;
- asserts the decoded chip id equals `chip`;
- asserts the total and the final leg, which come from the **advertisement**,
  equal MyFreelap's values after its display rounding (#25 says exact, not
  approximately);
- asserts the intermediate legs, which come from the **scan response**,
  **separately**, so a failure says which half is wrong.

Commit the test together with the first session folder. If the decoder is wrong
about the real chip, the test goes red, which is the point.

```bash
python tools/decode_capture.py captures/<dir>/B1.tsv          # eyeball first
python -m pytest tools/tests/test_real_captures.py -q
```

`decode_capture.py` decodes advertisement rows. Scan-response rows are printed
as hex, and the new test is what decodes them.

### 4.2 Reading the result

| Result | Means | Next |
|---|---|---|
| Green on A–C | The documented layout matches a real chip | Post on #4 and #5, and note it on #6 |
| Total right, intermediates wrong | Scan-response handling is off | `decode_capture.py B1.tsv 3.42 6.13` hunts for where those times really are |
| First rep of C right, later reps wrong | `OFFSET` vs `FROMLAP` (#6) | Fix `freelap_frame.py` **and** `BroadcastFrame.mc` in one commit |
| Off by a hundredth here and there | Rounding (#77) | Compare truncate with round |
| Nothing decodes | Wrong company id or frame type, or old firmware | Check the firmware against the spec's minimum |

### 4.3 Pin the real frames into the Monkey C suite

Once green, generate `source-test/RealCaptureVectors.mc` from the captures. Do
it with a small script, or a `--vectors` option on `fake_chip.py --replay`, and
add a pytest drift guard like `test_scenarios.py` so the vectors cannot go
stale. Then add a `RealCaptureTest.mc` that runs those bytes through
`BroadcastFrame` → `RepTracker` → `SplitEngine` and asserts MyFreelap's
numbers. This is the "vectors taken from real captures" criterion in #7.

Commit the TSVs, `expected.json` and screenshots. **Leave out anything that
identifies the phone**: no bugreport, no phone Bluetooth address. The chip's own
address is fine.

---

## Part 5 — What you know after Parts 2–4

Write it on the issues, including negative results:

- **#4 / #5:** the chip id, firmware, local name, whether it refused a
  connection, and the A–H captures.
- **#6:** the result of Run C, and of the long-running capture when you have it.
- **#9:** how long the broadcast window lasted (Run E), and whether shaking
  recovered a missed rep (Run H).
- **#78 (from the phone's point of view):** whether the advertisement and scan
  response arrived as separate packets. In an HCI log they normally do, as
  separate event types. What *Connect IQ* hands the app is still Part 7's
  question.

---

## Part 6 — The fenix 7 Pro

`fenix7pro` is already a product in `manifest.xml`.

### 6.1 One-time setup

1. Install the Connect IQ SDK with the SDK Manager. Under *Devices*, download
   **fenix 7 Pro**: `monkeyc -d fenix7pro` refuses a product whose definition
   is not installed.
2. Generate a developer key (VS Code: *Monkey C: Generate a Developer Key*).
   Keep it **outside the repository**.

### 6.2 Unit tests on the fenix 7 Pro definition

```bash
connectiq &                                   # start the simulator once
monkeyc -f monkey.jungle -d fenix7pro -l 1 --unit-test \
        -y /path/to/developer_key.der -o bin/freelap-test.prg
monkeydo bin/freelap-test.prg fenix7pro -t     # /t on Windows (monkeydo.bat)
```

The test build only fits on API 5.x devices (TESTING.md §1). The fenix 7 Pro
should qualify. If it reports *"exceeding the limit of 253"* globals, run the
tests on `fenix7` or `fr265` instead. The release build in 6.3 is unaffected.

### 6.3 Build and sideload

```bash
monkeyc -f monkey.jungle -d fenix7pro -l 1 \
        -y /path/to/developer_key.der -o bin/freelap-fenix7pro.prg
```

Connect the watch by USB. On Windows it appears as a portable device (MTP), not
a drive letter. On macOS use an MTP client such as OpenMTP. Copy
`bin/freelap-fenix7pro.prg` into `GARMIN/APPS/`, eject, and **Freelap** appears
in the activity list.

### 6.4 Settings for a sideloaded build

Settings for a sideloaded app often do not show up in Garmin Connect. For the
test build, set the defaults in `resources/settings/properties.xml` and
rebuild. **Do not commit this change.**

```xml
<property id="chipId" type="string">BC-9636</property>       <!-- your printed id -->
<property id="course1" type="string">S:0;L:15;F:30</property> <!-- your bench course -->
<property id="captureMode" type="boolean">true</property>
```

### 6.5 What to check on the watch today

- [ ] The app launches, and the screen shows the chip id and the course you set.
- [ ] With `chipId` empty, it says it will not record. That is the intended
      refusal (#63).
- [ ] START / BACK / pause / save behave as the README's *First run* describes,
      and an empty session saves or discards without crashing.
- [ ] Note the battery percentage before and after 30 minutes with the app
      open. That is a first baseline for #9.

Crossing the cones will **not** produce a rep yet (see *Read this first*). If it
somehow does, record exactly what happened on #60, because it would mean the
old path is doing something nobody expects.

---

## Part 7 — The code that makes the watch hear the chip

Every step is test-first, ring 3 (Monkey C unit tests) before any radio. The
captures from Part 3 are the test data.

1. **A probe, for #60.** Write a pure `ScanProbe.describe(mfgEntries, rawLength,
   name)` that turns what one `ScanResult` exposes into a log line: how many
   manufacturer entries for `0x0363`, their lengths, the `getRawData()` length,
   and whether a name is present. Test it with byte arrays for three shapes:
   advertisement only, both halves merged, and scan response alone. Then call
   it from `onScanResults` for **every** `0x0363` result when `captureMode` is
   on, *before* the name filter. Sideload it to the fenix 7 Pro, cross the
   cones, and dump the capture log from the idle menu. Post the answer on #60 as
   YES / NO / PARTIAL. It decides what the product is:

   | fenix 7 Pro sees | Then the app records |
   |---|---|
   | Two entries in one result | every split, as designed |
   | Separate results | depends on pairing them safely (#78) |
   | Advertisement only | rep total and final leg only. Correct README, site and store listing before any release |

2. **A `BroadcastIntake`.** Behind a thin adapter that pulls `(manufacturer
   entries, arrivalMs)` out of each `ScanResult`, add a pure intake that feeds
   `BroadcastFrame` → `RepTracker` → `SplitEngine.onRepBurst`. Write the red
   tests first, using the real vectors from 4.3: a real rep gives MyFreelap's
   legs; forty repeats give one rep; an unbound chip gives nothing; a gap in
   the lap number is shown as a missed rep; a scan response with no matching
   advertisement is dropped.
3. **Continuous scanning** from session start to end, including while paused
   (#9).
4. **Delete the pairing path** (#61): pair, subscribe, handshake,
   `FreelapProtocol.mc`, `PacketAssembler.mc`, and `ProtocolVectorTest.mc`'s
   vectors. Part 2 step 7 is your evidence that it can go.
5. **Fix #85 and #86** before taking real data. #85 is the overlay that can
   exit the app; #86 is the duplicated finish record and closing lap in the
   FIT.

Then repeat the Part 3 bench runs **on the watch** with MyFreelap alongside:

- [ ] five reps give five laps;
- [ ] `python tools/fit_splits.py activity.fit` matches MyFreelap to the
      hundredth;
- [ ] a rep finished out of range and recovered by shaking appears once;
- [ ] a rep finished just before a pause is kept.

---

## Part 8 — Track validation (#25)

Before the session, write `tools/compare_session.py` test-first, against
`tools/tests/data/reference-session.fit` and a small hand-written MyFreelap
fixture. It takes the `.fit` and a `myfreelap.csv` (rep, leg, seconds) and
writes `captures/<date>/validation.md`:

| rep | leg | MyFreelap | watch `fl_split_us` | Δ | Garmin lap time | GPS lap distance |
|---|---|---|---|---|---|---|

The header gives the reps each source saw, missing and extra reps, the largest
\|Δ\| and battery at start and end.

**The session:** three cones (e.g. `S:0;L:30;F:60` on a straight), 20 reps,
MyFreelap running the whole time, at least one pause, one rep finished out of
the watch's range and recovered by shaking, and battery noted at start and end.

**Afterwards:**

1. Export the original `.FIT` from Garmin Connect.
2. Run `compare_session.py`.
3. Every Δ must be zero after MyFreelap's rounding. Any difference is a bug to
   track down, not noise.

Garmin's lap time and GPS distance are context, not pass/fail. The watch's lap
trails the beam by about the broadcast latency (`bleLatencyMs`, 150 ms by
default), and GPS distance scatters by a few metres. Record the typical gap:
#68 needs it.

When it passes, update the status wording in `README.md`, `site/index.html`
and `docs/store/` in the same PR. "Nothing here has been run against a real
Freelap chip" stops being true.

---

## Checklist

```
Part 1  [ ] chip id, firmware, cone modes noted   [ ] HCI snoop log on   [ ] pytest green
Part 2  [ ] name in discoverable mode              [ ] lap-mode RAW hex
        [ ] broadcast window timed                 [ ] connect attempt recorded
Part 3  [ ] expected.json written before the hex  [ ] runs A B C D E G H captured
        [ ] all.tsv exported and split per run
Part 4  [ ] test_real_captures.py red -> green     [ ] real vectors in Monkey C
Part 5  [ ] results posted on #4 #5 #6 #9
Part 6  [ ] fenix7pro tests run                    [ ] sideloaded, launches, settings shown
Part 7  [ ] #60 answered on the fenix 7 Pro        [ ] BroadcastIntake green
        [ ] pairing path deleted                   [ ] #85 #86 fixed   [ ] 5 bench reps match
Part 8  [ ] compare_session.py tested              [ ] 20 reps, all Δ = 0
```

Record where every result came from (phone model, nRF Connect, fenix 7 Pro
firmware). A negative result, written down carefully, is worth as much as a
positive one.
