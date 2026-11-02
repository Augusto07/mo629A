#include "csi_batch.h"

#if CONFIG_CSI_BATCH_POST_ENABLED
#include "csi_batch_json.h"

#include <inttypes.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "esp_heap_caps.h"
#include "esp_http_client.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_random.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#if CONFIG_MBEDTLS_CERTIFICATE_BUNDLE
#include "esp_crt_bundle.h"
#endif

static const char *TAG = "csi_batch";
static const char *STUB_URL = "https://example.invalid/csi";
static portMUX_TYPE s_lock = portMUX_INITIALIZER_UNLOCKED;
static csi_batch_sample_t *s_samples;
static TaskHandle_t s_task;
static esp_ping_handle_t s_ping;
static SemaphoreHandle_t s_ping_done;
static bool s_collecting;
static size_t s_count;
static uint32_t s_seq, s_dropped_samples;
static char s_device_id[18], s_session_id[33];

void csi_batch_ping_ended(void)
{
    if (s_ping_done) xSemaphoreGive(s_ping_done);
}

void csi_batch_capture(const wifi_csi_info_t *info)
{
    /* Called in the Wi-Fi task. Never wait, print, allocate or perform I/O here. */
    bool full = false;
    uint64_t now = (uint64_t)esp_timer_get_time();
    portENTER_CRITICAL(&s_lock);
    if (!s_collecting) {
        portEXIT_CRITICAL(&s_lock);
        return;
    }
    uint32_t seq = s_seq++;
    if (!info || !info->buf || !info->len || info->len > CSI_BATCH_RAW_BYTES) {
        ++s_dropped_samples;
        portEXIT_CRITICAL(&s_lock);
        return;
    }
    if (s_count >= CONFIG_CSI_BATCH_MAX_SAMPLES) {
        ++s_dropped_samples;
        portEXIT_CRITICAL(&s_lock);
        return;
    }
    csi_batch_sample_t *s = &s_samples[s_count];
    const wifi_pkt_rx_ctrl_t *r = &info->rx_ctrl;
    *s = (csi_batch_sample_t) {
        .timestamp_us = now, .seq = seq, .rx_timestamp_us = r->timestamp,
        .len = info->len, .sig_len = r->sig_len,
        .rssi = r->rssi, .noise_floor = r->noise_floor,
        .channel = r->channel, .cwb = r->cwb, .rate = r->rate,
        .sig_mode = r->sig_mode, .mcs = r->mcs,
        .smoothing = r->smoothing, .not_sounding = r->not_sounding,
        .aggregation = r->aggregation, .stbc = r->stbc, .fec_coding = r->fec_coding,
        .sgi = r->sgi, .ampdu_cnt = r->ampdu_cnt,
        .secondary_channel = r->secondary_channel, .ant = r->ant,
        .first_word_invalid = info->first_word_invalid,
    };
    memcpy(s->mac, info->mac, sizeof(s->mac));
    memcpy(s->data, info->buf, info->len);
    ++s_count;
    if (s_count == CONFIG_CSI_BATCH_MAX_SAMPLES) {
        s_collecting = false;
        full = true;
    }
    portEXIT_CRITICAL(&s_lock);
    if (full) xTaskNotifyGive(s_task);
}

typedef struct {
    esp_http_client_handle_t client;
    int64_t deadline_us;
    size_t bytes_sent;
    esp_err_t error;
} http_sink_t;

static bool set_remaining_timeout(http_sink_t *sink)
{
    int64_t remaining = sink->deadline_us - esp_timer_get_time();
    if (remaining <= 0) {
        sink->error = ESP_ERR_TIMEOUT;
        return false;
    }
    sink->error = esp_http_client_set_timeout_ms(sink->client, (int)((remaining + 999) / 1000));
    return sink->error == ESP_OK;
}

static bool http_write(void *ctx, const char *data, size_t length)
{
    http_sink_t *sink = ctx;
    while (length) {
        if (!set_remaining_timeout(sink)) return false;
        int written = esp_http_client_write(sink->client, data, (int)length);
        if (written <= 0) {
            sink->error = ESP_FAIL;
            return false;
        }
        sink->bytes_sent += (size_t)written;
        data += written;
        length -= (size_t)written;
    }
    return true;
}

static esp_err_t set_post_headers(esp_http_client_handle_t client)
{
    esp_err_t error = esp_http_client_set_header(client, "Content-Type", "application/json");
    if (error != ESP_OK || CONFIG_CSI_POST_TOKEN[0] == '\0') return error;
    if (strchr(CONFIG_CSI_POST_TOKEN, '\r') || strchr(CONFIG_CSI_POST_TOKEN, '\n')) {
        ESP_LOGE(TAG, "token contains a line break; batch discarded");
        return ESP_ERR_INVALID_ARG;
    }
    /* Never print this value or place it in the JSON body. */
    return esp_http_client_set_header(client, "Authorization", "Bearer " CONFIG_CSI_POST_TOKEN);
}

static bool post_batch(const csi_batch_meta_t *meta, size_t count, int *status)
{
    *status = 0;
    if (strcmp(CONFIG_CSI_POST_URL, STUB_URL) == 0) {
        ESP_LOGW(TAG, "stub URL: batch discarded without network I/O");
        return false;
    }
    bool https = strncmp(CONFIG_CSI_POST_URL, "https://", 8) == 0;
    if (!https && strncmp(CONFIG_CSI_POST_URL, "http://", 7) != 0) {
        ESP_LOGE(TAG, "POST URL must start with http:// or https://");
        return false;
    }
#if !CONFIG_MBEDTLS_CERTIFICATE_BUNDLE
    if (https) {
        ESP_LOGE(TAG, "HTTPS requires CONFIG_MBEDTLS_CERTIFICATE_BUNDLE; batch discarded");
        return false;
    }
#endif
    size_t body_size = 0;
    if (!csi_batch_json(meta, s_samples, count, NULL, NULL, &body_size) || body_size > INT_MAX) {
        ESP_LOGE(TAG, "could not encode batch");
        return false;
    }
    esp_http_client_config_t config = {
        .url = CONFIG_CSI_POST_URL,
        .method = HTTP_METHOD_POST,
        .timeout_ms = CONFIG_CSI_POST_TIMEOUT_MS,
        .disable_auto_redirect = true,
        .max_authorization_retries = -1,
        .buffer_size = 512,
        .buffer_size_tx = 1024,
#if CONFIG_MBEDTLS_CERTIFICATE_BUNDLE
        .crt_bundle_attach = esp_crt_bundle_attach,
#endif
    };
    esp_http_client_handle_t client = esp_http_client_init(&config);
    if (!client) {
        ESP_LOGE(TAG, "POST failed stage=init (client allocation)");
        return false;
    }
    http_sink_t sink = {.client = client};
    bool success = false;
    const char *stage = "headers";
    int64_t started_us = esp_timer_get_time();
    uint64_t connect_ms = 0;
    esp_err_t error = set_post_headers(client);
    if (error != ESP_OK) goto done;

    stage = "connect";
    int64_t connect_started_us = esp_timer_get_time();
    error = esp_http_client_open(client, (int)body_size);
    connect_ms = (uint64_t)(esp_timer_get_time() - connect_started_us) / 1000;
    if (error != ESP_OK) goto done;

    /* DNS/TLS must not consume the entire body budget before the first byte. */
    stage = "write";
    sink.deadline_us = esp_timer_get_time() + (int64_t)CONFIG_CSI_POST_TIMEOUT_MS * 1000;
    size_t emitted = 0;
    if (!csi_batch_json(meta, s_samples, count, http_write, &sink, &emitted) || emitted != body_size) {
        error = sink.error != ESP_OK ? sink.error : ESP_FAIL;
        /* An API gateway may reject headers/authentication before consuming
         * the full body. Probe that response on the same request, never retry. */
        int probe_ms = CONFIG_CSI_POST_TIMEOUT_MS < 200 ? CONFIG_CSI_POST_TIMEOUT_MS : 200;
        if (esp_http_client_set_timeout_ms(client, probe_ms) == ESP_OK &&
            esp_http_client_fetch_headers(client) >= 0) {
            int early_status = esp_http_client_get_status_code(client);
            if (early_status > 0) {
                *status = early_status;
                stage = "early_response";
            }
        }
        goto done;
    }

    /* A fully transmitted body gets a fresh response timeout as well. */
    stage = "response";
    error = esp_http_client_set_timeout_ms(client, CONFIG_CSI_POST_TIMEOUT_MS);
    if (error != ESP_OK) goto done;
    if (esp_http_client_fetch_headers(client) < 0) {
        error = ESP_FAIL;
        goto done;
    }
    *status = esp_http_client_get_status_code(client);
    stage = "http_status";
    success = *status >= 200 && *status < 300;
    if (!success) error = ESP_FAIL;

done:
    if (success) {
        ESP_LOGI(TAG, "POST completed HTTP=%d body_sent=%u/%u connect_ms=%" PRIu64 " elapsed_ms=%" PRIu64,
                 *status, (unsigned int)sink.bytes_sent, (unsigned int)body_size, connect_ms,
                 (uint64_t)(esp_timer_get_time() - started_us) / 1000);
    } else {
        ESP_LOGW(TAG, "POST failed stage=%s err=%s socket_errno=%d HTTP=%d body_sent=%u/%u"
                 " connect_ms=%" PRIu64 " elapsed_ms=%" PRIu64,
                 stage, esp_err_to_name(error), esp_http_client_get_errno(client), *status,
                 (unsigned int)sink.bytes_sent, (unsigned int)body_size, connect_ms,
                 (uint64_t)(esp_timer_get_time() - started_us) / 1000);
    }
    /* Exactly one request attempt: no retries, redirects or retained payload. */
    esp_http_client_cleanup(client);
    return success;
}

#if CONFIG_CSI_BATCH_SERIAL_OUTPUT
static void print_csv(size_t count)
{
    static bool header_printed;
    if (!header_printed) {
        puts("type,id,mac,rssi,rate,sig_mode,mcs,bandwidth,smoothing,not_sounding,aggregation,stbc,fec_coding,sgi,noise_floor,ampdu_cnt,channel,secondary_channel,local_timestamp,ant,sig_len,rx_format,len,first_word,data");
        header_printed = true;
    }
    for (size_t i = 0; i < count; ++i) {
        const csi_batch_sample_t *s = &s_samples[i];
        printf("CSI_DATA,%" PRIu32 "," MACSTR ",%d,%u,%u,%u,%u,%u,%u,%u,%u,%u,%u,%d,%u,%u,%u,%" PRIu32 ",%u,%u,%u,%u,%u,\"[",
               s->seq, MAC2STR(s->mac), s->rssi, s->rate, s->sig_mode, s->mcs, s->cwb,
               s->smoothing, s->not_sounding, s->aggregation, s->stbc, s->fec_coding, s->sgi,
               s->noise_floor, s->ampdu_cnt, s->channel, s->secondary_channel, s->rx_timestamp_us,
               s->ant, s->sig_len, s->sig_mode, s->len, s->first_word_invalid);
        for (size_t j = 0; j < s->len; ++j) printf("%s%d", j ? "," : "", s->data[j]);
        puts("]\"");
    }
}
#endif

static void batch_task(void *unused)
{
    (void)unused;
    uint32_t batch_id = 0, sent = 0, discarded = 0;
    for (;;) {
        /* A notification from a completed previous window must not close this one. */
        (void)ulTaskNotifyTake(pdTRUE, 0);
        (void)xSemaphoreTake(s_ping_done, 0);
        uint64_t started = (uint64_t)esp_timer_get_time();
        portENTER_CRITICAL(&s_lock);
        s_count = 0;
        s_collecting = true;
        portEXIT_CRITICAL(&s_lock);
        esp_err_t csi_error = esp_wifi_set_csi(true);
        esp_err_t ping_error = csi_error == ESP_OK ? esp_ping_start(s_ping) : csi_error;
        if (csi_error == ESP_OK && ping_error == ESP_OK) {
            (void)ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(CONFIG_CSI_BATCH_WINDOW_MS));
        }
        portENTER_CRITICAL(&s_lock);
        s_collecting = false;
        size_t count = s_count;
        uint32_t dropped = s_dropped_samples;
        portEXIT_CRITICAL(&s_lock);
        uint64_t ended = (uint64_t)esp_timer_get_time();
        /* In-flight ping replies may still arrive; capture already rejects them. */
        esp_err_t stop_error = esp_ping_stop(s_ping);
        esp_err_t disable_error = esp_wifi_set_csi(false);
        if (csi_error == ESP_OK && ping_error == ESP_OK && stop_error == ESP_OK) {
            /* Wait for the ping task to finish its in-flight receive (100 ms timeout).
             * Never restart the session or POST while the old ping loop is active. */
            (void)xSemaphoreTake(s_ping_done, portMAX_DELAY);
        }
        uint32_t ping_tx = 0, ping_rx = 0;
        (void)esp_ping_get_profile(s_ping, ESP_PING_PROF_REQUEST, &ping_tx, sizeof(ping_tx));
        (void)esp_ping_get_profile(s_ping, ESP_PING_PROF_REPLY, &ping_rx, sizeof(ping_rx));
        if (csi_error != ESP_OK || ping_error != ESP_OK || stop_error != ESP_OK || disable_error != ESP_OK) {
            ESP_LOGE(TAG, "capture control error: CSI=%s ping=%s stop=%s disable=%s",
                     esp_err_to_name(csi_error), esp_err_to_name(ping_error),
                     esp_err_to_name(stop_error), esp_err_to_name(disable_error));
        }
        csi_batch_meta_t meta = {
            .device_id = s_device_id, .session_id = s_session_id, .batch_id = batch_id++,
            .window_started_us = started, .window_ended_us = ended,
            .dropped_samples_total = dropped, .discarded_batches_total = discarded,
        };
        int status = 0;
        if (count) {
#if CONFIG_CSI_BATCH_SERIAL_OUTPUT
            print_csv(count);
#endif
            if (post_batch(&meta, count, &status)) ++sent;
            else ++discarded;
        }
        wifi_ap_record_t ap;
        bool wifi_associated = esp_wifi_sta_get_ap_info(&ap) == ESP_OK;
        ESP_LOGI(TAG, "batch=%" PRIu32 " samples=%u ping_tx=%" PRIu32 " ping_rx=%" PRIu32 " wifi=%u HTTP=%d sent=%" PRIu32
                 " discarded=%" PRIu32 " dropped=%" PRIu32 " pause_ms=%" PRIu64 " free_heap=%u",
                 meta.batch_id, (unsigned int)count, ping_tx, ping_rx, (unsigned int)wifi_associated,
                 status, sent, discarded, dropped,
                 ((uint64_t)esp_timer_get_time() - ended) / 1000,
                 (unsigned int)heap_caps_get_free_size(MALLOC_CAP_8BIT));
        /* Reuse the allocation on the next window, even if delivery failed. */
        if (!count || csi_error != ESP_OK || ping_error != ESP_OK) vTaskDelay(pdMS_TO_TICKS(100));
    }
}

esp_err_t csi_batch_start(esp_ping_handle_t ping)
{
    if (!ping || s_samples || s_task) return ESP_ERR_INVALID_STATE;
    uint8_t mac[6];
    esp_err_t error = esp_read_mac(mac, ESP_MAC_WIFI_STA);
    if (error != ESP_OK) return error;
    snprintf(s_device_id, sizeof(s_device_id), MACSTR, MAC2STR(mac));
    uint32_t random[4];
    esp_fill_random(random, sizeof(random));
    snprintf(s_session_id, sizeof(s_session_id), "%08" PRIx32 "%08" PRIx32 "%08" PRIx32 "%08" PRIx32,
             random[0], random[1], random[2], random[3]);
    s_samples = calloc(CONFIG_CSI_BATCH_MAX_SAMPLES, sizeof(*s_samples));
    if (!s_samples) {
        ESP_LOGE(TAG, "cannot allocate %u bytes for samples", (unsigned int)(CONFIG_CSI_BATCH_MAX_SAMPLES * sizeof(*s_samples)));
        return ESP_ERR_NO_MEM;
    }
    s_ping_done = xSemaphoreCreateBinary();
    if (!s_ping_done) {
        free(s_samples);
        s_samples = NULL;
        return ESP_ERR_NO_MEM;
    }
    s_ping = ping;
    if (xTaskCreate(batch_task, "csi_batch", 8192, NULL, 4, &s_task) != pdPASS) {
        free(s_samples);
        vSemaphoreDelete(s_ping_done);
        s_ping_done = NULL;
        s_samples = NULL;
        s_task = NULL;
        return ESP_ERR_NO_MEM;
    }
    ESP_LOGI(TAG, "RAM buffer=%u bytes capacity=%u window_ms=%u ping_hz=%u timeout_ms=%u; no delivery retries",
             (unsigned int)(CONFIG_CSI_BATCH_MAX_SAMPLES * sizeof(*s_samples)),
             (unsigned int)CONFIG_CSI_BATCH_MAX_SAMPLES, (unsigned int)CONFIG_CSI_BATCH_WINDOW_MS,
             (unsigned int)CONFIG_CSI_BATCH_PING_HZ,
             (unsigned int)CONFIG_CSI_POST_TIMEOUT_MS);
    return ESP_OK;
}
#endif
