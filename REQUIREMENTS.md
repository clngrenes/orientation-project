# ORIENTATION — Project Requirements
**Haptic Spatial Awareness Collar for Visually Impaired Users**

> Living document — update as decisions are made.
> Team: 3 people · Course deadline: **16 April 2026** · Exhibition: **30 May 2026**

---

## 1. Project Overview

ORIENTATION is a wearable haptic collar designed for visually impaired people navigating outdoor urban environments. It detects nearby obstacles, people, and movement in four spatial directions (front, left, right, back) and translates that information into directional vibration patterns at the corresponding body location.

The collar is an *additional sense*, not a navigation system. It supplements — never replaces — a white cane by providing upper-body and peripheral spatial awareness that a cane physically cannot cover.

**Design language:** Soft, fluffy faux-fur collar — feels like a fashion accessory, not a medical device.
**Core principle:** Vibration location = direction. Silence = safe.

---

## 2. The Problem

Research findings that ground this project:

- **54%** of blind/severely visually impaired individuals experience an obstacle accident at head height at least once a year, often much more frequently.
- **23%** of those accidents are severe enough to require immediate medical attention.
- **43%** of cane users permanently alter their walking habits (slower gait, defensive posture) after a head-level collision.
- A white cane covers only ground-level obstacles in a ~1m forward cone — it does nothing for upper-body threats, approaching pedestrians, or lateral obstacles.
- Crowded, noisy environments cause *acoustic masking* — removing the only spatial sense most blind users have beyond the cane.
- Cognitive load of constant environmental monitoring leaves no bandwidth for conversation, relaxation, or spontaneous navigation.

**Design goal: restore *spatial courage*.** Not just safety — the freedom to move confidently, without constant vigilance.

---

## 3. Team & Timeline

| Phase | Deadline | Target completeness | Focus |
|---|---|---|---|
| **Phase 1 — Class Prototype** | 16 April 2026 | ~80% | All core functionality working, may be rough |
| **Phase 2 — Exhibition** | 30 May 2026 | 100% stable | Polish, reliability, demo-readiness |

3-person team. All hardware is already acquired (see Section 6).

---

## 4. Primary Users & Context

**Primary user:** Visually impaired people navigating outdoor urban environments with a white cane.

**Scenarios in scope:**
- Walking from home to a bus stop along familiar sidewalks
- Passing sidewalks partially blocked by scooters, bins, bicycles, or temporary barriers
- Navigating near pedestrians and moving objects

**Context of use:**
- Outdoors: sidewalks, residential streets, bus stop areas
- Over winter/outdoor clothing (coat, hoodie, jacket)
- Short-duration demo sessions at minimum; longer if possible

**Out of scope — this project does not do:**
- GPS turn-by-turn navigation
- Indoor wayfinding
- Traffic light detection
- Reading signs, text, or bus numbers
- Full 360° semantic scene understanding
- Support for all disability types

---

## 5. Core Use Cases

### Use Case 1 — Walking to the Bus Stop
User walks along a familiar sidewalk toward a bus stop. Encounters pedestrians, potential upper-body obstacles (signs, branches), and increased movement near the stop. The collar provides directional haptic cues so the user can walk confidently without relying solely on hearing and a cane.

**Journey (with device):**
1. Device turned on → double pulse confirms active state
2. Walking, no vibration → user trusts silence as "clear"
3. Person approaches from left → soft pulse on left shoulder → user adjusts path without stopping
4. Upper-body obstacle ahead → steady chest vibration → user shifts
5. Nearing busy bus stop → light pulses both shoulders → aware without overwhelmed
6. User taps collar → circular sweep confirms system still working

### Use Case 2 — Passing a Narrow Blocked Sidewalk
User encounters a sidewalk partially blocked by a parked scooter or bin. Cannot tell where handlebars, mirrors, or other chest-height protrusions are. Needs to find the safer side and navigate through.

**Journey (with device):**
1. Device on → double pulse confirmation
2. Obstacle detected ahead → steady front vibration → user slows
3. Stronger right-side vibration + lighter left → gap is on the left
4. Moving through → vibrations shift around collar tracking body position
5. Clear → vibrations stop → safe to resume normal pace
6. User taps for reassurance → confirmation sweep

---

## 6. Hardware Architecture

### Component Roles

| Component | Qty | Status | Role |
|---|---|---|---|
| Raspberry Pi 4 Model B | 1 | ✓ confirmed | Central compute: runs server, ML inference, sensor fusion |
| Arduino Nano Every | 1 | ✓ confirmed | Haptic controller: receives commands from Pi, drives motors |
| VL53L0X ToF Distance Sensor | 4 | ✓ confirmed | Proximity sensing: front, back, left, right (range ~2–2000mm) |
| ProXtend X301 Full HD Webcam | 2 | ✓ confirmed | Object detection input: front-facing + back-facing |
| DFRobot FIT0774 Mini Vibration Motor | 5–8 | ✓ confirmed (qty TBD) | Haptic output at body zones |
| Generic Mini Vibration Motor | 1 | ✓ confirmed | 6th motor (system state / spare) |
| DFRobot DFR0440 Vibration Module | 2 | ✓ confirmed (Anna: use 2) | Driver modules |
| 2N3904 NPN Transistor | 8+ | ✓ confirmed | Motor switching — need 1 per motor |
| Flyback Diode | 10+ | ✓ confirmed | Motor protection — need 1 per motor |
| 1kΩ Resistor | 10+ | ✓ confirmed | Base resistors — need 1 per motor |
| AKY-LP502248 Li-Po 3.7V 450mAh | 1 | ⚠ unconfirmed | Portable power for motors/Arduino |
| TP4056 Charging Module | 1 | ⚠ unconfirmed | Li-Po charge management |
| Speaker (small) | 4 | ⚠ pending test 2026-04-10 | Voice alerts: 2 front, 2 back — volume TBD |
| Microphone (USB) | 1 | ✗ not yet acquired | Required if wake-word voice assistant added |

### System Architecture

```
[VL53L0X x4]──I²C──┐
                    ├──[Raspberry Pi 4]──USB Serial──[Arduino Nano Every]──[Motor Drivers]──[Vibration Motors x5-6]
[Webcam FRONT]──USB─┤         │
[Webcam BACK]───USB─┘         │
                              └──WiFi──[Dashboard Browser]
                                       (monitoring + manual override)
```

### Communication Protocols
- **VL53L0X → Pi**: I²C (all 4 sensors on same bus with different addresses via XSHUT pins)
- **Webcams → Pi**: USB (UVC, OpenCV capture)
- **Pi → Arduino**: USB Serial (commands: motor ID + pattern + intensity)
- **Pi → Dashboard**: Socket.IO over WiFi (existing server.js)

### Vibration Motor Placement (5 zones)

```
      [FRONT]
  [LEFT] · [RIGHT]
      [BACK]
      [STATE]  ← 5th motor: startup / system-check / error signals
```

Motors must be positioned so vibration is felt through clothing and not confused with each other. Front = collarbone area. Left/Right = shoulders. Back = upper back. State = distinct location (e.g. mid-back or sternum).

### Motor Driver Circuit (per motor)
```
Pi/Arduino GPIO ──[1kΩ]── 2N3904 Base
                          Collector ──[Motor +] ── [Flyback Diode] ── VCC
                          Emitter ── GND
```

---

## 7. Software Architecture

### Overview

The existing Node.js prototype (`server.js`) is retained and extended. The phone-based approach is **replaced** by Pi + webcams + Arduino.

```
server.js (Node.js / Express / Socket.IO)
│
├── /dashboard  → dashboard.html  (monitoring + manual control)
├── /front      → [replaced by Pi sensor pipeline]
└── /back       → [replaced by Pi sensor pipeline]
```

### Pi Sensor Pipeline (new: `sensor_bridge.py` or similar)

```
Loop:
  1. Read VL53L0X distances (front, left, right, back)
  2. Grab webcam frames (front, back)
  3. Run ML inference on frames (COCO-SSD / YOLOv5/v8 lite)
  4. Fuse: camera detections + ToF distances → spatial map
  5. Determine: threat level + direction for each zone
  6. Send haptic command → Arduino via Serial
  7. Emit spatial-update → Socket.IO server (for dashboard)
```

### Threat Classification (MVP)

Keep it to 3 categories maximum:

| Category | Trigger | Haptic pattern |
|---|---|---|
| `safe` | Nothing detected / far away | Silence |
| `notice` | Person or slow-moving object | 1 gentle tap / 3s |
| `warning` | Static obstacle in path | Double tap / 1.5s (steady for close proximity) |
| `danger` | Fast-approaching object / very close obstacle | Triple burst / 0.9s |
| `system` | Startup / check / error (not spatial) | Distinct patterns — see Section 8 |

**Do not attempt** to classify bikes vs cars vs signs vs branches reliably. The prototype only needs: static obstacle / person or moving object / high urgency.

### Arduino Serial Protocol (proposed)

Simple text or binary commands from Pi:

```
# Activate zone with level
ZONE <zone_id> <level>
# zone_id: 0=front, 1=left, 2=right, 3=back, 4=state
# level: 0=off, 1=notice, 2=warning, 3=danger

# System patterns (bypass spatial zones)
SYS <pattern_id>
# pattern_id: 0=startup, 1=check, 2=error
```

Arduino maintains its own timing loops for vibration patterns — Pi just sends events.

### Dashboard (existing — keep + minor extensions)
- Already works: camera feeds, detection list, body map, auto/manual mode
- **Add**: serial port status indicator (Arduino connected?)
- **Add**: ToF sensor readings per direction
- **Keep**: manual override controls (critical for exhibition Wizard of Oz fallback)

### AI / ML Requirements (MVP scope)

**Must have:**
- Object detection on webcam frames (COCO-SSD via TensorFlow Lite, or YOLOv8n)
- Classify: person, static obstacle, fast-moving object
- Direction from camera: left 1/3, center, right 1/3 of frame
- Motion estimation: frame-to-frame bounding box delta to distinguish moving vs static

**Should have:**
- Stair / step detection (already in phone.html — port to Pi)
- Floor-level obstacle detection

**Do not attempt:**
- Fine-grained object categories (bus vs bike vs sign)
- Scene understanding beyond detection + proximity

**Model recommendation:** YOLOv8n (fastest, Raspberry Pi 4 can do ~4–8fps), or TF Lite MobileNetSSD.

---

## 8. Haptic Language Specification

### Core Principle
Vibration = spatial direction. Pattern/intensity = urgency. Silence = safe.

The user should not need to memorize codes. The mapping should be intuitive from the first use.

### Spatial Patterns

| Signal | Pattern | Meaning |
|---|---|---|
| Gentle tap | `[25ms on]` every 3s | Person or mild presence nearby |
| Double tap | `[50ms, 80ms gap, 50ms]` every 1.5s | Static obstacle in path |
| Triple burst | `[120, 60, 120, 60, 120ms]` every 0.9s | Fast-approaching / high urgency |
| Continuous | `[sustained]` proportional to distance | Very close obstacle — immediate |

### System/State Patterns (zone 4 — state motor)

| Signal | Pattern | Meaning |
|---|---|---|
| Startup | 2 gentle pulses | Device is on and ready |
| System check | Circular sweep F→L→B→R→F | All zones functioning |
| Error/fault | Irregular stuttering pattern | Sensor blocked / module disconnected / low battery |

### Intensity ↔ Distance Mapping (VL53L0X)
```
> 150cm  → no signal
100–150cm → notice (1 tap)
 50–100cm → warning (double tap)
   < 50cm → danger (triple burst)
```
Fine-tune these thresholds during testing. The camera-based detections override distance-only if a more specific classification is available.

### Anti-overload Rules
- Maximum 2 zones active simultaneously
- If >2 zones trigger, prioritize: front > danger level > closest distance
- No signal = safe state (do not add "heartbeat" pulses unless testing reveals users need reassurance)
- Haptic scheduler must require **5 consecutive danger frames** before firing danger, and **12 consecutive safe frames** before releasing (already implemented in phone.html — port this logic)

---

## 9. Physical & Wearable Design Requirements

### Form Factor
- Collar worn around neck and shoulders — not tight on neck, weight distributed to shoulders
- Must fit over coats, hoodies, jackets
- Must be wearable/removable independently by user
- Should not excessively restrict neck movement

### Material Layer Structure
```
[Outer] Faux-fur / fleece — hides electronics, soft appearance
[Middle] Foam / neoprene / spacer mesh — structural support, component housing
[Inner] Soft lining — against skin/clothing, low irritation
[Windows] Trimmed pile or mesh patches over camera lenses and ToF sensors
```

### Component Integration
- 2 webcams: front-facing and back-facing, unobstructed sight lines through collar
- 4 VL53L0X sensors: pointing front, back, left shoulder, right shoulder
- 5–6 vibration motors: sewn/embedded at defined zones, direct contact through lining
- Wiring: routed inside collar structure, exits to Pi/Arduino in a pocket or bag
- Power cable: exits collar discreetly to Li-Po battery pack (external for prototype)

### Comfort Requirements (must)
- Soft or non-irritating against skin and clothing
- Not overly heavy (Raspberry Pi should be external, not on collar)
- Collar structure should not require precise fit to function
- Comfortable for a minimum 30-minute demo session

---

## 10. Trust & System State Requirements

The user must always know whether the collar is active and functioning. Confusion between "no obstacles detected" and "system is broken" is a critical failure.

| State | Required signal | Implementation |
|---|---|---|
| **Power on** | Double pulse on state motor | Fired once on Arduino init |
| **Active / safe** | Silence (no vibration) | Default state — silence means "clear" |
| **User check** | Tap gesture → circular sweep | Capacitive or physical button triggers SYS 1 command |
| **Error / fault** | Distinct stuttering pattern on state motor | Fired when: sensor timeout, serial disconnect, low battery |
| **Mode change** | Brief confirmation pulse | When switching auto ↔ manual on dashboard |

**Design rule:** State signals must be *unmistakably different* from spatial navigation signals in both location (state motor) and rhythm (irregular pattern vs regular pulses).

---

## 11. Phase 1 — Class Deadline (16 April 2026) ~80%

Everything below must work reliably before the class ends. Can be rough around the edges but must demonstrate the full concept.

### Must be working by April 16

**Hardware:**
- [ ] All 5+ vibration motors wired, tested, addressable individually from Arduino
- [ ] Arduino receiving serial commands from Pi and firing correct motor patterns
- [ ] At least 2 VL53L0X sensors reading distances (front + one side)
- [ ] At least 1 webcam feeding ML inference on Pi
- [ ] Li-Po battery powering motor circuit
- [ ] Collar form factor assembled — wearable for a short demo

**Software:**
- [ ] Pi sensor pipeline running: webcam inference + VL53L0X reads
- [ ] Sensor fusion producing a threat level + direction per zone
- [ ] Serial commands sent from Pi to Arduino
- [ ] Dashboard showing live data (existing + ToF readings)
- [ ] Startup confirmation pulse working
- [ ] System check gesture working

**Haptic:**
- [ ] At least 3 signal types distinguishable: safe / obstacle / danger
- [ ] Direction correctly maps to motor location
- [ ] Anti-overload (max 2 zones active) implemented

---

## 12. Phase 2 — Exhibition (30 May 2026) 100% stable

The additional 20% is about reliability, polish, and demo experience — not new features.

### Must be exhibition-ready by May 30

**Reliability:**
- [ ] System runs continuously for 30+ minutes without crash
- [ ] Graceful recovery if a sensor disconnects or camera feed drops
- [ ] Error signal fires reliably on fault conditions
- [ ] All 4 VL53L0X sensors working in all directions
- [ ] Both webcams feeding inference simultaneously
- [ ] Motor patterns feel smooth and clearly distinguishable through clothing

**Physical:**
- [ ] Collar finished — clean, wearable, aesthetically cohesive
- [ ] All wiring hidden or managed neatly
- [ ] Sensors and cameras properly mounted with unobstructed windows
- [ ] Can be put on independently and demonstrated without discomfort

**Demo experience:**
- [ ] Two scenarios demonstrable end-to-end (bus stop walk, blocked sidewalk)
- [ ] Dashboard available for exhibition observers to see what the device detects
- [ ] Manual override available as a fallback (Wizard of Oz) if autonomous sensing has issues
- [ ] Quick-start: device boots and is ready in under 2 minutes

---

## 13. Success Criteria

### Prototype is successful if:

**User experience:**
- A person wearing it (eyes closed or blindfolded) can tell which *direction* a threat is coming from, without being told
- They can distinguish at least "something nearby" vs "urgent/fast threat"
- They understand and trust silence as "safe"
- They can trigger and recognize the system-check sweep

**Technical:**
- Correct direction fires with >80% accuracy in controlled demo conditions
- No more than 2 simultaneous zone activations
- System check completes reliably within 1 second of trigger

**Design:**
- Collar looks like a wearable accessory, not a DIY electronics project
- Can be demonstrated on a person without discomfort

**Exhibition:**
- Audience understands the concept within 30 seconds of explanation
- Live demo clearly shows value over cane-only navigation
- At least one scenario runs end-to-end without manual intervention

---

## 14. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Pi too slow for real-time ML + I²C + serial simultaneously | Medium | High | Use YOLOv8n (fastest), limit inference to 5fps, use threading |
| VL53L0X I²C address conflicts | Medium | Medium | Use XSHUT pins to assign unique addresses at boot |
| Motors too weak to feel through thick clothing | Medium | High | Test early on different fabric thicknesses; use stronger motor if needed |
| Wiring causes collar to be too stiff / heavy | Medium | Medium | Route Pi/battery externally; only motors + sensors in collar |
| Camera obstructed by fur material | Low | High | Cut precise sensor windows; test detection accuracy early |
| Haptic language too complex / confusing | Low | High | Max 3 spatial patterns; user test early with blindfold |
| Arduino serial communication unreliable | Low | Medium | Add heartbeat / handshake; implement retry logic |
| Dashboard not useful at exhibition | Low | Low | Already built; just ensure it's visible on a second screen |

---

## 15. Open Questions (decide before April 16)

- [ ] **ToF sensor mount angles**: Are all 4 sensors pointing horizontally, or angled slightly downward?
- [ ] **Tap/check gesture**: Physical button on collar vs capacitive touch vs specific vibration pattern held?
- [ ] **Camera orientation**: Are webcams mounted horizontally or at a slight upward angle to capture head-height obstacles better?
- [ ] **Pi external or in collar**: Confirm Pi + battery live in a bag/pocket, not on collar itself
- [ ] **Silence as safe**: Is silence sufficient as the "working" state signal, or do we need a periodic subtle heartbeat? (test with users)
- [ ] **Motor placement confirmation**: Finalize exact positions of all 5 motors on collar template before sewing

---

## 16. Future Directions (post-exhibition, not in scope now)

- Fully embedded electronics (miniaturized PCB, no external Pi)
- Full 360° radar/ultrasonic sensing alongside cameras
- Adaptive haptic thresholds that learn user preferences
- Integration with white cane (complementary, not competing)
- Washable/detachable textile shell
- Longer-term user testing with visually impaired participants
- Modular seasonal covers (summer mesh vs winter fur)
