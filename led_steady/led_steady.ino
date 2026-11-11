/*
 * LED steady-on test
 *
 * Holds GPIO 26 (green) and GPIO 27 (red) HIGH forever, instead of sweeping.
 * Use this when you need to watch the LED without worrying about timing, or
 * when you want to measure voltages along the path with a multimeter.
 *
 * Expected voltages when the wiring is correct (3.3 V logic):
 *   GPIO pin            ~3.3 V
 *   other end of R      ~3.2 V
 *   LED long leg        ~3.2 V
 *   LED short leg        0 V
 *   LED across its legs ~1.8-2.0 V
 */

const int GREEN = 26;
const int RED   = 27;

void setup() {
  Serial.begin(115200);
  delay(300);
  pinMode(GREEN, OUTPUT);
  pinMode(RED, OUTPUT);
  digitalWrite(GREEN, HIGH);
  digitalWrite(RED, HIGH);
  Serial.println();
  Serial.printf("STEADY ON - GPIO 26 = %d, GPIO 27 = %d\n", digitalRead(GREEN), digitalRead(RED));
  Serial.println("Both LEDs should be lit continuously. Nothing else will change.");
}

void loop() {
  static unsigned long last = 0;
  if (millis() - last > 5000) {
    last = millis();
    Serial.printf("still HIGH: 26=%d 27=%d\n", digitalRead(GREEN), digitalRead(RED));
  }
}
