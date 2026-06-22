#include <WiFi.h>
#include <WiFiUdp.h>
#include <esp_wifi.h>

namespace {
constexpr char AP_SSID[] = "GRADUATION_PROJECT";
constexpr char AP_PASSWORD[] = "12345678";
constexpr char BROADCAST_IP[] = "192.168.4.255";
constexpr uint8_t WIFI_CHANNEL = 11;
constexpr uint16_t UDP_PORT = 12345;
constexpr uint16_t SEND_INTERVAL_MS = 50;
constexpr int8_t TX_POWER = 8;

WiFiUDP udp;
}  // namespace

void setup() {
  Serial.begin(115200);
  WiFi.mode(WIFI_AP);
  WiFi.softAP(AP_SSID, AP_PASSWORD, WIFI_CHANNEL, false);

  // 일정한 패킷 주기 유지.
  esp_wifi_set_ps(WIFI_PS_NONE);

  // 최소 송신 출력 적용.
  // 8 = 2 dBm, 20 = 5 dBm, 34 = 8.5 dBm, 78 = 19.5 dBm
  esp_wifi_set_max_tx_power(TX_POWER);

  udp.begin(UDP_PORT);
  Serial.println("AP + Self-broadcast READY");
}

void loop() {
  // 초당 20회 CSI 트래픽 생성.
  udp.beginPacket(BROADCAST_IP, UDP_PORT);
  udp.write(reinterpret_cast<const uint8_t*>("ping"), 4);
  udp.endPacket();
  delay(SEND_INTERVAL_MS);
}
