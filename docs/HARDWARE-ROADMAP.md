# You have a Freelap system: what to do next

A sequenced, test-first plan for getting this app from "built against generated
frames" to "validated on a track against MyFreelap", now that a real FxChip BLE
and transmitters are on hand.

This document is the **order of work**. The *how* of each technique already
lives elsewhere and is linked rather than repeated:
[`TESTING.md`](TESTING.md) (simulator, nRF52 radio, sideloading),
[`REVERSE-ENGINEERING.md`](REVERSE-ENGINEERING.md) (the run script A–H and the
open protocol questions), [`EXPORT.md`](EXPORT.md) (getting numbers out of a
FIT file).

The same rule as everywhere in this repo applies (`AGENTS.md`): **write the
check before the thing it checks.** For hardware work that means writing down
what MyFreelap says *before* asking whether our decoder agrees, and committing a
failing test that holds those numbers before touching the decoder.

---

## Where things actually stand

Read this before planning a track day, because one gap is easy to miss.

| Piece | State |
|---|---|
| Frame decoder (`BroadcastFrame.mc`, `freelap_frame.py`) | Built, mirrored, checked against the vendor's worked example. Never seen a real chip. |
| Rep tracking (`RepTracker.mc`) | Built and tested: repeats, strangers' chips, missed-rep gaps. |
| Course, split engine, FIT recorder | Built; scenario suite drives them end to end in the simulator. |
| **Live BLE path (`FreelapBleDelegate.mc`)** | **Still the old connection-oriented design.** `onScanResults` looks for a chip by name and then tries to *pair* with it. The chip never accepts a connection, and nothing in `source/` outside tests calls `BroadcastFrame` or `RepTracker`. |

So **today, a sideloaded build will not record a rep from a real chip**, however
good the decoder is. The decoder and tracker have to be wired into
`onScanResults` (Phase 3) before an on-watch session can produce anything.
Phases 1 and 2 do not need that, and they produce the evidence Phase 3 should
be built against, so do them first.

---

## Phase 0 — Kit and setup (an evening)

**Inventory.** Write these down once; most of them go into every capture folder.

- [ ] FxChip BLE: the **id printed on the case** (two letters, four digits,
      e.g. `BC-9636`) and its **firmware version** (MyFreelap shows it). The
      frame specification applies from a stated minimum firmware; a capture
      from an older chip proves less than it seems.
- [ ] Transmitters: how many, and confirm at least one can be set to
      **Finish**. Without a Finish the chip never enters lap mode and never
      broadcasts, and nothing below happens.
- [ ] MyFreelap on a phone, logged in, showing the chip. This is the source of
      truth for every time in this plan.
- [ ] Your Garmin watch model, so you build with the right `-d` product id.
- [ ] A capture route for raw advertisements (Phase 1). Cheapest first:
      an **nRF52840 Dongle** (doubles as the simulator's radio in Phase 2 and
      as a sniffer here), or a Linux laptop with `btmon`, or nRF Connect on a
      phone for eyeballing.
- [ ] A tape measure, and a short stretch of flat ground indoors or outdoors
      for bench runs (a corridor works).

**Toolchain.** Get both CI rings green on your machine before touching
hardware, so a later failure is never "the setup".

```bash
python tools/validate_resources.py
python -m pytest tools/tests -q
# then the Monkey C ring, per TESTING.md §1:
monkeyc -f monkey.jungle -d fr265 -l 1 --unit-test -y <key.der> -o bin/freelap-test.prg
monkeydo bin/freelap-test.prg fr265 -t            # /t on Windows
```

If you hold the confidential worked-example fixture, put it at
`tools/tests/data/vendor_frame_example.json` (git-ignored by name) so the tests
in `tools/tests/test_freelap_frame.py` run rather than skip. That is the only external anchor the decoder
has until Phase 1 adds a second one.

**Learn the chip** (10 minutes, saves a wasted session): no button, wake it by
shaking; LED green = START, blue = LAP, red = FINISH; it sleeps after 30 min
without a crossing and loses its time; keep it 30 cm from any receiver; at most
11 transmitters, at least 10 m or 0.7 s apart. Details in
[`TESTING.md` § Handling the chip](TESTING.md#handling-the-chip).

---

## Phase 1 — Capture the chip off the air, no Garmin involved (half a day)

**Goal:** real frames, paired with the times MyFreelap showed for them,
committed as a test. Settles #4, #5, and the two ambiguities in #6. Nothing
here depends on Connect IQ.

### 1.1 Write the expectation first

For each run in the script (A–H in
[`REVERSE-ENGINEERING.md`](REVERSE-ENGINEERING.md#the-runs-that-still-matter-issue-5)),
create `captures/<YYYY-MM-DD>-<chipid>-fw<version>/` and, **before looking at
any hex**, record what MyFreelap displays in `expected.json`:

```json
{
  "chip": "BC-9636",
  "firmware": "x.y",
  "course": "S:0;L:30;L:60;F:100",
  "runs": [
    {"run": "B1", "file": "adv.tsv",
     "legs_s": [3.42, 2.71, 4.05], "total_s": 10.18,
     "notes": "Start + 2 LAP + Finish, jogging"}
  ]
}
```

Seconds to the hundredth, exactly as MyFreelap shows them. Note anything odd in
`notes` (LED colour that surprised you, a crossing that did not flash).

### 1.2 Add the failing test

New `tools/tests/test_real_captures.py`, parametrised over every
`captures/*/expected.json`:

- decode each run's capture with `decode_capture.py`'s functions;
- assert the decoded chip id equals `chip` (identity is printed on the case,
  carried in the frame, and in the local name: all three must agree);
- assert every leg and the total equal MyFreelap's values **after MyFreelap's
  display rounding** (#25 says exact, not approximate);
- assert advertisement-derived values (total, final leg) and scan-response
  values (intermediate legs) **separately**, so a failure says which half is
  wrong.

Commit the test with the first `expected.json` and its capture. It is meant to
go red if the decoder is wrong; that is the point of the exercise.

### 1.3 Capture

- **Sniffer route (best):** nRF52840 Dongle + *nRF Sniffer for Bluetooth LE* in
  Wireshark. A sniffer sees both the advertisement and the scan response,
  provided *something* is actively scanning the chip, so keep MyFreelap open on
  the phone. Export with `tshark` as `<epoch>\t<address>\t<hex>`:

  ```bash
  tshark -r run-b1.pcapng -Y "btcommon.eir_ad.entry.company_id == 0x0363" \
         -T fields -e frame.time_epoch -e btle.advertising_address \
         -e btcommon.eir_ad.entry.data > adv.tsv
  ```

  Field names differ between Wireshark versions; if a column comes out empty,
  click the manufacturer-data field in Wireshark, *Copy → Field Name*, and use
  that.
- **Linux route:** `btmon -w run-b1.btsnoop` while `bluetoothctl scan on`
  (active scan), then the same `tshark` export on the btsnoop file.
- **nRF Connect on a phone:** fine for confirming the chip is advertising at
  all and for reading the hex by eye; its log export is not in the TSV shape,
  so you would convert it by hand. Use it for Run D (the local name) and as a
  sanity check, not as the main capture.

Then `python tools/decode_capture.py captures/<dir>/adv.tsv` and run the new
test.

### 1.4 What each result means

| Test result | Means | Next |
|---|---|---|
| Green on runs A–C | Layout confirmed against a real chip | Close #4/#5; note it on #6 |
| Total right, intermediates wrong | Scan-response handling is off | `decode_capture.py adv.tsv <times>` to hunt where the times really are |
| Run C's second/third rep wrong, first right | `OFFSET` vs `FROMLAP` (#6) | Fix in `freelap_frame.py` **and** `BroadcastFrame.mc` in one commit |
| Everything off by a small constant | Origin or rounding | Compare truncate vs round; see #77 |
| Nothing decodes | Wrong company/frame type, or old firmware | Check firmware against the spec's minimum |

The *mask* question in #6 only shows itself once a counter's high bits are set,
so leave the chip awake and crossing occasionally for a long session (hours) at
some point and capture a rep at the end. Mark that run `"long_running": true`.

### 1.5 Pin the real frames into the Monkey C suite

Once the Python test is green, the same frames should drive the watch's
decoder. Add a small generator (or a `--vectors` option on
`fake_chip.py --replay`) that turns `captures/*/adv.tsv` + `expected.json` into
`source-test/RealCaptureVectors.mc`, plus a drift guard in pytest like the one
`test_scenarios.py` uses. Then a `RealCaptureTest.mc` that runs those bytes
through `BroadcastFrame` → `RepTracker` → `SplitEngine` and asserts MyFreelap's
numbers. This is #7's "vectors taken from real captures" criterion.

Never commit anything that identifies a phone. The chip's own address is fine.

---

## Phase 2 — What can a Connect IQ app actually hear? (a few hours)

**Goal:** answer #60 (is the scan response visible at all?) and #78 (if so, in
the same `ScanResult` or a separate one?). This decides whether the product
records a split at every transmitter or only a rep total, so it gates Phase 3's
design.

### 2.1 Test first: a pure probe

Add a small pure function, e.g. `ScanProbe.describe(mfgEntries, rawLength,
name)`, that turns what one `ScanResult` exposes into a single log line:
number of manufacturer entries for company `0x0363`, each entry's length,
`getRawData()` length, whether a device name is present. Ring-3 tests feed it
byte arrays for the three shapes that matter: one entry (advertisement only),
two entries (merged), a scan response alone. Green before any BLE code.

### 2.2 Wire it, behind capture mode

In `onScanResults`, when `captureMode` is on, log `ScanProbe.describe(...)` for
**every** result carrying company `0x0363`, before any name filter. (Today the
loop filters by name first, which would hide exactly what we need to see.) The
wiring itself is BLE-stack behaviour and is verified by the manual step below,
as `AGENTS.md` allows; say so in the PR.

### 2.3 Run it in two places, and label which

1. **Simulator + nRF52840 Dongle** —
   [`TESTING.md` §3](TESTING.md#3-the-simulator-with-a-real-radio--an-nrf52-board).
   Quick to iterate; not evidence about a watch.
2. **Your watch**, sideloaded ([`TESTING.md` §4](TESTING.md#4-a-real-watch)),
   capture mode baked on in `properties.xml` if settings do not appear.

For each, run A (no intermediates), B (two intermediates) and D (shake, for the
local name). Dump the capture log from the idle menu.

### 2.4 Record and decide

Post on #60 as **YES / NO / PARTIAL**, simulator and watch separately, with the
log. Then:

| Watch result | Product | Phase 3 builds |
|---|---|---|
| Two entries in one `ScanResult` | As designed: every split | Merged intake; nothing to pair |
| Separate results | Depends on #78 | Pair with `isSameDevice()` **only if** a two-chip test proves it; else advertisement-only when >1 chip present |
| Advertisement only | Rep total + final split only | Advertisement-only intake; open the follow-up #60 asks for, and correct README, site and store listing before any release |

---

## Phase 3 — Wire the broadcast path into the app (the real implementation)

**Goal:** a sideloaded build records reps from a real chip. Closes most of #61,
#7 and #9. Everything here is ring 3 first; the radio only appears at the end.

Work outside in, one criterion at a time:

1. **Seam.** `ScanResult` cannot be constructed in a test, so give the delegate
   a thin adapter that extracts `(manufacturer entries as ByteArrays,
   arrivalMs)` and hands them to a pure intake object, say `BroadcastIntake`.
   All behaviour lives in the intake; the delegate only extracts and forwards.
2. **Red tests on the intake**, using the Phase 1 real vectors where possible
   and `fake_chip.py --vectors` / `scenarios.py` frames otherwise:
   - a real rep's frames → one rep into `SplitEngine.onRepBurst`, with the
     legs MyFreelap showed;
   - forty repeats of one frame → one rep (#69);
   - a frame from an unbound chip → nothing; no chip id set → nothing, and the
     screen says why (#63);
   - a lap-number gap → a surfaced missed-rep count (#9);
   - a scan response with no matching advertisement → dropped, never attached
     to the nearest advertisement (#78);
   - whichever shape Phase 2 found (merged / separate / advertisement-only) is
     the default path, and the other shapes are handled or ignored on purpose.
3. **Continuous scanning.** Scan from session start to session end, including
   while paused (#9); a test with the timer paused still receives frames. The
   screen distinguishes *scanning*, *chip seen*, *chip seen this rep*.
4. **Delete the old path** (#61): pairing, subscribe, handshake,
   `FreelapProtocol.mc`, `PacketAssembler.mc`, and `ProtocolVectorTest.mc`'s
   vectors (#7 says delete, not adapt). The suite should stay green with less
   code.
5. **Fix the two P1 bugs that will distort a validation session**:
   #85 (the rep-summary overlay can exit the app) and #86 (duplicated finish
   record and closing lap in the FIT). Both have a reproducing test path in
   `TESTING.md` §2; do them now so the track data in Phase 5 is clean.

**Done when:** ring 3 green; the scenario suite still green; and in the
simulator with the nRF52 dongle, a real chip's rep shows up on screen and in
the saved `.fit`, read back with `python tools/fit_splits.py`.

---

## Phase 4 — Bench session on the watch (an hour)

**Goal:** prove the whole chain on the wrist before booking track time.

Two or three transmitters in a corridor or on a path, course measured with the
tape, e.g. `S:0;L:15;F:30` (respect the 10 m / 0.7 s minimum). MyFreelap running
alongside. Walk or jog five reps, then:

- [ ] Five laps in the activity, one per rep, no extras.
- [ ] `python tools/fit_splits.py activity.fit` legs equal MyFreelap's, to the
      hundredth.
- [ ] Shake recovery: let one rep finish with the watch out of range (leave it
      on a bench 30 m away), walk back, shake the chip; the rep appears
      **once** (REVERSE-ENGINEERING run H).
- [ ] Pause between reps, finish a rep just before pausing; nothing lost.

Fix what fails here with a test first, exactly as in Phase 3. Do not take a
build to the track that has not passed this.

---

## Phase 5 — First track validation: Freelap vs Garmin (a session)

**Goal:** #25's acceptance run, and a first look at beam timing next to
Garmin's own GPS timing.

### 5.1 Test first: the comparison tool

Before the session, add `tools/compare_session.py` with pytest coverage
against `tools/tests/data/reference-session.fit` and a small hand-written
MyFreelap fixture. Input: the `.fit` and a `myfreelap.csv` (rep, leg, seconds;
transcribed, or exported if your MyFreelap version can). Output:
`captures/<date>/validation.md`, a table with one row per split:

| rep | leg | MyFreelap | watch (`fl_split_us`) | Δ | Garmin lap time | GPS lap distance |
|---|---|---|---|---|---|---|

and a header with: reps seen by each, missing/extra reps, max |Δ|, and battery
start/end. Tests cover: exact match → Δ 0; one leg off by 0.01 s → flagged;
a rep present in one source only → listed as missing/extra.

### 5.2 The session

Course with **at least three transmitters**, e.g. `S:0;L:30;L:60;F:100`; set the
same course string in the watch settings. Then:

- [ ] Note battery % at start; capture mode **off** (this is a normal session).
- [ ] 20 reps, MyFreelap running in parallel the whole time.
- [ ] One rep finished out of the watch's range, recovered by shaking.
- [ ] At least one pause between reps.
- [ ] If a training partner with a chip is available, have them run too; their
      reps must contribute nothing to your file.
- [ ] Battery % at end.

### 5.3 Afterwards

1. Pull the activity's original `.FIT` from Garmin Connect (activity → ⚙ →
   *Export Original*).
2. `python tools/compare_session.py activity.fit myfreelap.csv >
   captures/<date>/validation.md`
3. Every Δ must be zero after MyFreelap's rounding. A non-zero Δ is a bug to
   run down (mask, origin, tie-break), not noise.
4. **Garmin columns are context, not pass/fail.** Garmin's lap time is when the
   watch *heard* the rep, so expect it to trail the beam by roughly the
   broadcast latency (`bleLatencyMs`, default 150 ms) plus scan timing; GPS lap
   distance will scatter around the course distance by a few metres. Write
   down the typical gap: it is the honest number for "how much better is beam
   timing than GPS for this athlete on this track", and it is what #68 needs.
5. Screenshot the Connect activity showing the laps and one developer-field
   chart; commit it beside `validation.md`.

Pass = #25's criteria all ticked. In that same PR, update the status wording in
`README.md` (*Status*), `site/index.html` (the status note and the meta
description) and anything in `docs/store/` that claims or disclaims it:
"nothing here has been run against a real Freelap chip" stops being true.

---

## Phase 6 — After the app is proven

In rough priority order:

1. **#9 battery.** If the measured drain from Phase 5 is too high for a two-hour
   session, design duty-cycled scanning against the broadcast window length
   measured in Phase 1 (run E), with the reasoning recorded.
2. **#78 with two chips** if Phase 2 found separate results and you skipped it.
3. **#68 — a data field** so Freelap splits can be recorded inside a normal
   Garmin workout, beside Garmin's own GPS timing.
4. **#79 — FxMotion**, if you have one.
5. Device coverage: run Phase 4 on a second, smaller-screen watch.

---

## One-page checklist

```
Phase 0  [ ] kit inventory, chip id + firmware   [ ] both test rings green locally
Phase 1  [ ] expected.json per run (from MyFreelap, before any hex)
         [ ] test_real_captures.py red -> green   [ ] #4 #5 #6 updated
         [ ] real frames pinned as Monkey C vectors
Phase 2  [ ] ScanProbe tested + wired            [ ] #60 answered, sim and watch separately
         [ ] #78 shape recorded
Phase 3  [ ] BroadcastIntake tests -> green      [ ] continuous scan   [ ] old path deleted
         [ ] #85 #86 fixed                         [ ] real rep in sim + nRF52 -> .fit
Phase 4  [ ] 5 bench reps match MyFreelap        [ ] shake recovery    [ ] pause safe
Phase 5  [ ] compare_session.py tested           [ ] 20-rep track session
         [ ] validation.md all Δ = 0              [ ] status notices updated
```

Record where you tested (simulator, nRF52, which watch) on every result.
A negative result, written down carefully, is as valuable as a positive one.
