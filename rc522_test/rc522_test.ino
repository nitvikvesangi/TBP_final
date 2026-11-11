/*
 * ============================================================================
 *  RC522 WIRING TEST  -  ESP32
 *  Minimal sketch: no servo, no Wi-Fi, no flash. Just prove the reader works.
 *
 *  Board      : ESP32 Dev Module
 *  Serial     : 115200
 *  Library    : MFRC522 by GithubCommunity
 *
 *  PINS (match README.md section 1 exactly)
 *    SDA (SS) -> GPIO 5     SCK  -> GPIO 18
 *    MOSI     -> GPIO 23    MISO -> GPIO 19
 *    RST      -> GPIO 22
 *    3.3V     -> 3V3        GND  -> GND      (never 5V)
 *
 *  WHAT TO EXPECT
 *    "Firmware Version: 0x92" or 0x91  -> wiring is correct
 *    0x00 or 0xFF                      -> a wire is wrong or loose
 * ============================================================================
 */

#include <SPI.h>
#include <MFRC522.h>

#define SS_PIN   5     // RC522 SDA
#define RST_PIN  22    // RC522 RST

MFRC522 rfid(SS_PIN, RST_PIN);

void setup() {
  Serial.begin(115200);
  delay(300);

  // ESP32: SPI.begin(SCK, MISO, MOSI, SS)
  SPI.begin(18, 19, 23, SS_PIN);

  rfid.PCD_Init();
  delay(100);

  byte v = rfid.PCD_ReadRegister(MFRC522::VersionReg);
  rfid.PCD_DumpVersionToSerial();

  if (v == 0x00 || v == 0xFF) {
    Serial.println("RESULT: reader NOT responding - check 3.3V, GND, and the 5 SPI wires");
  } else {
    Serial.printf("RESULT: reader OK (version 0x%02X)\n", v);
  }

  Serial.println("Tap a card...");
}

void loop() {
  if (!rfid.PICC_IsNewCardPresent()) return;
  if (!rfid.PICC_ReadCardSerial())   return;

  Serial.print("UID:");
  for (byte i = 0; i < rfid.uid.size; i++) {
    Serial.printf(" %02X", rfid.uid.uidByte[i]);
  }
  Serial.println();

  rfid.PICC_HaltA();
  rfid.PCD_StopCrypto1();
  delay(200);
}
