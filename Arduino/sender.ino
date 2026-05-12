// sender.ino 수정 - 자체 브로드캐스트 추가
#include <WiFi.h>
#include <WiFiUdp.h>
#include <esp_wifi.h>

WiFiUDP udp;

void setup() {
  Serial.begin(115200);
  WiFi.mode(WIFI_AP);

  WiFi.softAP("GRADUATION_PROJECT", "12345678", 11, false);

 // 절전 끄기
  esp_wifi_set_ps(WIFI_PS_NONE);

  // 송신 출력 낮추기
  // 8  = 2 dBm
  // 20 = 5 dBm
  // 34 = 8.5 dBm
  // 78 = 19.5 dBm
  esp_wifi_set_max_tx_power(8);   // 가장 약하게 시작

  
  // UDP 시작 - 자체 브로드캐스트용
  udp.begin(12345);
  Serial.println("AP + Self-broadcast READY");
}

void loop() {
  // AP 자신이 브로드캐스트를 쏨 → 수신기 CSI 유발
  // 노트북 연결 불필요!
  udp.beginPacket("192.168.4.255", 12345);
  udp.write((uint8_t*)"ping", 4);
  udp.endPacket();
  delay(50); // 초당 20회
}