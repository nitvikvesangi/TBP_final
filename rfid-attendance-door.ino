/*
 * ============================================================================
 *  RFID Attendance + Door Access  -  ESP32 firmware v2
 *  MFRC522 reader (SPI) + SG90 servo + optional Wi-Fi upload
 *  Theme: Cybersecurity & Digital Forensics
 *
 *  ONE SCAN, TWO JOBS
 *    1. DOOR   registered card -> unlocks for UNLOCK_MS, then relocks
 *              unknown card    -> stays locked, event logged DENIED
 *    2. RECORD one attendance event per session, timestamped, queued in flash
 *
 *  WHY THIS VERSION IS "CONNECT AND IT WORKS"
 *    - the roster lives in flash, so you add cards without reflashing
 *    - no Wi-Fi at all is a valid configuration (offline queue)
 *    - Wi-Fi is retried in the background, never blocks a scan
 *    - records are only deleted from the queue after a 2xx from the server
 *    - an optional shared token stops random devices posting to your server
 *
 *  SERIAL CONSOLE (115200 baud) - type "help"
 * ============================================================================
 */

#include <SPI.h>
#include <MFRC522.h>
#include <ESP32Servo.h>
#include <LittleFS.h>
#include <WiFi.h>
#include <time.h>
#include <HTTPClient.h>

/* ------------------------------ 1. PINS ---------------------------------- */
#define SS_PIN      5      // RC522 SDA / chip select
#define RST_PIN     22     // RC522 RST (matches the physical wiring)
#define SERVO_PIN   13     // servo signal
#define LED_GREEN   26     // green: access granted (0.5 s pulse)
#define LED_RED     27     // red:   access denied (0.5 s)
// SPI on ESP32 defaults: SCK 18, MISO 19, MOSI 23

static const int SERVO_LOCKED   = 0;    // tune to your latch
static const int SERVO_UNLOCKED = 90;

/* ----------------------------- 2. TIMING --------------------------------- */
static const uint32_t UNLOCK_MS       = 5000;      // door stays open
static const uint32_t RE_READ_MS      = 3000;      // ignore a card left on the reader
static const uint32_t SESSION_MS      = 3600000;   // attendance window (1 h)
static const uint32_t PROXY_WINDOW_MS = 2000;      // on-device heuristic window
static const int      PROXY_DISTINCT  = 3;
static const uint32_t LED_DENY_MS     = 500;       // red shows a refusal - same length as green
static const uint32_t LED_GRANT_MS    = 500;       // green confirmation pulse
static const uint32_t SERVO_SETTLE_MS = 300;       // polling held off while the servo swings
static const uint32_t BUZZ_MS         = 200;       // each pulse of the grant nudge
static const uint32_t BUZZ_GAP_MS     = 150;       // pause between the two pulses
static const uint32_t FLUSH_EVERY_MS  = 20000;     // upload retry period
static const uint32_t WIFI_RETRY_MS   = 30000;     // reconnect attempt period

/* ------------------------ 3. NETWORK (OPTIONAL) -------------------------- */
/* Leave WIFI_SSID empty to run fully offline. Leave CLOUD_URL empty to never
   upload. Set CLOUD_TOKEN to the same value as the server's --token.            */
/* Credentials live in secrets.h, next to this sketch, and never in this file.
   Create it like this (it is git-ignored):

     #define WIFI_SSID    "MyHotspot"
     #define WIFI_PASS    "the-password"
     #define CLOUD_URL    "http://192.168.1.4:8080/api/scan"
     #define CLOUD_TOKEN  "S3cret"

   With no secrets.h the sketch still compiles and runs fully offline.        */
#if __has_include("secrets.h")
  #include "secrets.h"
#endif
#ifndef WIFI_SSID
  #define WIFI_SSID    ""
  #define WIFI_PASS    ""
  #define CLOUD_URL    ""
  #define CLOUD_TOKEN  ""
#endif
const long  GMT_OFFSET_SEC = 19800;   // IST (UTC+5:30)
const int   DST_OFFSET_SEC = 0;

/* ------------------------------ 4. FILES --------------------------------- */
static const char* QUEUE_PATH  = "/attendance.ndjson";
static const char* ROSTER_PATH = "/roster.txt";

/* ----------------------------- 5. ROSTER --------------------------------- */
/* Loaded from flash at boot. Seeded with four cards the first time only.
   Add cards from the serial console: register <uid> <roll> <name...>        */
static const int MAX_CARDS = 40;

struct Card {
  String   uid;
  String   name;
  String   roll;
  bool     present;
  uint32_t lastSeen;
};

Card roster[MAX_CARDS];
int  rosterN = 0;

/* ------------------------------ 6. STATE --------------------------------- */
MFRC522 rfid(SS_PIN, RST_PIN);
Servo   doorServo;

bool     doorOpen     = false;
uint32_t doorOpenedAt = 0;
uint32_t sessionStart = 0;
uint32_t lastFlushMs  = 0;
uint32_t lastWifiTry  = 0;
bool     fsReady      = false;
String   serialBuf    = "";

struct ScanMark { int idx; uint32_t ms; };
ScanMark recent[8];
int      recentCount = 0;

/* --------------------------- 7. UID HELPERS ------------------------------ */
String hexOnly(const String& raw) {
  String out;
  for (int i = 0; i < (int)raw.length(); i++) {
    char c = raw[i];
    if (c >= 'a' && c <= 'f') c = c - 'a' + 'A';
    if ((c >= '0' && c <= '9') || (c >= 'A' && c <= 'F')) out += c;
  }
  return out;
}

String formatUid(const String& raw) {
  String h = hexOnly(raw);
  String out;
  for (int i = 0; i + 1 < (int)h.length(); i += 2) {
    if (i) out += ' ';
    out += h.substring(i, i + 2);
  }
  return out;
}

String uidToString(byte* b, byte len) {
  String out;
  for (byte i = 0; i < len; i++) {
    if (i) out += ' ';
    if (b[i] < 0x10) out += '0';
    out += String(b[i], HEX);
  }
  out.toUpperCase();
  return out;
}

/* --------------------------- 8. ROSTER I/O ------------------------------- */
int findCard(const String& uid) {
  String key = hexOnly(uid);
  if (key.length() == 0) return -1;
  for (int i = 0; i < rosterN; i++) {
    if (hexOnly(roster[i].uid) == key) return i;
  }
  return -1;
}

bool saveRoster() {
  if (!fsReady) return false;
  File f = LittleFS.open(ROSTER_PATH, "w");
  if (!f) return false;
  for (int i = 0; i < rosterN; i++) {
    f.printf("%s|%s|%s\n", roster[i].uid.c_str(),
             roster[i].name.c_str(), roster[i].roll.c_str());
  }
  f.close();
  return true;
}

void addCard(const String& uid, const String& name, const String& roll, bool persist) {
  if (rosterN >= MAX_CARDS) return;
  roster[rosterN].uid      = formatUid(uid);
  roster[rosterN].name     = name;
  roster[rosterN].roll     = roll;
  roster[rosterN].present  = false;
  roster[rosterN].lastSeen = 0;
  rosterN++;
  if (persist) saveRoster();
}

void seedDefaults() {
  addCard("01 02 03 04", "Alice Sharma",  "CS-01", false);   // Wokwi Blue
  addCard("11 22 33 44", "Rohit Verma",   "CS-02", false);   // Wokwi Green
  addCard("55 66 77 88", "Sara Khan",     "CS-03", false);   // Wokwi Yellow
  addCard("AA BB CC DD", "Imran Qureshi", "CS-04", false);   // Wokwi Red
}

void loadRoster() {
  rosterN = 0;
  if (!fsReady) { seedDefaults(); return; }

  File f = LittleFS.open(ROSTER_PATH, "r");
  if (!f) { seedDefaults(); saveRoster(); return; }

  while (f.available() && rosterN < MAX_CARDS) {
    String line = f.readStringUntil('\n');
    line.trim();
    if (line.length() == 0) continue;
    int a = line.indexOf('|');
    int b = line.indexOf('|', a + 1);
    if (a < 0 || b < 0) continue;
    roster[rosterN].uid      = formatUid(line.substring(0, a));
    roster[rosterN].name     = line.substring(a + 1, b);
    roster[rosterN].roll     = line.substring(b + 1);
    roster[rosterN].present  = false;
    roster[rosterN].lastSeen = 0;
    rosterN++;
  }
  f.close();

  if (rosterN == 0) { seedDefaults(); saveRoster(); }
}

bool removeCard(const String& uid) {
  int i = findCard(uid);
  if (i < 0) return false;
  for (int j = i; j < rosterN - 1; j++) roster[j] = roster[j + 1];
  rosterN--;
  roster[rosterN].uid  = "";
  roster[rosterN].name = "";
  roster[rosterN].roll = "";
  saveRoster();
  return true;
}

/* --------------------------- 9. TIME ------------------------------------- */
bool timeReady() { return time(nullptr) > 1700000000; }   // later than Nov 2023

String isoNow() {
  time_t t = time(nullptr);
  struct tm tmv;
  localtime_r(&t, &tmv);
  char buf[32];
  strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%S", &tmv);
  return String(buf);
}

/* --------------------------- 10. DOOR ------------------------------------ */
/* An SG90 starting from rest pulls a current step on the 5 V rail, and SPI
   reads taken during that burst come back malformed or get dropped - which
   showed up as missed taps right after a door movement. Polling is suspended
   for SERVO_SETTLE_MS around each swing so the reader never samples mid-move. */
static uint32_t pollPausedUntil = 0;

void pausePolling(uint32_t ms) { pollPausedUntil = millis() + ms; }
bool pollingPaused()           { return (int32_t)(pollPausedUntil - millis()) > 0; }

void unlockDoor() {
  if (!doorOpen) {
    doorServo.write(SERVO_UNLOCKED);
    pausePolling(SERVO_SETTLE_MS);
    doorOpen = true;
    doorOpenedAt = millis();   // fixed window from the grant - never extended
    Serial.println("         door: UNLOCKED");
  }
}

void lockDoor() {
  if (doorOpen) {
    doorServo.write(SERVO_LOCKED);
    pausePolling(SERVO_SETTLE_MS);
    doorOpen = false;
    Serial.println("         door: LOCKED");
  }
}

/* --------------------------- 10a. GRANT NUDGE ---------------------------- */
/* The servo no longer holds the latch open. On a grant it gives a short
   two-pulse nudge instead: out, back, out, back. That keeps the read loop (and
   therefore the timing the proxy heuristic depends on) uninterrupted, and
   removes the held-open window that invited tailgating.
   To go back to a real swinging door, call unlockDoor() from handleCard()
   instead of startBuzz() — nothing else needs to change.                    */
static uint8_t  buzzStep = 0;      // 0 = idle
static uint32_t buzzAt   = 0;

void startBuzz() {
  if (buzzStep != 0) return;       // already nudging
  doorServo.write(SERVO_UNLOCKED);
  pausePolling(SERVO_SETTLE_MS);
  buzzAt   = millis() + BUZZ_MS;
  buzzStep = 1;
  Serial.println("         door: nudge (latch tapped, not held)");
}

void serviceBuzz() {
  if (buzzStep == 0 || millis() < buzzAt) return;
  switch (buzzStep) {
    case 1: doorServo.write(SERVO_LOCKED);   buzzAt = millis() + BUZZ_GAP_MS; buzzStep = 2; break;
    case 2: doorServo.write(SERVO_UNLOCKED); buzzAt = millis() + BUZZ_MS;     buzzStep = 3; break;
    default: doorServo.write(SERVO_LOCKED);  buzzStep = 0;                   break;
  }
  pausePolling(SERVO_SETTLE_MS);
}

void serviceDoor() {
  if (doorOpen && millis() - doorOpenedAt >= UNLOCK_MS) lockDoor();
}

/* --------------------------- 10b. LEDs ----------------------------------- */
/* Both LEDs confirm a SCAN, not the door. Green pulses 0.5 s on a grant and red
   flashes 0.5 s on a refusal. Driving green from door state made it a 5 s
   "walk straight through" lamp: people queue into the open window, the door is
   never given a chance to lock, and three of them land inside the proxy window
   and get flagged as proxy attendance.                                        */
static uint32_t redOffAt   = 0;
static uint32_t greenOffAt = 0;

void denyFlash() {
  digitalWrite(LED_RED, HIGH);
  redOffAt = millis() + LED_DENY_MS;
}

void grantFlash() {
  digitalWrite(LED_GREEN, HIGH);
  greenOffAt = millis() + LED_GRANT_MS;
}

void serviceLeds() {
  if (greenOffAt != 0 && millis() >= greenOffAt) {
    digitalWrite(LED_GREEN, LOW);
    greenOffAt = 0;
  }
  if (redOffAt != 0 && millis() >= redOffAt) {
    digitalWrite(LED_RED, LOW);
    redOffAt = 0;
  }
}

/* ------------------------ 11. UPLOAD + QUEUE ----------------------------- */
bool cloudEnabled() { return strlen(WIFI_SSID) > 0 && strlen(CLOUD_URL) > 0; }

bool postJson(const String& body) {
  HTTPClient http;
  http.setTimeout(4000);
  if (!http.begin(String(CLOUD_URL))) return false;
  http.addHeader("Content-Type", "application/json");
  if (strlen(CLOUD_TOKEN) > 0) http.addHeader("X-Device-Token", CLOUD_TOKEN);
  int code = http.POST(body);
  http.end();
  return (code >= 200 && code < 300);
}

/* Send queued records in order. A record is only removed once the server
   answers 2xx, so nothing is lost if the laptop is asleep.                  */
void flushQueue() {
  if (!cloudEnabled() || WiFi.status() != WL_CONNECTED || !fsReady) return;

  File f = LittleFS.open(QUEUE_PATH, "r");
  if (!f) return;
  String all = f.readString();
  f.close();
  if (all.length() == 0) return;

  String rest;
  int pos = 0;
  while (pos < (int)all.length()) {
    int nl = all.indexOf('\n', pos);
    if (nl < 0) nl = all.length();
    String line = all.substring(pos, nl);
    line.trim();
    pos = nl + 1;
    if (line.length() == 0) continue;

    if (rest.length() > 0) {          // an earlier record failed: keep order
      rest += line + "\n";
      continue;
    }
    if (!postJson(line)) rest += line + "\n";
    else delay(30);
  }

  File w = LittleFS.open(QUEUE_PATH, "w");
  if (w) { w.print(rest); w.close(); }
}

/* --------------------------- 12. EVENTS ---------------------------------- */
void logEvent(const String& uid, const String& name, const String& roll,
              const char* result, const char* attendance,
              bool suspect, bool simulated) {
  String ts;
  const char* src;
  if (timeReady()) { ts = isoNow(); src = "ntp"; }
  else             { ts = String("T+") + String(millis() / 1000UL) + "s"; src = "uptime"; }

  String json = "{";
  json += "\"uid\":\""        + uid  + "\",";
  json += "\"name\":\""       + name + "\",";
  json += "\"roll\":\""       + roll + "\",";
  json += "\"result\":\""     + String(result) + "\",";
  json += "\"attendance\":\"" + String(attendance) + "\",";
  json += "\"suspect\":"      + String(suspect ? "true" : "false") + ",";
  json += "\"simulated\":"    + String(simulated ? "true" : "false") + ",";
  json += "\"ts\":\""         + ts + "\",";
  json += "\"src\":\""        + String(src) + "\"";
  json += "}";

  Serial.printf("[%s] %-14s %-5s %-8s %-14s%s\n", ts.c_str(),
                name.length() ? name.c_str() : "-",
                roll.length() ? roll.c_str() : "-",
                result, attendance,
                suspect ? "  <<< PROXY SUSPECT" : "");
  Serial.println(json);

  if (fsReady) {
    File f = LittleFS.open(QUEUE_PATH, "a");
    if (f) { f.println(json); f.close(); }
  }
}

/* ---------------------- 13. ON-DEVICE HEURISTIC -------------------------- */
void rememberScan(int idx, uint32_t ms) {
  if (recentCount < 8) {
    recent[recentCount].idx = idx;
    recent[recentCount].ms  = ms;
    recentCount++;
  } else {
    for (int i = 1; i < 8; i++) recent[i - 1] = recent[i];
    recent[7].idx = idx;
    recent[7].ms  = ms;
  }
}

int distinctScannersInWindow(uint32_t now) {
  uint32_t mask = 0;
  for (int i = 0; i < recentCount; i++) {
    if (now - recent[i].ms <= PROXY_WINDOW_MS &&
        recent[i].idx >= 0 && recent[i].idx < 32) {
      mask |= (1UL << recent[i].idx);
    }
  }
  int n = 0;
  for (int b = 0; b < 32; b++) if (mask & (1UL << b)) n++;
  return n;
}

/* --------------------------- 14. SESSION --------------------------------- */
void startNewSession() {
  for (int i = 0; i < rosterN; i++) roster[i].present = false;
  sessionStart = millis();
  recentCount  = 0;
  Serial.println(">> new attendance session started (all students reset)");
}

/* ------------------------ 15. CARD HANDLING ------------------------------ */
void handleCard(const String& uid, bool simulated) {
  uint32_t now = millis();

  if (now - sessionStart >= SESSION_MS) startNewSession();

  int idx = findCard(uid);
  if (idx < 0) {
    denyFlash();
    Serial.println("         door: stays LOCKED (card not registered)");
    Serial.print("         UID = "); Serial.println(formatUid(uid));
    Serial.println("         ^ register it:  register <uid> <roll> <name>");
    logEvent(formatUid(uid), "", "", "DENIED", "NOT_RECORDED", false, simulated);
    return;
  }

  if (!simulated && roster[idx].lastSeen != 0 &&
      now - roster[idx].lastSeen < RE_READ_MS) {
    return;                       // card still resting on the reader
  }
  roster[idx].lastSeen = now;

  rememberScan(idx, now);
  bool suspect = distinctScannersInWindow(now) >= PROXY_DISTINCT;

  const char* attendance;
  if (roster[idx].present) {
    attendance = "ALREADY_MARKED";
  } else {
    roster[idx].present = true;
    attendance = "PRESENT";
  }

  grantFlash();
  startBuzz();
  logEvent(uid, roster[idx].name, roster[idx].roll,
           "GRANTED", attendance, suspect, simulated);

  if (suspect) {
    Serial.println("         !! " + String(PROXY_DISTINCT) + " different cards tapped within "
                   + String(PROXY_WINDOW_MS / 1000) + "s - possible proxy attendance");
  }
}

/* --------------------------- 16. CONSOLE --------------------------------- */
int tokenize(const String& cmd, String out[], int maxTok) {
  int n = 0, start = 0;
  int len = (int)cmd.length();
  for (int i = 0; i <= len; i++) {
    if (i == len || cmd[i] == ' ') {
      if (i > start && n < maxTok) out[n++] = cmd.substring(start, i);
      start = i + 1;
    }
  }
  return n;
}

bool isHexToken(const String& s) {
  if (s.length() < 2 || (s.length() % 2) != 0) return false;
  for (int i = 0; i < (int)s.length(); i++) {
    char c = s[i];
    bool ok = (c >= '0' && c <= '9') || (c >= 'A' && c <= 'F') || (c >= 'a' && c <= 'f');
    if (!ok) return false;
  }
  return true;
}

void printHelp() {
  Serial.println("commands:");
  Serial.println("  sim <uid>                      fake scan, e.g. sim AA BB CC DD");
  Serial.println("  register <uid> <roll> [name]   save a card to flash");
  Serial.println("  remove <uid>                   delete a card from flash");
  Serial.println("  list                           roster + who is present");
  Serial.println("  session                        new session, clears PRESENT");
  Serial.println("  queue                          count of un-uploaded records");
  Serial.println("  dump                           re-print queued records as JSON");
  Serial.println("  upload                         force a queue upload now");
  Serial.println("  unlock / lock                  test the servo only");
  Serial.println("  wifi                           network + time status");
  Serial.println("  reboot                         restart the ESP32");
  Serial.println("  help                           this list");
}

void printRoster() {
  int present = 0;
  Serial.println("-- roster --------------------------------------------");
  for (int i = 0; i < rosterN; i++) {
    if (roster[i].present) present++;
    Serial.printf("  %-14s %-5s %-16s %s\n",
                  roster[i].uid.c_str(), roster[i].roll.c_str(),
                  roster[i].name.c_str(), roster[i].present ? "PRESENT" : "-");
  }
  Serial.printf("-- %d of %d present\n", present, rosterN);
}

void printQueue() {
  if (!fsReady) { Serial.println("queue: flash unavailable"); return; }
  File f = LittleFS.open(QUEUE_PATH, "r");
  if (!f) { Serial.println("queue: 0 pending"); return; }
  int lines = 0;
  while (f.available()) {
    String l = f.readStringUntil('\n');
    l.trim();
    if (l.length()) lines++;
  }
  f.close();
  Serial.printf("queue: %d pending\n", lines);
}

void dumpQueue() {
  if (!fsReady) { Serial.println("queue: flash unavailable"); return; }
  File f = LittleFS.open(QUEUE_PATH, "r");
  if (!f) { Serial.println("queue: empty"); return; }
  Serial.println("<<<BEGIN-QUEUE>>>");
  while (f.available()) {
    String line = f.readStringUntil('\n');
    line.trim();
    if (line.length()) Serial.println(line);
  }
  f.close();
  Serial.println("<<<END-QUEUE>>>");
}

void printNetStatus() {
  Serial.printf("wifi: %s\n", WiFi.status() == WL_CONNECTED ? "connected" : "not connected");
  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("ip: "); Serial.println(WiFi.localIP());
    Serial.print("rssi: "); Serial.print(WiFi.RSSI()); Serial.println(" dBm");
  }
  Serial.printf("time: %s\n", timeReady() ? isoNow().c_str() : "not synced (uptime only)");
  Serial.printf("cloud url: %s\n", strlen(CLOUD_URL) ? CLOUD_URL : "(none - offline mode)");
  Serial.printf("token: %s\n", strlen(CLOUD_TOKEN) ? "set" : "not set");
}

void cmdRegister(const String& cmd) {
  String tok[12];
  int n = tokenize(cmd, tok, 12);

  int i = 1;
  String hexAcc;
  while (i < n && isHexToken(tok[i])) { hexAcc += hexOnly(tok[i]); i++; }
  if (hexAcc.length() < 8 || i >= n) {
    Serial.println("usage: register <uid> <roll> [name...]");
    Serial.println("   e.g. register 4A 1F 9C 2E CS-05 Priya Nair");
    return;
  }

  String uid  = formatUid(hexAcc);
  String roll = tok[i++];
  String name;
  for (; i < n; i++) {
    if (name.length()) name += ' ';
    name += tok[i];
  }
  if (name.length() == 0) name = roll;

  if (findCard(uid) >= 0) {
    Serial.printf("card %s is already registered\n", uid.c_str());
    return;
  }
  addCard(uid, name, roll, true);
  Serial.printf("registered %s -> %s (%s)\n", uid.c_str(), name.c_str(), roll.c_str());
}

void handleCommand(String cmd) {
  cmd.trim();
  String lower = cmd;
  lower.toLowerCase();

  if (lower == "help" || lower == "?") { printHelp(); return; }
  if (lower == "list")                 { printRoster(); return; }
  if (lower == "session")              { startNewSession(); return; }
  if (lower == "queue")                { printQueue(); return; }
  if (lower == "dump")                 { dumpQueue(); return; }
  if (lower == "upload")               { flushQueue(); Serial.println("upload: attempted"); return; }
  if (lower == "unlock")               { unlockDoor(); return; }
  if (lower == "lock")                 { lockDoor(); return; }
  if (lower == "wifi")                 { printNetStatus(); return; }
  if (lower == "reboot")               { Serial.println("rebooting..."); delay(200); ESP.restart(); }
  if (lower == "register")             { cmdRegister(cmd); return; }
  if (lower.startsWith("register "))   { cmdRegister(cmd); return; }
  if (lower.startsWith("remove ")) {
    String uid = formatUid(cmd.substring(7));
    Serial.println(removeCard(uid) ? "removed " + uid : "not found: " + uid);
    return;
  }
  if (lower.startsWith("sim")) {
    String uid = formatUid(cmd.substring(3));
    if (hexOnly(uid).length() < 8) { Serial.println("usage: sim AA BB CC DD"); return; }
    Serial.println("-- simulated scan --");
    handleCard(uid, true);
    return;
  }

  Serial.print("unknown command: "); Serial.println(cmd);
  printHelp();
}

void serviceSerial() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (serialBuf.length() > 0) { handleCommand(serialBuf); serialBuf = ""; }
    } else if (serialBuf.length() < 96) {
      serialBuf += c;
    }
  }
}

/* --------------------------- 17. NETWORK --------------------------------- */
void connectWifi(uint32_t timeoutMs) {
  if (!cloudEnabled()) {
    Serial.println("wifi: disabled (offline-only mode)");
    return;
  }
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASS);

  Serial.print("wifi: connecting");
  uint32_t t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < timeoutMs) {
    delay(300);
    Serial.print(".");
  }
  Serial.println();

  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("wifi: not connected - records will queue locally");
    return;
  }

  Serial.print("wifi: connected, ip "); Serial.println(WiFi.localIP());

  configTime(GMT_OFFSET_SEC, DST_OFFSET_SEC, "pool.ntp.org", "time.nist.gov");
  Serial.print("ntp: syncing");
  t0 = millis();
  while (!timeReady() && millis() - t0 < 10000) { delay(300); Serial.print("."); }
  Serial.println();
  Serial.println(timeReady() ? "ntp: ok" : "ntp: failed (records will use uptime)");
}

void serviceNetwork() {
  if (!cloudEnabled()) return;

  if (WiFi.status() == WL_CONNECTED) {
    if (!timeReady()) {
      configTime(GMT_OFFSET_SEC, DST_OFFSET_SEC, "pool.ntp.org", "time.nist.gov");
    }
    return;
  }
  if (millis() - lastWifiTry >= WIFI_RETRY_MS) {
    lastWifiTry = millis();
    Serial.println("wifi: retrying...");
    WiFi.reconnect();
  }
}

/* ---------------------------- 18. SETUP ---------------------------------- */
void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println();
  Serial.println("=== RFID Attendance + Door Access ===");

  pinMode(LED_GREEN, OUTPUT);
  pinMode(LED_RED, OUTPUT);
  digitalWrite(LED_GREEN, LOW);
  digitalWrite(LED_RED, LOW);

  doorServo.attach(SERVO_PIN);
  doorServo.write(SERVO_LOCKED);

  SPI.begin();
  rfid.PCD_Init();
  delay(50);

  byte v = rfid.PCD_ReadRegister(MFRC522::VersionReg);
  if (v == 0x00 || v == 0xFF) {
    Serial.println("rc522: NOT detected - check 3.3V, GND and SPI wires");
  } else {
    Serial.printf("rc522: ok (version 0x%02X)\n", v);
  }

  fsReady = LittleFS.begin(true);
  Serial.println(fsReady ? "flash: ok" : "flash: mount failed - roster and queue not saved");

  loadRoster();
  Serial.printf("roster: %d cards\n", rosterN);

  connectWifi(15000);
  startNewSession();

  Serial.println("System Ready - scan a card, or type 'help'");
}

/* ---------------------------- 19. LOOP ----------------------------------- */
void loop() {
  serviceSerial();
  serviceDoor();
  serviceBuzz();
  serviceLeds();
  serviceNetwork();

  if (millis() - lastFlushMs >= FLUSH_EVERY_MS) {
    lastFlushMs = millis();
    flushQueue();
  }

  if (pollingPaused()) { delay(10); return; }   // servo is moving - skip a read

  if (!rfid.PICC_IsNewCardPresent()) { delay(30); return; }
  if (!rfid.PICC_ReadCardSerial())   { delay(30); return; }

  String uid = uidToString(rfid.uid.uidByte, rfid.uid.size);
  rfid.PICC_HaltA();
  rfid.PCD_StopCrypto1();

  handleCard(uid, false);
  delay(100);
}
