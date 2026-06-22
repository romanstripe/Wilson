#include "esp_wifi.h"
#include "esp_event.h"
#include "nvs_flash.h"
#include <WiFi.h>

namespace {
constexpr char AP_SSID[] = "GRADUATION_PROJECT";
constexpr char AP_PASSWORD[] = "12345678";
constexpr uint8_t WIFI_CHANNEL = 11;
constexpr unsigned long CONNECTION_CHECK_MS = 5000;

void handle_csi(void* context, wifi_csi_info_t* data) {
  if (data == nullptr || data->buf == nullptr) {
    return;
  }

  Serial.print("CSI_DATA,RSSI=");
  Serial.print(data->rx_ctrl.rssi);

  for (int i = 0; i < data->len; ++i) {
    Serial.print(',');
    Serial.print(data->buf[i]);
  }

  Serial.println();
}

void handle_wifi_event(void* arg, esp_event_base_t event_base,
                       int32_t event_id, void* event_data) {
  if (event_id == WIFI_EVENT_STA_CONNECTED) {
    Serial.println(">>> AP 연결 성공!");
  } else if (event_id == WIFI_EVENT_STA_DISCONNECTED) {
    Serial.println(">>> 재연결 시도...");
    esp_wifi_connect();
  }
}
}  // namespace

void setup() {
  Serial.begin(115200);
  nvs_flash_init();
  esp_event_loop_create_default();

  wifi_init_config_t wifi_config = WIFI_INIT_CONFIG_DEFAULT();
  esp_wifi_init(&wifi_config);
  esp_wifi_set_mode(WIFI_MODE_STA);

  // Wi-Fi 자동 재연결 등록.
  esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID,
                             &handle_wifi_event, nullptr);

  esp_wifi_start();

  wifi_config_t station_config = {};
  strcpy(reinterpret_cast<char*>(station_config.sta.ssid), AP_SSID);
  strcpy(reinterpret_cast<char*>(station_config.sta.password), AP_PASSWORD);

  esp_wifi_set_config(WIFI_IF_STA, &station_config);
  esp_wifi_connect();

  esp_wifi_set_channel(WIFI_CHANNEL, WIFI_SECOND_CHAN_NONE);

  wifi_csi_config_t csi_config = {};
  csi_config.lltf_en = 1;
  csi_config.htltf_en = 0;
  csi_config.stbc_htltf2_en = 0;
  csi_config.ltf_merge_en = 1;
  csi_config.channel_filter_en = 0;
  csi_config.manu_scale = 0;
  csi_config.shift = 0;

  esp_wifi_set_promiscuous(true);
  esp_wifi_set_csi_rx_cb(handle_csi, nullptr);
  esp_wifi_set_csi_config(&csi_config);
  esp_wifi_set_csi(true);

  Serial.println("CSI_RECEIVER_READY");
}

void loop() {
  // 5초 간격 연결 상태 확인.
  static unsigned long last_check = 0;
  const unsigned long now = millis();
  if (now - last_check >= CONNECTION_CHECK_MS) {
    last_check = now;
    wifi_ap_record_t access_point;
    if (esp_wifi_sta_get_ap_info(&access_point) != ESP_OK) {
      esp_wifi_connect();
    }
  }
}
