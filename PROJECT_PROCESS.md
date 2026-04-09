# ORIENTATION — Project Process Documentation

> Step-by-step documentation of how this project evolved.  
> Not sorted by date — sorted by sequence of events and decisions.

---

## Step 1 — Problem Discovery & Initial Research

The team decided early on to work on the topic of **orientation for people with limited senses**. The project channel was originally named *ai-orientation* — reflecting that AI-driven sensing was part of the vision from day one. It was later renamed simply *orientation* as the scope clarified.

**Primary target user:** Blind and severely visually impaired people navigating outdoor urban environments.

Research was conducted in parallel by all three team members and compiled into shared references. Early external references that shaped thinking:
- **BlindSight** (Hackster.io) — a wearable haptic device for the visually impaired, noted for technical architecture insights
- **WebHaptics** — a haptic feedback library for the mobile web, explored early for software-side feasibility
- Faruk compiled a deep-dive research document: *"Assistive Navigation for Visual Impairment — Research Findings"* covering white cane limitations, pain points, and design implications from existing literature

Key statistics that grounded the problem:

- **54%** of blind/severely visually impaired people experience a head-height obstacle collision at least once a year — often much more frequently
- **23%** of those accidents require immediate medical attention
- **43%** of cane users permanently change their walking behavior after a head-level collision (slower, more defensive)
- A white cane only covers ground-level obstacles in a ~1m forward cone — it does nothing for upper-body threats, approaching pedestrians, or lateral obstacles
- In crowded or noisy environments: acoustic masking removes the only remaining spatial sense
- Constant environmental monitoring causes cognitive overload — no bandwidth for conversation or relaxed navigation

**Design goal: restore *spatial courage*.** Not just safety — the freedom to move without constant vigilance.

**Additional user groups considered (still open):**
- Deaf people who lack audio spatial cues
- Sighted people who want rear-awareness (e.g. cyclists, runners) — *use case not yet defined, no user story confirmed*

---

## Step 2 — Early Team Alignment: Ideas and Discussions (13.03)

Before going deep into prototyping, the team held an early alignment session to establish shared ground. Key outcomes documented:

**User groups considered:**
- People with vision impairment — walking, moving around in the environment, ambient awareness *(primary focus)*
- People with anxiety, schizophrenia, etc. — spatial awareness as a calming tool *(interesting secondary target)*
- Bikers — *noted but explicitly excluded from this project's scope*

**What we agreed on early:**
- The device must be wearable
- Cameras: infrared, wide-angle considered
- Comfortable in all situations and weather conditions
- Sensors + haptics + possibly sound
- **Key early decision:** The compute unit ("the machine") does not need to be inside the collar — for the prototype, it can live in a connected external device (bag, pocket, etc.)

**Open questions at this stage:**
- How could the system be *predictive* (not just reactive)?
- User cases for the exhibition
- How does the user feel when using it — what are the actions they take?

---

## Step 3 — Early Electronics Experimentation

Before committing to a specific form factor, Faruk purchased a set of electronics components independently (bluetooth/wifi board, haptic coin motors, resistors, diodes, transistors, cables, accelerometers, batteries). The goal was a simple proof of concept: can we make something vibrate from a mobile device?

The team experimented with a BLE-enabled speaker wearable on a breadboard using an ESP32. The result: a very quiet, barely audible sound — not at all what was envisioned. The hardware worked in the most minimal sense, but confirmed that making it work *well* would require proper support.

**Key takeaway from this phase:** Electronics at this level require specialist knowledge. The team reached out to the prototype lab (via Anna) to get proper hardware support rather than trying to figure everything out independently. This decision saved significant time.

---

## Step 3 — Form Factor Exploration: Paper Prototypes

Before any real electronics were integrated, the team built **4 cardboard paper prototypes** to experiment with where on the body the device should be placed.

Candidates explored:
- **Belt** (waist height)
- **Neckband / collar** (neck and shoulder area)
- **Shoulder strap**
- **Insole**

The goal: figure out which placement makes the most spatial sense for communicating direction — front, back, left, right.

Faruk documented the entire session with a camera. **100 photos were taken.** Enes directed the photo shoot — composition, angles, and staging. Several shots came out strong enough to be portfolio material from the start.

---

## Step 3 — Form Factor Criteria

To make a data-driven decision between form factors, the team defined a set of criteria and evaluated the two strongest candidates — **Belly (belt)** and **Necklace (collar)** — against them.

| Criterion | Belly | Necklace |
|---|:---:|:---:|
| 360° spatial coverage? | ✓ | ✓ |
| Sensor placement natural? | ✗ | ✓ |
| Cable / hardware routing clean? | ✗ | ✓ |
| Works over jacket? | ✓ | ✓ |
| Wearable without assistance? | ✓ | ✓ |
| Stays stable while walking? | ✗ | ✓ |
| Doesn't restrict movement? | ✗ | ✓ |
| Weight distribution? | ✗ | ✓ |
| Skin contact comfortable long-term? | ✗ | ✓ |

The necklace won 8 out of 9 criteria. Both formats offer 360° directional coverage in principle, but the necklace outperforms on sensor placement (shoulder level is ideal for head-height obstacles), stability during walking, and comfort over extended wear. The belly belt also confirmed its weakness through physical user testing — see Step 9.

The neckband and belt were carried forward into physical testing to validate the criteria with real users.

---

## Step 5 — Parallel Software Development: Phone Prototype

While form factor testing was ongoing, the team built the first version of the software using **2 Android phones**.

> **Why Android?** iPhones cannot be programmed to trigger custom vibration patterns — Android allows full haptic control.

One phone mounted **front**, one **back**, attached to the two strongest physical prototypes (neckband and belt).

**What was built:**
- `phone.html` — browser-based prototype running on Android
- COCO-SSD object detection via the phone camera
- Threat classification: `safe / notice / warning / danger`
- Directional vibration based on camera detections
- Class stability filtering (to avoid jitter)
- `server.js` — Node.js/Express/Socket.IO server connecting both devices
- `dashboard.html` — monitoring view showing what each phone sees and detects

---

## Step 6 — First User Test: Overwhelm

**Setup:** User wore the two-phone prototype (neckband + belt) with the automatic software running.

**Outcome:** The test person felt completely overwhelmed.
- Almost everything was classified as danger
- Too many vibrations happening simultaneously
- No clear sense of what was important vs. noise
- The system produced more anxiety than orientation

**Key insight:** The automatic pipeline was too aggressive. Less signal = more meaning.

---

## Step 7 — Software Improvement: Wizard of Oz Control

After the first test, the software was extended with a **manual Wizard of Oz override**:

- From the dashboard, the operator could manually control what each phone would signal
- The operator decided *when* to trigger a vibration, at what intensity, and for which direction
- Phones could be controlled remotely in real time without the user knowing

This allowed the team to test haptic language and information density independently of detection accuracy.

---

## Step 8 — Second User Test: Blindfolded Run with Manual Control

**Setup:** Test person was blindfolded. The operator ran the Wizard of Oz dashboard.  
Two form factors tested in sequence: **neckband** vs **belt at waist height**.

**Outcome:**
- With manual control, much less information was needed to create meaningful spatial awareness
- The user could orient themselves and navigate without being overwhelmed
- Confirmed: *silence as the safe state* works — users trusted the absence of vibration

**Key insight:** Less is more. The first test was overcommunicating. A single well-timed cue beats a stream of alerts.

---

## Step 9 — Third Test: Physical Tapping Only (No Technology)

**Setup:** No software, no hardware. The operator physically tapped the test person on the body to simulate haptic signals.  
Two conditions:
1. Tapping on **shoulders** (neckband zone)
2. Tapping at **waist / stomach** (belt zone)

**Outcome:**
- Both zones worked for directional communication
- The person was consistently more sensitive at **waist height**
- The waist taps caused involuntary startle responses — the user described them as ticklish and unexpected every time
- Shoulder/neck taps felt more natural and less intrusive

**Key insight:** Waist-level haptics are too sensitive for continuous wear. Shoulder/neck area is more appropriate for ambient, ongoing signals.

---

## Step 10 — Form Factor Decision: Neckband / Collar

Based on all three tests and the criteria evaluation, the team decided on the **neckband / collar** form factor.

**Why the collar won:**
- Covers all four spatial directions clearly (front = chest, back = upper back, left/right = shoulders)
- Vibration at shoulder level is noticeable but not startling
- Wearable over coats and winter clothing
- Can be designed to look like a fashion accessory, not a medical device — **"soft faux-fur collar"**
- Doesn't interfere with cane use
- Weight distributable across shoulders (not on neck)

**Design language defined:** Soft, fluffy faux-fur collar — feels like an accessory, not a medical device.  
**Core principle confirmed:** Vibration location = direction. Silence = safe.

---

## Step 11 — Hardware Research & Component Decisions

After locking the form factor, the team researched what hardware needed to go into a real, electronics-based prototype.

**Key decisions made:**
- **Raspberry Pi 4** as the central compute unit — runs ML inference, sensor fusion, server
- **Arduino Nano Every** as dedicated haptic controller — receives commands from Pi, drives motors
- **VL53L0X ToF distance sensors (×4)** for proximity: front, back, left, right (range ~2–2000mm via I²C)
- **ProXtend X301 Full HD Webcams (×2)** for object detection: front-facing + back-facing
- **DFRobot FIT0774 Mini Vibration Motors (5–8×)** for haptic output
- **DFRobot DFR0440 Vibration Module (×2)** as driver modules — confirmed by Anna
- **Transistor circuits (2N3904, flyback diodes, 1kΩ resistors)** — one circuit per motor
- **Li-Po battery + TP4056** for portable power

**Rationale for two-board architecture:**  
Pi handles compute, Arduino handles real-time motor timing — keeping haptic patterns precise even if the Pi is busy with inference.

**Why VL53L0X instead of ultrasonic:** ToF sensors are faster, more accurate at short range, and give consistent distance readings through clothing material.

**Hardware not yet confirmed:**
- Speaker type (small speakers vs piezo buzzers vs bluetooth) — pending test
- USB microphone — needed if wake-word voice assistant is added to collar

**First impressions of real hardware:** When the ProXtend X301 webcams arrived, the reaction was: *"that camera is huge AF."* Larger than expected — the team acknowledged it would need to be worked into the collar design somehow, at least for the functional prototype.

**Product naming:** The working name is *ORIENTATION*. The team discussed using an Estonian name to allow braille-printed tags for the exhibition. No final name chosen yet.

---

## Step 12 — User Research Preparation & Interview Attempts

In parallel with hardware and form factor work, the team invested significant effort into user research methodology.

The 3/21 huddle crystallized the team's research philosophy before any interviews were attempted:

- **Laura:** Understand user needs before building anything technical. Don't over-complicate. Focus on solving *one* problem well.
- **Enes:** The device must respect user autonomy — it's an independent assistance tool, not a dependency.
- **Faruk:** Semi-structured interview approach — let users naturally describe their experiences, don't steer them.
- **Team agreement:** No leading questions. No confirmation bias. No designing for what we assume the problem is.

**What was prepared:**
- Each team member independently researched blind navigation challenges (podcasts, AI personas, academic papers, existing assistive tech)
- Faruk compiled findings into: *"Assistive Navigation for Visual Impairment — Research Findings"*
- Interview questions written individually by Enes and Faruk, then merged and refined in FigJam — structured in phases: rapport, mobility context, friction moments, specific scenarios, technology attitudes

**Attempt to reach blind users:**
- Contact 1: Hendra (female) — offered to connect the team with people in the blind community → all her contacts were too busy
- Contact 2: **Blind People Union** — formal organization, Laura's task
- Alternative: send written questions instead of live interviews
- Fallback: approach blind pedestrians on the street for informal conversations

---

## Step 13 — Component Layout & System Visualization

Before building anything physical, Enes created a set of technical design diagrams to map out where every component lives and how the system flows. Three panels:

**Panel 1 — Collar Layout (top-down, to scale)**
A flat schematic of the collar shape with all components placed at their intended positions. Dimensions annotated (200mm sides, 130mm front section, etc.). Components shown: 2× cameras, 4× distance sensors, multiple vibration motors, speakers, on/off button, microphone — each using consistent iconography.

**Panel 2 — Use Case Visualization**
Bird's-eye view of a person (O) with three surrounding people/obstacles (P) at varying distances and directions. Concentric detection-range rings show the system's spatial awareness. Makes the core concept immediately readable without any explanation.

**Panel 3 — System Architecture Diagram**
Input layer: 1× camera + 5× distance sensors  
Processing: `sensor_bridge.py`  
Output layer: 4× speakers + 9× vibration motors

The diagrams are minimal, muted palette (warm beige/brown), and consistent across all three panels — ready for portfolio use as-is.

---

## Step 14 — Three Parallel Prototype Directions

After deciding on the collar form factor, the team defined three parallel prototype tracks to work toward — each with a different owner and purpose:

| Prototype | CMF Direction | Owner | Purpose |
|---|---|---|---|
| **Industrial / Polished** | Neutral, Plastic, 3D printed | Enes (+ Faruk support) | Shows the product could be a real consumer device |
| **Vivid / Textile / Organic** | Textile, handmade like a stuffed animal | Laura & Faruk | Shows the soft, wearable, emotional side of the concept |
| **Functional** | Whatever works | Everyone | The one that actually functions end-to-end — most important |

The logic: if you can show three versions at exhibition — one that looks polished, one that feels human, one that actually works — the audience understands both the concept *and* the range of possible futures for the product.

Faruk also acquired a sewing machine and textile materials in preparation for the organic prototype direction.

---

## Step 14 — Software Evolution: Pi-Based Pipeline

The phone prototype (`phone.html`) was replaced by a proper Raspberry Pi-based software pipeline.

**What was built (with Claude's help):**

### `server.js`
Node.js / Express / Socket.IO server (port 3000). Handles:
- Device registration (Pi connects as sensor source)
- Spatial updates and threat levels per direction
- Camera frame streaming
- ToF distance data relay
- Dashboard commands and manual override
- Voice query/response relay

### `dashboard.html`
Full monitoring dashboard:
- Live camera feeds (front + back)
- Detection list per frame
- Body map visualization (which zones are active)
- Auto / manual mode toggle
- Voice agent controls (text input + log panel)
- Manual haptic override (critical for Wizard of Oz fallback at exhibition)

### `sensor_bridge.py`
Python script running on Raspberry Pi:
- Captures webcam via OpenCV
- Runs YOLOv8n object detection (fastest model for Pi 4, ~4–8fps)
- Classifies threats: `safe / notice / warning / danger`
- Class stability filtering (prevents flickering)
- Mock ToF distances (until real sensors wired)
- Sensor fusion: camera detections + distance readings → spatial map
- Serial commands to Arduino
- Streams spatial data to server via Socket.IO

### `arduino/motor_controller/motor_controller.ino`
Arduino sketch:
- Receives serial commands from Pi (`ZONE <id> <level>` or `SYS <pattern>`)
- Manages vibration timing loops independently
- Zone IDs: 0=front, 1=left, 2=right, 3=back, 4=state

### Haptic Language Implemented

| Signal | Pattern | Meaning |
|---|---|---|
| Gentle tap | 25ms on, every 3s | Person or mild presence nearby |
| Double tap | 50ms, 80ms gap, 50ms, every 1.5s | Static obstacle in path |
| Triple burst | 120, 60, 120, 60, 120ms, every 0.9s | Fast-approaching / urgent |
| Continuous | Sustained, distance-proportional | Very close obstacle |

Distance thresholds (VL53L0X):
```
> 150cm  → no signal
100–150cm → notice
 50–100cm → warning
  < 50cm  → danger
```

Anti-overload rules: max 2 zones active simultaneously; front > danger > closest distance in priority.

---

## Step 15 — Voice Assistant: OpenClaw / Navi

In parallel with the haptic pipeline, the team explored adding a voice assistant to the collar — a conversational AI the user could talk to for navigation, environment description, or help.

**Product chosen:** OpenClaw (open-source AI agent framework, Node.js-based)  
**Interface:** Telegram bot named **"Navi"** (after the fairy companion from The Legend of Zelda)  
**Running on:** Hetzner cloud server (CPX22, always on, accessible 24/7)  
**Model:** Claude Sonnet 4.6 via Anthropic API  

**Skills installed on Navi:**
- Google Places (location search and POI lookup)
- ElevenLabs TTS (voice output)
- OpenAI Whisper (speech-to-text)
- DuckDuckGo web search
- Session memory
- URL summarizer

**Future integration planned:** Voice button on collar (GPIO pin 23 on Pi) triggers Navi. Wake-word "Navi" as long-term goal.

---

## Step 16 — Where We Are Now: Hardware Assembly

All hardware components have been acquired. The physical collar construction is beginning.

**What has been completed (from team TODO list):**
- ✅ Create a 1st prototype with phones hanging on the shoulders
- ✅ Vibecode the software for phone cameras for 1st testing
- ✅ Validate body location for haptics
- ✅ Generate prototype ideas for the physical product
- ✅ Generate prototype ideas for testing the functionality

**Currently open tasks (team assignments):**
- [ ] Continue to work on Technical Prototype — *Enes*
- [ ] Work on 3D Model and Plan — *Enes* *(open question: does this make sense given the time left?)*
- [ ] Think about the Textile for the Ergonomical Prototype — *Laura*
- [ ] Contact Blind People Union — *Laura*
- [ ] Put Research and Questions together — *Laura*
- [ ] Prepare Exhibition Script — *Laura*

**Open design question: The Outer Shell**

Making the electronics work is one thing — making the collar ergonomic and wearable is a separate problem that needs its own attention. Two parallel directions:

- **3D printed shell** (Enes) — a polished, structured housing for the components
- **Textile shell** (Laura) — softer, handmade, closer to the faux-fur vision

The shell determines how the collar sits on the body, how it interacts with clothing, and whether it actually feels like something worth wearing. Ergonomics cannot be an afterthought added on top of the technical prototype.

**Immediate technical next steps:**
- Wire vibration motors to Arduino via transistor circuits — test each motor individually
- Connect VL53L0X sensors to Pi via I²C (XSHUT pins for unique address assignment)
- Mount webcams on collar structure
- Test `sensor_bridge.py` on real Pi with real webcam
- End-to-end loop: camera → detection → fusion → serial → motor vibration

**Pending decisions (must resolve before April 16):**
- [ ] Speaker type — test with small speakers; decision: speakers vs piezo vs bluetooth
- [ ] ToF sensor mount angles: horizontal or slightly downward?
- [ ] Camera orientation: horizontal or slight upward angle for head-height obstacles?
- [ ] Tap/check gesture method: physical button vs capacitive touch?
- [ ] Motor placement finalization before sewing into collar
- [ ] Shell approach: 3D print vs textile vs combination
- [ ] Silence as safe: sufficient alone, or need a subtle periodic heartbeat?
- [ ] Confirm Pi + battery live externally (bag/pocket), not on collar

---

## Step 17 — Raspberry Pi Setup & First Live Detection Test

With the software pipeline fully written, the next milestone was getting it running on real hardware — not a simulation, not a phone, but the actual Raspberry Pi 4 that will live inside the prototype.

**Setup path taken:**

The Pi was flashed fresh using Raspberry Pi Imager (Raspberry Pi OS Lite 64-bit), with SSH enabled and the hostname `orientation` set during imaging. The EKA university network turned out to block mDNS (`.local` hostnames) and direct SSH connections between devices — so the standard `ssh orientation@raspberrypi.local` approach didn't work. The solution: **Raspberry Pi Connect** (`connect.raspberrypi.com`), a browser-based remote access tool provided by the Raspberry Pi Foundation. This gave full terminal access through a web interface without needing to be on the same network.

**File transfer challenge:**

Moving `sensor_bridge.py` from Mac to Pi was non-trivial. SCP (port 22) was blocked by EKA. `transfer.sh` was offline. The Hetzner server's port 8765 was blocked by its own firewall. Final solution: upload via GitHub CLI (`gh gist create sensor_bridge.py --public`) and pull on the Pi via `wget` from the raw Gist URL. Straightforward once the blockers were identified.

**Dependency installation on Pi:**

Installing `ultralytics` (YOLOv8) naively pulls CUDA GPU packages — roughly 540MB on a Pi with no GPU and limited storage. The Pi ran out of disk space mid-install. Fix: clear pip cache first (`pip3 cache purge`), then install PyTorch CPU-only explicitly before ultralytics:

```bash
pip3 install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
pip3 install ultralytics --break-system-packages
pip3 install "python-socketio[client]" "python-engineio" --break-system-packages
```

**First live test — webcam connected:**

A ProXtend X301 Full HD webcam was plugged into the Pi via USB. Running `sensor_bridge.py --no-display` (no GUI on a headless Pi), the output confirmed:

```
[front] Camera 0 ready (640x480)
[bridge] Running. Ctrl+C or Q to quit.
[serial] ZONE 0 1
[serial] ZONE 1 2
[serial] ZONE 2 0
[serial] ZONE 3 0
...
```

The Pi was looking through a real camera, running YOLOv8n inference, classifying spatial threats, and outputting zone commands — the same commands the Arduino will eventually receive to drive vibration motors.

**One bug found and fixed:**

The original `sensor_bridge.py` used a Python `or` expression to fall back to a test frame if the real frame was `None` — but `or` doesn't work with NumPy arrays (the camera frame is an array). This caused a `ValueError` on the first live run. Fix: replaced `read_frame(cap) or fallback` with an explicit `None` check. Fixed, re-uploaded, re-downloaded, re-ran — working.

**What this milestone means:**

This is the first time the real compute unit (Pi) ran the real detection pipeline through a real camera. All three previous layers — YOLOv8 inference, threat classification, serial output formatting — work correctly on the actual hardware. The pipeline is no longer simulated.

**What's still missing before full end-to-end:**
- Arduino Nano Every receiving and acting on `ZONE` commands (serial loop)
- VL53L0X sensors wired via I²C (I²C interface still to be enabled on Pi)
- `server.js` running on the Pi so Socket.IO connection succeeds (currently "running offline")
- Motor circuits and collar assembly

---

## Step 18 — Hardware Assembly Day: Arduino UNO + Motor + VL53L0X (09.04.2026)

Today was the first real hardware assembly session with Anna. Goal: connect all physical components to Arduino UNO, flash the firmware, and achieve an end-to-end pipeline from camera detection → ZONE command → motor vibration.

**Arduino UNO confirmed (not Nano Every):**

The available Arduino was an UNO R3, not the originally planned Nano Every. This required a different FQBN for arduino-cli:
- Nano Every: `arduino:megaavr:nona4809` (wrong)
- UNO: `arduino:avr:uno` ✅

arduino-cli was installed on the Pi via the official curl script (not apt, which was outdated):
```bash
curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh | sh
```

**Motor: DFRobot Gravity Vibration Module V1.1:**

The vibration motor used is a DFRobot Gravity module — 3-wire (GND / + / Signal), with an onboard driver. This means no transistor or separate driver circuit needed. Signal wire connects directly to a digital PWM pin (Pin 9).

Wiring: Signal → Pin 9 | + → 5V | GND → GND

**`motor_controller.ino` — firmware flashed to Arduino UNO:**

The firmware handles two things:
1. Listens on Serial (9600 baud) for `ZONE X Y` commands from the Pi
2. Drives vibration motor with 4 levels (0=off, 1=short pulse, 2=double tap, 3=triple burst)

Key learning: Arduino UNO resets when the serial port is opened (DTR pin). The Pi must wait 2 seconds after opening the port before sending commands. Also, Arduino's `String` class caused command parsing to fail silently on AVR — replaced with `char buf[32]` and direct character comparison (`buf[0]=='Z' && buf[1]=='O'`), which works reliably.

**End-to-end motor vibration confirmed working:**

With `sensor_bridge.py --serial-port /dev/ttyACM0` running on the Pi, YOLOv8 detecting objects through the webcam, and ZONE commands flowing over serial to the Arduino — **the motor vibrated in response to real detections**. This is the first full end-to-end confirmation of the core haptic feedback loop.

```
Pi webcam → YOLOv8 → ZONE 0 2 → Arduino serial → vibrate(2) → motor ✅
```

**VL53L0X ToF sensor: moved from Pi to Arduino UNO I2C:**

The VL53L0X distance sensor was previously attempted on the Pi's I2C bus but never registered on `i2cdetect`. Anna suggested moving it to Arduino UNO I2C instead (A4=SDA, A5=SCL) — a better architecture since the Arduino can read distance continuously and send `TOF:distance` over serial to the Pi.

The Pololu VL53L0X Arduino library was installed:
```bash
arduino-cli lib install "VL53L0X"
```

Wiring: VIN → 5V | GND → GND | SDA → A4 | SCL → A5

**VL53L0X diagnosis: sensor appears damaged:**

Despite correct wiring (verified: yellow=SCL→A5, gray=SDA→A4, red=VIN, black=GND), the sensor does not respond on I2C. A debug sketch confirmed:
- `DEBUG: Wire started` prints correctly → Arduino I2C bus is working
- `sensor.init()` hangs indefinitely → no device responds on the bus
- Neither 3.3V nor 5V on VIN makes a difference

The sensor likely suffered permanent damage during an earlier session when wiring to the Pi was incorrect. **The VL53L0X is to be considered defective and needs replacement.**

**What still works without the sensor:**

The motor_controller.ino handles `sensorOK = false` gracefully — motor vibration via ZONE commands continues to work normally. The `sensor_bridge.py` also has a mock ToF fallback. The Phase 1 demo can proceed without real distance data.

**GitHub repository created:**

A GitHub repo was created for the project. Collaborators added:
- Faruk (@726f6f6b)
- Laura (@luu-ra)

All project files pushed (excluding node_modules, .pem keys, yolov8n.pt model).

**Summary of what was achieved today:**

| Goal | Status |
|---|---|
| Flash Arduino UNO via Pi | ✅ Done |
| Motor vibration from ZONE commands | ✅ Working |
| Full pipeline: camera → YOLO → motor | ✅ Confirmed |
| VL53L0X wired to Arduino I2C | ✅ Wired correctly |
| VL53L0X reading distance | ❌ Sensor defective |
| GitHub repo with collaborators | ✅ Done |

**What to do next (tomorrow / next session):**

1. **Order a new VL53L0X sensor** — the current one is defective
2. **Second vibration motor** — currently only one motor is wired; need one for front zone and one for back/side
3. **Wire second motor** to a second digital pin (e.g. Pin 10) and extend `vibrate()` function
4. **Physical collar assembly** — mount Pi, Arduino, motors, battery into the collar form
5. **Run full demo** with collar worn: person walks, camera detects, motor vibrates in correct zone
6. **Dashboard camera streaming** — still shows "NO SIGNAL" (deprioritized, not blocking demo)

---

## Decisions Already Made (do not revisit)

| Decision | Choice | Reason |
|---|---|---|
| Form factor | Collar / neckband | Best criteria fit, waist too sensitive, shoulder zone natural |
| Compute board | Raspberry Pi 4 | ML inference + server + I²C + serial simultaneously |
| Haptic controller | Arduino Nano Every | Dedicated real-time motor timing |
| Distance sensors | VL53L0X ToF × 4 | Accurate short-range, I²C bus, corrected from MPU-6050 |
| ML model | YOLOv8n | Fastest option viable on Pi 4 |
| Object detection source | Webcams (not phone cameras) | Stable, USB, consistent placement on collar |
| Core haptic principle | Silence = safe, location = direction | Confirmed across all three user tests |
| Max simultaneous zones | 2 | Anti-overload; more = confusion |
| Voice assistant | OpenClaw / Navi on Hetzner | Reliable, always-on, not running on battery-limited Pi |
| Design language | Faux-fur soft collar | Fashion accessory aesthetic, not medical device |

---

## Open Questions (not yet resolved)

- Is silence alone sufficient as the "safe/active" signal, or do users need a periodic heartbeat to trust the system is on?
- What is the valid use case for sighted users wanting rear awareness? (No user story defined yet)
- How do we integrate a blind person's real-world perspective? (Interview not yet done)
