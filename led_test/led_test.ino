/*
 * LED wiring sweep
 *
 * Lights ONE pin at a time for 2 s and prints which pin it is. Watch the LEDs:
 *
 *   - an LED lights on the pin named in the monitor  -> it is plugged into that
 *     pin, not 26/27. Tell me the number and I will move the firmware to it.
 *   - no LED ever lights on any pin                 -> polarity, resistor or a
 *     broken breadboard ground rail. See notes below.
 *
 * Avoided on purpose: 6-11 (internal flash), 5/18/19/21/22/23 (RC522),
 * 13 (servo), 16/17 (PSRAM on WROVER modules).
 */

const int SWEEP[] = {26, 27, 25, 32, 33, 14, 4, 15, 2};
const int N = sizeof(SWEEP) / sizeof(SWEEP[0]);

void allLow() {
  for (int i = 0; i < N; i++) {
    pinMode(SWEEP[i], OUTPUT);
    digitalWrite(SWEEP[i], LOW);
  }
}

void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println();
  Serial.println("=== LED sweep: ONE pin at a time, 2 s each ===");
  allLow();
}

void loop() {
  for (int i = 0; i < N; i++) {
    int pin = SWEEP[i];
    digitalWrite(pin, HIGH);
    delay(60);
    Serial.printf("GPIO %-2d HIGH   read back %d\n", pin, digitalRead(pin));
    delay(2000);
    digitalWrite(pin, LOW);
    delay(250);
  }
  Serial.println("--- sweep done, repeating ---\n");
}
