#pragma once
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>

#define CONFIG_CSI_BATCH_POST_ENABLED 1
#define CONFIG_CSI_BATCH_MAX_SAMPLES 20
#define CONFIG_CSI_BATCH_BUFFER_COUNT 4
#define CONFIG_CSI_BATCH_PING_HZ 100
#define CONFIG_CSI_POST_TIMEOUT_MS 1000
#define CONFIG_CSI_POST_URL "http://127.0.0.1/csi"
#ifndef CONFIG_CSI_POST_TOKEN
#define CONFIG_CSI_POST_TOKEN "unit-test-token"
#endif
#define CONFIG_MBEDTLS_CERTIFICATE_BUNDLE 1
#ifndef CONFIG_CSI_BATCH_SERIAL_OUTPUT
#define CONFIG_CSI_BATCH_SERIAL_OUTPUT 0
#endif
#define ESP_OK 0
#define ESP_FAIL -1
#define ESP_ERR_INVALID_STATE 2
#define ESP_ERR_NO_MEM 3
#define ESP_ERR_INVALID_ARG 4
#define ESP_ERR_TIMEOUT 5
#define ESP_MAC_WIFI_STA 0
#define MALLOC_CAP_8BIT 0
#define HTTP_METHOD_POST 1
#define ESP_PING_PROF_REQUEST 1
#define ESP_PING_PROF_REPLY 2
#define pdTRUE 1
#define pdPASS 1
#define pdMS_TO_TICKS(x) (x)
#define portMAX_DELAY UINT32_MAX
#define portMUX_INITIALIZER_UNLOCKED 0
#define portENTER_CRITICAL(x) ((void)(x))
#define portEXIT_CRITICAL(x) ((void)(x))
#define MACSTR "%02x:%02x:%02x:%02x:%02x:%02x"
#define MAC2STR(m) (m)[0],(m)[1],(m)[2],(m)[3],(m)[4],(m)[5]
#define ESP_LOGI(...) host_log(__VA_ARGS__)
#define ESP_LOGW(...) host_log(__VA_ARGS__)
#define ESP_LOGE(...) host_log(__VA_ARGS__)
typedef int esp_err_t;
typedef int portMUX_TYPE;
typedef void *TaskHandle_t;
typedef void *SemaphoreHandle_t;
typedef void *esp_ping_handle_t;
typedef void *esp_http_client_handle_t;
typedef struct { uint8_t unused; } wifi_ap_record_t;
typedef struct {
    uint32_t timestamp;
    uint16_t sig_len;
    int8_t rssi, noise_floor;
    uint8_t channel,cwb,rate,sig_mode,mcs,smoothing,not_sounding,aggregation;
    uint8_t stbc,fec_coding,sgi,ampdu_cnt,secondary_channel,ant;
} wifi_pkt_rx_ctrl_t;
typedef struct {
    int8_t *buf;
    uint16_t len;
    uint8_t mac[6];
    bool first_word_invalid;
    wifi_pkt_rx_ctrl_t rx_ctrl;
} wifi_csi_info_t;
typedef struct {
    const char *url;
    int method,timeout_ms;
    bool disable_auto_redirect;
    int max_authorization_retries,buffer_size,buffer_size_tx;
    esp_err_t (*crt_bundle_attach)(void *);
} esp_http_client_config_t;

void host_log(const char *, const char *, ...) __attribute__((format(printf, 2, 3)));
int64_t esp_timer_get_time(void);
esp_err_t esp_wifi_set_csi(bool);
esp_err_t esp_ping_start(esp_ping_handle_t);
esp_err_t esp_ping_stop(esp_ping_handle_t);
esp_err_t esp_ping_get_profile(esp_ping_handle_t, int, void *, uint32_t);
esp_err_t esp_wifi_sta_get_ap_info(wifi_ap_record_t *);
const char *esp_err_to_name(esp_err_t);
esp_err_t esp_read_mac(uint8_t *, int);
void esp_fill_random(void *, size_t);
size_t heap_caps_get_free_size(int);
int xTaskCreate(void (*)(void *), const char *, uint32_t, void *, unsigned int, TaskHandle_t *);
void xTaskNotifyGive(TaskHandle_t);
uint32_t ulTaskNotifyTake(int, uint32_t);
void vTaskDelay(uint32_t);
void vTaskDelete(TaskHandle_t);
SemaphoreHandle_t xSemaphoreCreateBinary(void);
int xSemaphoreGive(SemaphoreHandle_t);
int xSemaphoreTake(SemaphoreHandle_t, uint32_t);
void vSemaphoreDelete(SemaphoreHandle_t);
esp_http_client_handle_t esp_http_client_init(const esp_http_client_config_t *);
esp_err_t esp_http_client_set_timeout_ms(esp_http_client_handle_t,int);
esp_err_t esp_http_client_set_header(esp_http_client_handle_t,const char *,const char *);
esp_err_t esp_http_client_open(esp_http_client_handle_t,int);
int esp_http_client_write(esp_http_client_handle_t,const char *,int);
int64_t esp_http_client_fetch_headers(esp_http_client_handle_t);
int esp_http_client_get_status_code(esp_http_client_handle_t);
int esp_http_client_get_errno(esp_http_client_handle_t);
esp_err_t esp_http_client_cleanup(esp_http_client_handle_t);
esp_err_t esp_crt_bundle_attach(void *);
