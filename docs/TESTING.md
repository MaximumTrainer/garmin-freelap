# Verifying the app against real Freelap hardware

Four ways to run this app, in increasing order of what they prove and of how
much kit they need. Pick the cheapest one that can answer your question.

For the *order* to do the hardware work in, from first capture to the track
session that closes #25, see [`HARDWARE-ROADMAP.md`](HARDWARE-ROADMAP.md).

| Route | Needs | Proves | Does not prove |
|---|---|---|---|
| **1. Unit tests** | nothing | the decoder, the rep tracker, the course model, the FIT fields | that a chip sends what we think |
| **2. Simulator, generated frames** | nothing | the app end to end *except* the radio | anything about BLE |
| **3. Simulator + nRF52 + a real chip** | a dongle, a chip, a transmitter | **that a Connect IQ app can hear a real FxChip**, and what it hears | that a *watch's* BLE behaves the same |
| **4. A watch + a real chip** | a watch, a chip, transmitters | everything | — |

Route 3 is the one most people skip and should not. It answers
[#60](https://github.com/MaximumTrainer/garmin-freelap/issues/60) — the
question that decides what this app can be — without owning a Garmin watch.

---

## 0. Setup, once

The SDK is not on `PATH` in Git Bash on a typical Windows install (the entry
contains a literal `%APPDATA%`), so put it there yourself and use the `.bat`
wrappers:

```bash
SDK=~/AppData/Roaming/Garmin/ConnectIQ/Sdks/connectiq-sdk-win-<version>/bin
export PATH="$SDK:$PATH"
```

You need a developer key. In VS Code: *Monkey C: Generate a Developer Key*.
Keep it **outside the repository** — `*.der` is git-ignored, and committing one
is the mistake that ends a store account.

---

## 1. Unit tests

```bash
monkeyc.bat -f monkey.jungle -d fr265 -l 1 --unit-test \
            -y /path/to/developer_key.der -o bin/freelap-test.prg
connectiq.bat &                       # once; leave it running
monkeydo.bat bin/freelap-test.prg fr265 /t
```

`/t`, not `-t`, on Windows.

**The test build only fits on API 5.x devices.** On fr645m, fenix6,
vivoactive4 and venu it fails with *"Found N members in module 'globals',
exceeding the limit of 253"*. N grows with every test added, so do not read a
particular number as meaningful — the cap is the point. This is the test
harness, not the app: release builds are clean for all of those products.
Use `fr265` (416 px) and `fenix7` (260 px) to cover a large and a small round
screen.

An unhandled exception in a test kills the simulator process. Restart it before
the next run, or every subsequent test errors for reasons that have nothing to
do with the test.

The Python side needs no SDK at all:

```bash
python -m pytest tools/tests -q
python tools/validate_resources.py
```

---

## 2. The simulator, with generated frames

No radio, no chip. This is where most development happens.

**Generate frames, and the times they should decode to:**

```bash
python tools/fake_chip.py --print --reps 3 --course "S:0;L:30;L:60;F:100"
```

Each rep prints its advertisement and scan response as hex, above the legs a
correct decoder should recover from them. If the app disagrees with that line,
the app is wrong — the generator is checked against the vendor's own worked
example.

`--vectors` emits the same frames as Monkey C byte arrays, for pinning into
`source-test/`.

**Set the chip binding** the app expects: *File → Edit Persistent Storage →
Edit Application.Properties data*, and set `chipId` to the id you are
pretending to be. `BC-9636` is what `fake_chip.py` uses unless told otherwise.
Leave it empty and the app records nothing — deliberately, because guessing is
right on an empty track and wrong beside a training partner
([#63](https://github.com/MaximumTrainer/garmin-freelap/issues/63)).

**What this cannot do:** there is no way to hand the simulator a BLE
advertisement by hand. Everything downstream of the decoder is testable here.
The radio is not. That is route 3.

### The scenario suite

`source-test/ChipScenarioTest.mc` feeds frames for several chips and courses -
two transmitters, the worked-example three, the documented maximum of eleven,
the 10 m minimum gap, a sprint, a walk, a stranger's chip, and a chip whose
lap-number byte never increments - through the real decoder, tracker, adapter,
engine and recorder, and asserts the developer-field values a `FakeSession`
captures. `tools/scenarios.py` is the oracle: it generates the frames and
computes the expected values in the same exact integer arithmetic the watch
uses, and `tools/tests/test_scenarios.py` fails if the committed vectors are
stale. Run it with the unit tests; it is part of them.

### Producing a real activity file from a scenario

`FakeSession` accepts any value on any field. A real session does not, and it
has its own timing. So for a change to the recorder, produce a real `.fit` and
read it back. This recipe is verified; each step below exists because the
obvious alternative failed.

1. Put a temporary hook at the end of `FreelapApp.onStart()` and **restore the
   file when you are done** - nothing of the sort is committed. The hook
   builds a course and engine, starts the recorder, feeds one scenario rep
   (the `SCN_*` byte arrays from `source-test/ScenarioVectors.mc`, copied in
   verbatim, since a release build cannot see `(:test)` constants) through
   `BroadcastFrame` -> `RepTracker` -> `toCrossings()` -> `engine.onRepBurst()`,
   then a `Timer.Timer` that calls `recorder.save()` after ten seconds and
   `System.exit()`.
2. **Set `engine.observer = null` in the hook.** The app is the observer, and
   on a rep it pushes the five-second summary overlay. In `onStart` there is no
   main view underneath it yet, so when the overlay dismisses itself it pops the
   app's only view and the app exits - cleanly, with no exception and no crash
   log, exactly five seconds after the rep, before the save. This cost eight
   runs to find.
3. Build a **release** `.prg` for the device, start `connectiq`, and run
   `monkeydo bin/<file>.prg <device>` in the **foreground with stdin held
   open** - `( sleep 90 ) | monkeydo ...`. Backgrounded, it produces nothing.
4. monkeydo returns as soon as the app is launched, not when it exits. **Poll**
   `%LOCALAPPDATA%\Temp\com.garmin.connectiq\GARMIN\Activities` for a new
   file; it appears on `save()`, not on session start.
5. `python tools/fit_splits.py <file>` and compare with the oracle's
   `SCN_<NAME>_CUM_US` / `_SPLIT_US` / `_DIST_M`.

`tools/tests/data/scenario-worked100.fit` is one such file, and
`tools/tests/test_scenario_fit.py` asserts the oracle's values come back out of
it on every push. It also records two things about the real output that the
fake could never show: the finish record appears twice, and the activity's
closing lap repeats the last rep's lap fields.

---

## 3. The simulator with a real radio — an nRF52 board

**This is the most useful few hours anyone can spend on this project**, and it
needs no Garmin watch.

The Connect IQ simulator can use a Nordic nRF52 board as its Bluetooth radio.
With one plugged in, the simulator scans real air, and the app receives real
`ScanResult`s from a real FxChip.

### Kit

* An **nRF52840 Dongle** or an **nRF52 DK**. The SDK ships firmware for both;
  the dongle is the cheap way in.
* **nRF Connect for Desktop**, to flash it.
* An FxChip BLE, and a transmitter that can be set to **Finish**.

### Setup

1. Install nRF Connect for Desktop. On Windows the drivers come with it; on
   macOS and Linux install the Segger JLink drivers first.
2. Flash the board with the firmware the SDK provides — *nRF52 DK firmware* or
   *nRF52840 Dongle firmware*, both linked from the SDK's *Getting Started with
   Connect IQ BLE Development* page. The stock Nordic firmware will not do.
3. Find its serial port. Windows: Device Manager → Ports, e.g. `COM4`.
   macOS: `ls /dev/tty.usbmodem*`. Linux: `ls /dev/ttyACM*`.
4. In the simulator: **Settings → BLE Settings**, enter the port, OK.

If it errors, it is almost always the port. Re-check and re-enter it.

### What to do with it

Run the app, wake the chip, cross a Finish transmitter, and watch what arrives.
In order of what they settle:

1. **Does anything arrive at all?** If no Freelap frame ever reaches the app,
   stop and find out why before testing anything else.
2. **Is the scan response there?** This is
   [#60](https://github.com/MaximumTrainer/garmin-freelap/issues/60), and it
   decides whether this app records a split at every transmitter or only a
   total per rep. For each `ScanResult`, log:
   * how many entries `getManufacturerSpecificDataIterator()` yields for
     company `0x0363` — one, or two;
   * the length of `getRawData()`;
   * whether `getDeviceName()` returns anything. The chip's local name is only
     ever sent in a scan response, so a name arriving at all is itself evidence
     that Connect IQ scans actively.
3. **Does the decoded chip id match the one printed on the case?** That
   identity exists in three independent places — the advertisement, the local
   name in discoverable mode, and the print on the chip. All three agreeing is
   the strongest available check that the field offsets are right.

### The caveat, and it matters

**The simulator's BLE stack is not the watch's.** This project has already been
caught by a difference between them: the simulator's profile registry outlives
the app, producing a crash on the third launch that no hardware ever showed.

So a **yes** here is strong evidence that still needs confirming on a watch. A
**no** is close to conclusive and worth acting on straight away. Record which
you tested on, every single time.

---

## 4. A real watch

### Build and sideload

```bash
monkeyc.bat -f monkey.jungle -d fr265 -l 1 \
            -y /path/to/developer_key.der -o bin/freelap.prg
```

Connect the watch by USB — it mounts as mass storage — and copy
`bin/freelap.prg` into `GARMIN/APPS/`. Eject, and the app appears in the
activity list.

`-d` must match the watch you own. A `.prg` built for another product will not
run on it.

### Setting the chip id

The app records nothing until it knows which chip is yours. Normally that is
*Garmin Connect → your watch → Connect IQ apps → Freelap → Settings*, where you
type the id printed on the chip.

**A sideloaded app does not always expose its settings there.** If yours does
not, bake the value in for a test build: set the default in
`resources/settings/properties.xml`

```xml
<property id="chipId" type="string">BC-9636</property>
```

and rebuild. Inelegant, but it takes a minute and removes a variable while you
are trying to test something else. Do the same with the course if that does not
appear either.

### Getting the results off

The activity syncs to Garmin Connect like any other. For exact numbers read the
FIT file rather than Connect's UI, which rounds floats:

```bash
python tools/fit_splits.py activity.fit > splits.csv
```

[`docs/EXPORT.md`](EXPORT.md) explains every column, and which single number in
there is an estimate rather than a measurement.

---

## Handling the chip

From Freelap's own manual, and worth knowing before you waste a session:

* **It has no button.** Hold it vertically and shake it horizontally to wake
  it; the LED flashes green.
* **It sleeps after 30 minutes** without crossing a transmitter, and sleeping
  *loses the time held in memory*. A chip that appears silent may simply be
  asleep — rule that out before recording a missed frame.
* **Keep 30 cm** between the chip and whatever is listening. Closer than that,
  and Freelap warn of interference.
* **Shaking also puts it in discoverable mode** for 10 seconds, and **re-sends
  its most recent time**. That second behaviour is a recovery path for a rep
  the watch missed, and is worth testing deliberately.
* **The LED says what it detected**: green START, blue LAP, red FINISH. Free
  confirmation that a crossing happened, and which kind, independent of
  anything on the air.

### The transmitters

* At least one must be set to **Finish**. Without it the chip never enters lap
  mode and never advertises, and nothing else in this guide happens.
* **At most 11 transmitters**, and at least **10 m or 0.7 s** between any two.
  `Course` warns about both. A tighter course may not register at all, and a
  non-detection looks exactly like a missed frame.

---

## Recording what you find

Captures go under `captures/<date>-<chip-or-firmware>/`: the export, the runs
followed, and the values MyFreelap displayed alongside. **Record the chip's
firmware version** — the frame specification applies from a stated minimum, and
a capture from an older chip proves less than it appears to.

Never commit anything carrying a phone's identifying data. The chip's own
address is fine.

The scripted run set, and what each run settles, is in
[`docs/REVERSE-ENGINEERING.md`](REVERSE-ENGINEERING.md). Results belong on the
issue the run is for —
[#4](https://github.com/MaximumTrainer/garmin-freelap/issues/4) for the chip's
behaviour, [#5](https://github.com/MaximumTrainer/garmin-freelap/issues/5) for
the captures, [#60](https://github.com/MaximumTrainer/garmin-freelap/issues/60)
for what a Connect IQ app can see of them.

A **negative** result is worth as much as a positive one. Write it down with
the same care: "the scan response never arrived" is the single most valuable
sentence anyone could add to this repository right now.
