#include <Wire.h>
#include <VL53L0X.h>

const int MOTOR_PIN = 9;
char buf[32];
int bufPos = 0;

VL53L0X sensor;
bool sensorOK = false;

void setup() {
  Serial.begin(9600);
  pinMode(MOTOR_PIN, OUTPUT);

  Wire.begin();
  Serial.println("DEBUG: Wire started");
  sensor.setTimeout(500);
  if (sensor.init()) {
    sensor.startContinuous();
    sensorOK = true;
    Serial.println("DEBUG: VL53L0X OK");
  } else {
    Serial.println("DEBUG: VL53L0X FAILED - check wiring");
  }

  // Startup pulse
  digitalWrite(MOTOR_PIN, HIGH); delay(150);
  digitalWrite(MOTOR_PIN, LOW);  delay(150);
  digitalWrite(MOTOR_PIN, HIGH); delay(150);
  digitalWrite(MOTOR_PIN, LOW);
}

void vibrate(int level) {
  if (level == 0) {
    digitalWrite(MOTOR_PIN, LOW);
  } else if (level == 1) {
    digitalWrite(MOTOR_PIN, HIGH); delay(25);
    digitalWrite(MOTOR_PIN, LOW);
  } else if (level == 2) {
    digitalWrite(MOTOR_PIN, HIGH); delay(50);
    digitalWrite(MOTOR_PIN, LOW);  delay(80);
    digitalWrite(MOTOR_PIN, HIGH); delay(50);
    digitalWrite(MOTOR_PIN, LOW);
  } else if (level == 3) {
    digitalWrite(MOTOR_PIN, HIGH); delay(120);
    digitalWrite(MOTOR_PIN, LOW);  delay(60);
    digitalWrite(MOTOR_PIN, HIGH); delay(120);
    digitalWrite(MOTOR_PIN, LOW);  delay(60);
    digitalWrite(MOTOR_PIN, HIGH); delay(120);
    digitalWrite(MOTOR_PIN, LOW);
  }
}

void handleCommand() {
  if (buf[0]=='Z' && buf[1]=='O') {
    int level = buf[7] - '0';
    vibrate(level);
  }
}

unsigned long lastTof = 0;

void loop() {
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

  if (sensorOK && millis() - lastTof > 200) {
    lastTof = millis();
    int dist = sensor.readRangeContinuousMillimeters();
    if (!sensor.timeoutOccurred()) {
      Serial.print("TOF:");
      Serial.println(dist);
    }
  }
}
