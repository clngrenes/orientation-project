/*
 * ORIENTATION — Motor Controller
 * 6 vibration motors + 4 VL53L0X distance sensors
 *
 * Motor layout on collar:
 *          FRONT
 *       [F — DFRobot]    pin 9
 *   FL(coin)    FR(coin) pins 3, 5
 *   BL(coin)    BR(coin) pins 6, 11
 *       [B — DFRobot]    pin 10
 *          BACK
 *
 * XSHUT pins for VL53L0X: D2, D4, D7, D8
 * (pins 7+8 are XSHUT — NOT motor pins!)
 *
 * Commands from Pi (serial, 9600 baud):
 *   ZONE:X:Y    X = motor zone 0-5, Y = level 0-3
 *   STAIR       all 6 motors: 5 rapid pulses (stair warning)
 *   BEAT        short pulse on F+FL+FR (heartbeat, system alive)
 *
 * Zone IDs:
 *   0 = F  (DFRobot Front,  pin 9)
 *   1 = FR (Coin FrontRight, pin 5)
 *   2 = FL (Coin FrontLeft,  pin 3)
 *   3 = BL (Coin BackLeft,   pin 6)
 *   4 = BR (Coin BackRight,  pin 11)
 *   5 = B  (DFRobot Back,   pin 10)
 *
 * Pulsing (non-blocking, millis-based):
 *   Level 0: silent
 *   Level 1 (Notice):  800ms period, 30ms ON
 *   Level 2 (Warning): 400ms period, 60ms ON
 *   Level 3 (Danger):  150ms period, 100ms ON
 */

#include <Wire.h>
#include <VL53L0X.h>

// ── Motors ──────────────────────────────────────────────────────────────────
const int NUM_MOTORS = 6;
const int MOTOR_PINS[NUM_MOTORS] = {9, 5, 3, 6, 11, 10};
// Zone:                            F  FR  FL  BL  BR   B

// Pulse timing per level [period_ms, on_ms]
const unsigned long PERIOD_MS[4] = {0,   800, 400, 150};
const unsigned long ON_MS[4]     = {0,   30,  60,  100};

// Per-motor state
int          motorLevel[NUM_MOTORS]      = {0};
unsigned long lastPeriodStart[NUM_MOTORS] = {0};
bool          pulseOn[NUM_MOTORS]         = {false};

// ── VL53L0X sensors ──────────────────────────────────────────────────────────
const int NUM_SENSORS = 4;
const int XSHUT_PINS[NUM_SENSORS]      = {2, 4, 7, 8};
const uint8_t SENSOR_ADDRS[NUM_SENSORS] = {0x30, 0x31, 0x32, 0x33};
VL53L0X sensors[NUM_SENSORS];
bool    sensorOK[NUM_SENSORS];

// ── Serial buffer ────────────────────────────────────────────────────────────
char buf[32];
int  bufPos = 0;

// ── Forward declarations ─────────────────────────────────────────────────────
void handleCommand();
void updateMotors();
void playStair();
void playBeat();

// ────────────────────────────────────────────────────────────────────────────

void setup() {
  Serial.begin(9600);

  // Motor pins
  for (int i = 0; i < NUM_MOTORS; i++) {
    pinMode(MOTOR_PINS[i], OUTPUT);
    digitalWrite(MOTOR_PINS[i], LOW);
  }

  // XSHUT pins — pull all LOW first (all sensors off)
  for (int i = 0; i < NUM_SENSORS; i++) {
    pinMode(XSHUT_PINS[i], OUTPUT);
    digitalWrite(XSHUT_PINS[i], LOW);
    sensorOK[i] = false;
  }
  delay(10);

  Wire.begin();

  // Boot sensors one by one, assign unique I2C addresses
  for (int i = 0; i < NUM_SENSORS; i++) {
    digitalWrite(XSHUT_PINS[i], HIGH);
    delay(10);
    sensors[i].setTimeout(500);
    if (sensors[i].init()) {
      sensors[i].setAddress(SENSOR_ADDRS[i]);
      sensors[i].startContinuous();
      sensorOK[i] = true;
      Serial.print("DEBUG: Sensor ");
      Serial.print(i);
      Serial.println(" OK");
    } else {
      Serial.print("DEBUG: Sensor ");
      Serial.print(i);
      Serial.println(" FAILED");
    }
  }

  // Startup beat — 2 short pulses on front motors
  playBeat();
  delay(300);
  playBeat();
}

// ── Non-blocking motor pulsing ───────────────────────────────────────────────

void updateMotors() {
  unsigned long now = millis();
  for (int i = 0; i < NUM_MOTORS; i++) {
    int lvl = motorLevel[i];
    if (lvl == 0) {
      if (pulseOn[i]) {
        digitalWrite(MOTOR_PINS[i], LOW);
        pulseOn[i] = false;
      }
      continue;
    }
    unsigned long elapsed = now - lastPeriodStart[i];
    if (!pulseOn[i]) {
      // Start new pulse when period elapsed
      if (elapsed >= PERIOD_MS[lvl]) {
        digitalWrite(MOTOR_PINS[i], HIGH);
        pulseOn[i] = true;
        lastPeriodStart[i] = now;
      }
    } else {
      // End pulse when on-time elapsed
      if (elapsed >= ON_MS[lvl]) {
        digitalWrite(MOTOR_PINS[i], LOW);
        pulseOn[i] = false;
      }
    }
  }
}

// ── Special patterns (use delay — intentional one-shot events) ───────────────

void playStair() {
  // All 6 motors: 5 rapid pulses — unmistakable stair warning
  for (int p = 0; p < 5; p++) {
    for (int i = 0; i < NUM_MOTORS; i++) digitalWrite(MOTOR_PINS[i], HIGH);
    delay(80);
    for (int i = 0; i < NUM_MOTORS; i++) digitalWrite(MOTOR_PINS[i], LOW);
    delay(60);
  }
}

void playBeat() {
  // Front motors only: single 40ms pulse (system alive)
  // F=0, FR=1, FL=2
  digitalWrite(MOTOR_PINS[0], HIGH);
  digitalWrite(MOTOR_PINS[1], HIGH);
  digitalWrite(MOTOR_PINS[2], HIGH);
  delay(40);
  digitalWrite(MOTOR_PINS[0], LOW);
  digitalWrite(MOTOR_PINS[1], LOW);
  digitalWrite(MOTOR_PINS[2], LOW);
}

// ── Serial command handling ──────────────────────────────────────────────────

void handleCommand() {
  // ZONE:X:Y
  if (buf[0]=='Z' && buf[1]=='O' && buf[2]=='N' && buf[3]=='E') {
    int zone  = buf[5] - '0';
    int level = buf[7] - '0';
    if (zone >= 0 && zone < NUM_MOTORS && level >= 0 && level <= 3) {
      motorLevel[zone] = level;
      // Reset pulse timing so new level takes effect immediately
      lastPeriodStart[zone] = millis() - PERIOD_MS[max(level, 1)];
      pulseOn[zone] = false;
      digitalWrite(MOTOR_PINS[zone], LOW);
    }
  }
  // STAIR
  else if (buf[0]=='S' && buf[1]=='T' && buf[2]=='A') {
    playStair();
  }
  // BEAT
  else if (buf[0]=='B' && buf[1]=='E' && buf[2]=='A') {
    playBeat();
  }
}

// ── TOF sensor reading ───────────────────────────────────────────────────────

unsigned long lastTof = 0;

void readAndSendTof() {
  if (millis() - lastTof < 200) return;
  lastTof = millis();
  for (int i = 0; i < NUM_SENSORS; i++) {
    if (sensorOK[i]) {
      int dist = sensors[i].readRangeContinuousMillimeters();
      if (!sensors[i].timeoutOccurred()) {
        Serial.print("TOF");
        Serial.print(i);
        Serial.print(":");
        Serial.println(dist);
      }
    }
  }
}

// ── Main loop ────────────────────────────────────────────────────────────────

void loop() {
  // Read serial commands
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (bufPos > 0) {
        buf[bufPos] = '\0';
        handleCommand();
        bufPos = 0;
      }
    } else if (bufPos < 31) {
      buf[bufPos++] = c;
    }
  }

  // Update motor pulsing (non-blocking)
  updateMotors();

  // Send sensor readings
  readAndSendTof();
}
