const int MOTOR_PIN = 9;
char buf[32];
int bufPos = 0;

void setup() {
  Serial.begin(9600);
  pinMode(MOTOR_PIN, OUTPUT);
  // Startup: 2 pulses
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
  // ZONE 0 3  → buf = "ZONE 0 3"
  if (buf[0]=='Z' && buf[1]=='O' && buf[4]==' ' && buf[6]==' ') {
    int level = buf[7] - '0';
    vibrate(level);
  }
  // SYS 0
  else if (buf[0]=='S' && buf[1]=='Y') {
    vibrate(3);
  }
}

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
}
