#include "esp_wifi.h"
#include "esp_event.h"
#include "nvs_flash.h"
#include <WiFi.h>
//클로드 송신 수신 - 작동
//클로드 송신 파이널 수신 - rssi 강조

static void csi_cb(void *ctx, wifi_csi_info_t *data) {
    Serial.print("CSI_DATA");
    Serial.print(",RSSI=");
    Serial.print(data->rx_ctrl.rssi);

    for (int i = 0; i < data->len; i++) {
        Serial.print(",");
        Serial.print(data->buf[i]);
    }

    Serial.println();
}

static void wifi_event_handler(void* arg, esp_event_base_t event_base,
                                int32_t event_id, void* event_data) {
    if (event_id == WIFI_EVENT_STA_CONNECTED) {
        Serial.println(">>> AP 연결 성공!");
    } else if (event_id == WIFI_EVENT_STA_DISCONNECTED) {
        Serial.println(">>> 재연결 시도...");
        esp_wifi_connect();
    }
}

void setup() {
    Serial.begin(115200);
    nvs_flash_init();
    esp_event_loop_create_default();

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    esp_wifi_init(&cfg);
    esp_wifi_set_mode(WIFI_MODE_STA);

    // 이벤트 핸들러 등록 (재연결 자동화)
    esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID,
                                &wifi_event_handler, NULL);

    esp_wifi_start();

    wifi_config_t sta_config = {};
    strcpy((char*)sta_config.sta.ssid, "GRADUATION_PROJECT");
    strcpy((char*)sta_config.sta.password, "12345678");

    esp_wifi_set_config(WIFI_IF_STA, &sta_config);
    esp_wifi_connect();

    esp_wifi_set_channel(11, WIFI_SECOND_CHAN_NONE);

    wifi_csi_config_t config;
    config.lltf_en           = 1;
    config.htltf_en          = 0;
    config.stbc_htltf2_en    = 0;
    config.ltf_merge_en      = 1;
    config.channel_filter_en = 0;
    config.manu_scale        = 0;
    config.shift             = 0;


    esp_wifi_set_promiscuous(true);
    esp_wifi_set_csi_rx_cb(csi_cb, NULL);
    esp_wifi_set_csi_config(&config);
    esp_wifi_set_csi(true);

    Serial.println("CSI_RECEIVER_READY");
}

void loop() {
    // 5초마다 연결 상태 확인 + 자동 재연결
    static unsigned long last_check = 0;
    if (millis() - last_check > 5000) {
        last_check = millis();
        wifi_ap_record_t ap_info;
        if (esp_wifi_sta_get_ap_info(&ap_info) == ESP_OK) {
            //Serial.printf("연결됨 | RSSI: %d dBm\n", ap_info.rssi);
        } else {
            //Serial.println("연결 안됨 - 재시도");
            esp_wifi_connect();
        }
    }
}