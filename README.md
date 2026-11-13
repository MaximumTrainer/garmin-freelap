# garmin-freelap

A native Garmin watch app that connects to a Freelap FxChip BLE over Bluetooth Low Energy, receives every transmitter crossing the chip recorded, and writes split time (µs), cumulative time, distance, velocity, speed and pace into the activity as FIT developer fields — one Garmin lap per Freelap rep, plus rep and session summaries.

The project is **garmin-freelap**. The *app* is called **Freelap** — that is the
name on the watch launcher (`resources/strings/strings.xml`) and in the Connect IQ
store listing, and it is deliberately not the repository slug.

Read `docs/DESIGN.md` first. The short version: the watch cannot sense Freelap's magnetic transmitters itself. The chip does, and the watch listens for the Bluetooth frames the chip broadcasts — exactly as the MyFreelap phone app does. There is no pairing and no connection; the chip announces and anyone in range can listen.

## Status

**Nothing here has been run against a real Freelap chip.** Everything below is
built and tested against generated frames.

What is done:

- **Freelap supplied the broadcast frame specification** (#8). It is
  confidential and is not in this repository; it is implemented, not
  reproduced. It replaced the connection-oriented design this project started
  with — the chip broadcasts and never accepts a connection.
- **The decoder exists twice and the two check each other.**
  `tools/freelap_frame.py` is the reference implementation and reproduces every
  value in the vendor's worked example; `source/ble/BroadcastFrame.mc` is the
  watch's, checked against vectors generated from it, with a test that fails if
  they drift apart.
- **`RepTracker`** works out which of the frames pouring in are reps, which are
  repeats, and which belong to somebody else's chip — and counts the reps the
  watch never heard.
- **Chip binding**: the id printed on the chip, typed into Garmin Connect
  (#64).
- It builds: `monkeyc -l 1` clean for every `manifest.xml` product whose device
  definition is installed (19 of 24), and `monkeydo /t` runs the Monkey C
  tests.

## Next steps

**Have a Freelap system? Start with
[`docs/HARDWARE-ROADMAP.md`](docs/HARDWARE-ROADMAP.md)**: the phased, test-first
order of work from first capture to a validated track session.

Almost everything left needs an FxChip and a transmitter set to **Finish**.
In rough order of what it would settle:

1. **#60 — can a Garmin watch read the scan response?** The chip puts the
   splits *between* transmitters there, and nothing in the Connect IQ SDK says
   whether a watch can see it. If it cannot, this app records a rep total and a
   final split and nothing finer, which is a different product. About an hour's
   work, and it gates the rest.
2. **#4 / #5 / #6 — confirm the documented frame against a real chip**, and
   settle the two things the specification could not: which mask applies to the
   running totals, and how `OFFSET` differs from `FROMLAP` on a second lap.
3. **#61 — delete the connection-oriented layer.** `FreelapProtocol.mc` and
   `PacketAssembler.mc` still implement the old guess. They wait on #4
   confirming the chip really does refuse a connection.
4. **#25 — twenty reps on a track against MyFreelap.** The last gate before
   this can honestly claim to work.
5. **#68 — a data field alongside the watch app**, so Freelap splits can be
   recorded into a structured Garmin workout with the beam timing beside
   Garmin's GPS timing.

Without hardware, `tools/fake_chip.py --print` generates frames and the times a
correct decoder should get back from them, with no radio involved.

## Layout

```
manifest.xml / monkey.jungle        CIQ project
resources/settings/                 course strings, BLE latency, capture mode
source/FreelapApp.mc                app entry, wiring
source/ble/FreelapProtocol.mc       ← the only file that knows the packet format
source/ble/FreelapBleDelegate.mc    scan / pair / subscribe / reconnect
source/model/Course.mc              "S:0;L:30;F:100" course parser & matcher
source/model/SplitEvent.mc          one crossing with derived metrics
source/model/SplitEngine.mc         crossings → splits → reps
source/fit/FitRecorder.mc           session + developer fields + laps
source/ui/                          activity screen, buttons, save menu
source-test/                        Monkey C unit tests (see AGENTS.md)
site/                               the project website (see below)
tools/decode_capture.py             find timestamp fields in a BLE capture
tools/fake_chip.py                  BLE peripheral: one rep, N synthetic reps, or a capture replay
tools/check_links.py                internal links in the site and the docs
tools/validate_resources.py         what CI can check without the Garmin SDK
tools/fit_fields.py                 read the fl_* developer fields out of a .FIT
tools/splits_to_csv.py              a dumped on-watch split log -> CSV
tools/fit_splits.py                 a .FIT file -> CSV (splits, laps or session)
tools/make_icons.py                 render the launcher icon at every size devices ask for
tools/tests/                        pytest suite for the above
docs/DESIGN.md                      architecture, timing model, FIT layout
docs/EXPORT.md                      getting the splits out, and what each column means
docs/screenshots/                   the main view at each target resolution
captures/                           BLE captures the protocol was derived from
docs/REVERSE-ENGINEERING.md         confirming the frame against a real chip
docs/TESTING.md                     simulator, nRF52 radio, and on-watch verification
docs/HARDWARE-ROADMAP.md            the order of work once you own a chip
```

## Website

<https://maximumtrainer.github.io/garmin-freelap/>

Published by `.github/workflows/pages.yml` from **`site/`** — a plain static
page, no Jekyll. `docs/` is deliberately *not* the publishing source: Pages
serving `/docs` would also publish the unsent letter to Freelap and the
unsubmitted store listing, and an exclude list only works until the next
working document is added. The screenshots the page uses are listed in
`site/assets.txt` and copied in at deploy time, so there is one copy of each
image in the repository.

## Work tracking

The plan is broken into [GitHub issues](https://github.com/MaximumTrainer/garmin-freelap/issues) grouped by milestone (M0 Foundations → M5 Beyond v0.1), each carrying a requirement and acceptance criteria. The issues are the single source of truth: the criteria on an issue are the test list for the PR that closes it (see `AGENTS.md`).

## Build

1. Install the Connect IQ SDK (7.x or newer) and the VS Code Monkey C extension.
2. Generate a developer key (VS Code: *Monkey C: Generate a Developer Key*).
3. Download the device definitions you need in the SDK Manager, and trim `manifest.xml` products to devices you own. `monkeyc -d <id>` refuses an id whose definition is not installed; the manifest itself only warns.
4. `monkeyc -f monkey.jungle -d fr265 -l 1 -o bin/freelap.prg -y developer_key.der` (or *Run* from VS Code).
5. Sideload `bin/freelap.prg` to `GARMIN/APPS/` on the watch.

CI does not run `monkeyc`: the SDK needs a Garmin login, so it cannot be
installed on a GitHub-hosted runner. [`.github/workflows/lint.yml`](.github/workflows/lint.yml)
validates the manifest, the resources and their cross-references, and runs the
Python tooling tests; its header comment carries the exact `monkeyc`/`monkeydo`
step to add once a self-hosted runner has the SDK. Run those two rings locally
before you push — see **Test** below.

```powershell
python tools/validate_resources.py   # the same check CI runs
python -m pytest tools/tests -q
```

## Test

Unit tests live in `source-test/` and run in the simulator:

```powershell
connectiq                                   # start the simulator once
monkeyc -f monkey.jungle -d fr265 -l 1 --unit-test -y developer_key.der -o bin/freelap-test.prg
monkeydo bin/freelap-test.prg fr265 -t
```

On Windows the SDK's `monkeydo.bat` takes `/t`, not `-t`. Or use *Monkey C: Run
Tests* in VS Code. The suite is green; `AGENTS.md` describes the outside-in TDD
loop this project follows.

The **test** build only fits on API 5.x devices — on the 240 px products it
exceeds Monkey C's 253-`globals` cap. That is the harness, not the app: release
builds are clean for every installed product. `fr265` and `fenix7` cover a large
and a small round screen.

**[`docs/TESTING.md`](docs/TESTING.md) is the guide to verifying against real
Freelap hardware** — including how to give the simulator a real Bluetooth radio
with an nRF52 dongle, which is how to answer the project's open question
without owning a watch.

## First run

1. Settings (Garmin Connect app → the watch → Connect IQ apps → Freelap): enter the **chip id printed on your FxChip** (two letters and four digits, e.g. `BC-9636`) and your course, e.g. `S:0;L:30;L:60;F:100`. Enable *Capture mode* if you are investigating the protocol. Without a chip id the app records nothing and says so — it will not guess.
2. Open the app; it listens. There is no pairing: the chip broadcasts, and the app accepts frames from the id you bound and ignores every other chip in range.
3. Wake the chip (hold it vertically, shake it horizontally), press START and run a rep. A rep is broadcast when you cross a transmitter set to **Finish**. In capture mode the last raw frame is shown on screen and recent frames are kept in app storage.
4. Controls: START = start / pause / resume. BACK = end the current rep while recording,
   or open Save/Discard while paused. On a touch screen, tapping the upper half is START and
   the lower half is BACK. Ending a rep with no crossings shows *No splits* and writes nothing.
   There is no way out of a running session without pausing first, which is deliberate. If the
   watch closes the app with a session still open, the session is **saved**, not discarded.

## Where the data ends up

In the `.FIT` file, as developer fields with a `field_description` each (field ids 0–10 on `record`, 20–25 on `lap`, 40–43 on `session`), and independently in `Application.Storage` as the last session's split log.

```bash
python tools/fit_splits.py activity.fit > splits.csv    # from the FIT file
python tools/splits_to_csv.py dump.txt > splits.csv     # from the watch's own log
```

**`docs/EXPORT.md`** explains both routes, what every column means, and which single number in there is an estimate rather than a measurement. `python tools/fit_fields.py <file.fit> --values` prints the raw developer field table, which is what to look at when a column comes out empty; `tools/tests/data/reference-session.fit` is a real file from the simulator that CI asserts the table against. Garmin Connect charts the record fields and lists lap fields per lap. For lossless µs values use the FIT file directly (FIT SDK `FitCSVTool`, `fitparse`, `fitdecode`); Connect's UI rounds floats but shows uint32 as-is.
