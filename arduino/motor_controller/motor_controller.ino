#include <Wire.h>
#include <VL53L0X.h>

// --- Motor pins ---
const int MOTOR_PIN  = 9;
const int MOTOR_PIN2 = 10;

// --- VL53L0X: 4 sensors via XSHUT pins ---
// Each sensor starts at 0x29; we boot them one by one and assign new addresses.
const int NUM_SENSORS = 4;
const int XSHUT_PINS[NUM_SENSORS] = {2, 3, 4, 5};
const uint8_t SENSOR_ADDRS[NUM_SENSORS] = {0x30, 0x31, 0x32, 0x33};
VL53L0X sensors[NUM_SENSORS];
bool sensorOK[NUM_SENSORS];

// --- Serial command buffer ---
char buf[32];
int bufPos = 0;

void setup() {
  Serial.begin(9600);
  pinMode(MOTOR_PIN,  OUTPUT);
  pinMode(MOTOR_PIN2, OUTPUT);

  // Pull all XSHUT LOW → all sensors off
  for (int i = 0; i < NUM_SENSORS; i++) {
    pinMode(XSHUT_PINS[i], OUTPUT);
    digitalWrite(XSHUT_PINS[i], LOW);
    sensorOK[i] = false;
  }
  delay(10);

  Wire.begin();

  // Boot each sensor individually and assign unique address
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

  // Startup pulse on both motors
  digitalWrite(MOTOR_PIN, HIGH); delay(150);
  digitalWrite(MOTOR_PIN, LOW);  delay(150);
  digitalWrite(MOTOR_PIN, HIGH); delay(150);
  digitalWrite(MOTOR_PIN, LOW);
}

void vibrate(int pin, int level) {
  if (level == 0) {
    digitalWrite(pin, LOW);
  } else if (level == 1) {
    digitalWrite(pin, HIGH); delay(25);
    digitalWrite(pin, LOW);
  } else if (level == 2) {
    digitalWrite(pin, HIGH); delay(50);
    digitalWrite(pin, LOW);  delay(80);
    digitalWrite(pin, HIGH); delay(50);
    digitalWrite(pin, LOW);
  } else if (level == 3) {
    digitalWrite(pin, HIGH); delay(120);
    digitalWrite(pin, LOW);  delay(60);
    digitalWrite(pin, HIGH); delay(120);
    digitalWrite(pin, LOW);  delay(60);
    digitalWrite(pin, HIGH); delay(120);
    digitalWrite(pin, LOW);
  }
}

// Command format: "ZONE:X:Y\n"  X = zone (0 or 1), Y = level (0-3)
// Legacy format still supported: "ZONE:0:Y" → motor pin 9
void handleCommand() {
  if (buf[0]=='Z' && buf[1]=='O') {
    // New format: ZONE:X:Y
    int zone  = buf[5] - '0';
    int level = buf[7] - '0';
    if (zone == 0) vibrate(MOTOR_PIN,  level);
    if (zone == 1) vibrate(MOTOR_PIN2, level);
  }
}

unsigned long lastTof = 0;

void loop() {
  // Read serial commands from Pi
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

  // Send all sensor readings every 200ms
  if (millis() - lastTof > 200) {
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
}
