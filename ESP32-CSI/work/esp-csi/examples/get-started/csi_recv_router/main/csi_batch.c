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
static TaskHandle_t s_capture_task;
static esp_ping_handle_t s_ping;
static SemaphoreHandle_t s_ping_done;
static bool s_collecting;
static bool s_capture_running;
typedef enum { BUFFER_FREE, BUFFER_FILLING, BUFFER_READY, BUFFER_SENDING } buffer_state_t;
typedef struct {
    buffer_state_t state;
    size_t count;
    csi_batch_meta_t meta;
} batch_buffer_t;
static batch_buffer_t s_buffers[CONFIG_CSI_BATCH_BUFFER_COUNT];
static int s_active = -1;
static size_t s_write_index = CONFIG_CSI_BATCH_BUFFER_COUNT - 1, s_read_index;
static uint32_t s_next_batch_id, s_sent, s_discarded, s_pause_count;
static uint64_t s_captured, s_sent_samples, s_discarded_samples;
static int64_t s_pause_started_us;
static uint64_t s_paused_us;
static uint32_t s_seq, s_dropped_samples;
static char s_device_id[18], s_session_id[33];

void csi_batch_ping_ended(void)
{
    if (s_ping_done) xSemaphoreGive(s_ping_done);
}

void csi_batch_capture(const wifi_csi_info_t *info)
{
    /* Called in the Wi-Fi task. Never wait, print, allocate or perform I/O here. */
    bool full = false, blocked = false;
    uint64_t now = (uint64_t)esp_timer_get_time();
    portENTER_CRITICAL(&s_lock);
    if (!s_collecting) {
        /* Account for replies already in flight while the controller pauses. */
        if (s_capture_running) { ++s_seq; ++s_dropped_samples; }
        portEXIT_CRITICAL(&s_lock);
        return;
    }
    uint32_t seq = s_seq++;
    if (!info || !info->buf || !info->len || info->len > CSI_BATCH_RAW_BYTES) {
        ++s_dropped_samples;
        portEXIT_CRITICAL(&s_lock);
        return;
    }
    batch_buffer_t *buffer = &s_buffers[s_active];
    csi_batch_sample_t *s = &s_samples[(size_t)s_active * CONFIG_CSI_BATCH_MAX_SAMPLES + buffer->count];
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
    if (!buffer->count) buffer->meta.window_started_us = now;
    ++buffer->count;
    ++s_captured;
    if (buffer->count == CONFIG_CSI_BATCH_MAX_SAMPLES) {
        buffer->meta = (csi_batch_meta_t) {
            .device_id = s_device_id, .session_id = s_session_id,
            .batch_id = s_next_batch_id++,
            .window_started_us = buffer->meta.window_started_us, .window_ended_us = now,
            .dropped_samples_total = s_dropped_samples,
        };
        buffer->state = BUFFER_READY;
        size_t next = (s_write_index + 1) % CONFIG_CSI_BATCH_BUFFER_COUNT;
        if (s_buffers[next].state == BUFFER_FREE) {
            s_write_index = next;
            s_active = (int)next;
            s_buffers[next].count = 0;
            s_buffers[next].state = BUFFER_FILLING;
        } else {
            s_active = -1;
            s_collecting = false;
            blocked = true;
        }
        full = true;
    }
    portEXIT_CRITICAL(&s_lock);
    if (full) xTaskNotifyGive(s_task);
    if (blocked && s_capture_task) xTaskNotifyGive(s_capture_task);
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

static bool post_batch(const csi_batch_meta_t *meta, const csi_batch_sample_t *samples,
                       size_t count, int *status)
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
    if (!csi_batch_json(meta, samples, count, NULL, NULL, &body_size) || body_size > INT_MAX) {
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
    if (!csi_batch_json(meta, samples, count, http_write, &sink, &emitted) || emitted != body_size) {
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
static void print_csv(const csi_batch_sample_t *samples, size_t count)
{
    static bool header_printed;
    if (!header_printed) {
        puts("type,id,mac,rssi,rate,sig_mode,mcs,bandwidth,smoothing,not_sounding,aggregation,stbc,fec_coding,sgi,noise_floor,ampdu_cnt,channel,secondary_channel,local_timestamp,ant,sig_len,rx_format,len,first_word,data");
        header_printed = true;
    }
    for (size_t i = 0; i < count; ++i) {
        const csi_batch_sample_t *s = &samples[i];
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

/* Only this task controls CSI/pings. Neither the callback nor HTTP can block it. */
static bool capture_control_step(void)
{
    portENTER_CRITICAL(&s_lock);
    if (s_active < 0) {
        size_t next = (s_write_index + 1) % CONFIG_CSI_BATCH_BUFFER_COUNT;
        if (s_buffers[next].state == BUFFER_FREE) {
            s_write_index = next;
            s_active = (int)next;
            s_buffers[next].count = 0;
            s_buffers[next].state = BUFFER_FILLING;
        }
    }
    bool wanted = s_active >= 0;
    bool running = s_capture_running;
    s_collecting = wanted && running;
    portEXIT_CRITICAL(&s_lock);
    if (wanted && !running) {
        (void)xSemaphoreTake(s_ping_done, 0);
        esp_err_t csi_error = esp_wifi_set_csi(true);
        esp_err_t ping_error = csi_error == ESP_OK ? esp_ping_start(s_ping) : csi_error;
        if (csi_error != ESP_OK || ping_error != ESP_OK) {
            (void)esp_wifi_set_csi(false);
            ESP_LOGE(TAG, "capture start failed: CSI=%s ping=%s; retrying control only",
                     esp_err_to_name(csi_error), esp_err_to_name(ping_error));
            return false;
        }
        int64_t resumed = esp_timer_get_time();
        portENTER_CRITICAL(&s_lock);
        s_capture_running = true;
        s_collecting = true;
        if (s_pause_started_us) {
            s_paused_us += (uint64_t)(resumed - s_pause_started_us);
            s_pause_started_us = 0;
        }
        portEXIT_CRITICAL(&s_lock);
    } else if (!wanted && running) {
        int64_t paused = esp_timer_get_time();
        esp_err_t stop_error = esp_ping_stop(s_ping);
        esp_err_t csi_error = esp_wifi_set_csi(false);
        if (stop_error == ESP_OK) (void)xSemaphoreTake(s_ping_done, portMAX_DELAY);
        portENTER_CRITICAL(&s_lock);
        s_capture_running = false;
        s_pause_started_us = paused;
        ++s_pause_count;
        portEXIT_CRITICAL(&s_lock);
        ESP_LOGW(TAG, "RAM queue full: capture paused until a buffer is released");
        if (stop_error != ESP_OK || csi_error != ESP_OK) {
            ESP_LOGE(TAG, "capture stop failed: ping=%s CSI=%s",
                     esp_err_to_name(stop_error), esp_err_to_name(csi_error));
        }
    }
    return true;
}

static void capture_task(void *unused)
{
    (void)unused;
    for (;;) {
        bool ok = capture_control_step();
        (void)ulTaskNotifyTake(pdTRUE, ok ? portMAX_DELAY : pdMS_TO_TICKS(100));
    }
}

/* A READY/SENDING buffer is immutable until this uploader releases it. */
static bool upload_next_batch(void)
{
    portENTER_CRITICAL(&s_lock);
    size_t index = s_read_index;
    batch_buffer_t *buffer = &s_buffers[index];
    if (buffer->state != BUFFER_READY) {
        portEXIT_CRITICAL(&s_lock);
        return false;
    }
    buffer->state = BUFFER_SENDING;
    size_t count = buffer->count;
    csi_batch_meta_t meta = buffer->meta;
    portEXIT_CRITICAL(&s_lock);
    const csi_batch_sample_t *samples = &s_samples[index * CONFIG_CSI_BATCH_MAX_SAMPLES];
    int status = 0;
    int64_t started = esp_timer_get_time();
#if CONFIG_CSI_BATCH_SERIAL_OUTPUT
    print_csv(samples, count);
#endif
    bool sent = post_batch(&meta, samples, count, &status);
    uint64_t upload_ms = (uint64_t)(esp_timer_get_time() - started) / 1000;
    if (sent) { ++s_sent; s_sent_samples += count; }
    else { ++s_discarded; s_discarded_samples += count; }
    portENTER_CRITICAL(&s_lock);
    buffer->count = 0;
    buffer->state = BUFFER_FREE;
    s_read_index = (index + 1) % CONFIG_CSI_BATCH_BUFFER_COUNT;
    unsigned int queued = 0;
    for (size_t i = 0; i < CONFIG_CSI_BATCH_BUFFER_COUNT; ++i) {
        if (s_buffers[i].state == BUFFER_READY || s_buffers[i].state == BUFFER_SENDING) ++queued;
    }
    uint64_t captured = s_captured;
    uint32_t dropped = s_dropped_samples, pauses = s_pause_count;
    uint64_t paused_us = s_paused_us;
    if (s_pause_started_us) paused_us += (uint64_t)(esp_timer_get_time() - s_pause_started_us);
    portEXIT_CRITICAL(&s_lock);
    xTaskNotifyGive(s_capture_task);
    uint32_t ping_tx = 0, ping_rx = 0;
    (void)esp_ping_get_profile(s_ping, ESP_PING_PROF_REQUEST, &ping_tx, sizeof(ping_tx));
    (void)esp_ping_get_profile(s_ping, ESP_PING_PROF_REPLY, &ping_rx, sizeof(ping_rx));
    wifi_ap_record_t ap;
    bool wifi = esp_wifi_sta_get_ap_info(&ap) == ESP_OK;
    ESP_LOGI(TAG, "batch=%" PRIu32 " samples=%u HTTP=%d queue=%u/%u captured=%" PRIu64
             " sent=%" PRIu32 " sent_samples=%" PRIu64 " discarded=%" PRIu32
             " discarded_samples=%" PRIu64 " dropped=%" PRIu32 " pauses=%" PRIu32
             " pause_ms=%" PRIu64 " upload_ms=%" PRIu64 " ping_tx=%" PRIu32 " ping_rx=%" PRIu32
             " wifi=%u free_heap=%u",
             meta.batch_id, (unsigned int)count, status, queued, (unsigned int)CONFIG_CSI_BATCH_BUFFER_COUNT,
             captured, s_sent, s_sent_samples, s_discarded, s_discarded_samples, dropped, pauses,
             paused_us / 1000, upload_ms, ping_tx, ping_rx, (unsigned int)wifi,
             (unsigned int)heap_caps_get_free_size(MALLOC_CAP_8BIT));
    return true;
}

static void batch_task(void *unused)
{
    (void)unused;
    for (;;) {
        if (!upload_next_batch()) (void)ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
    }
}

esp_err_t csi_batch_start(esp_ping_handle_t ping)
{
    if (!ping || s_samples || s_task || s_capture_task) return ESP_ERR_INVALID_STATE;
    uint8_t mac[6];
    esp_err_t error = esp_read_mac(mac, ESP_MAC_WIFI_STA);
    if (error != ESP_OK) return error;
    snprintf(s_device_id, sizeof(s_device_id), MACSTR, MAC2STR(mac));
    uint32_t random[4];
    esp_fill_random(random, sizeof(random));
    snprintf(s_session_id, sizeof(s_session_id), "%08" PRIx32 "%08" PRIx32 "%08" PRIx32 "%08" PRIx32,
             random[0], random[1], random[2], random[3]);
    size_t capacity = (size_t)CONFIG_CSI_BATCH_MAX_SAMPLES * CONFIG_CSI_BATCH_BUFFER_COUNT;
    s_samples = calloc(capacity, sizeof(*s_samples));
    if (!s_samples) {
        ESP_LOGE(TAG, "cannot allocate %u bytes for samples", (unsigned int)(capacity * sizeof(*s_samples)));
        return ESP_ERR_NO_MEM;
    }
    s_ping_done = xSemaphoreCreateBinary();
    if (!s_ping_done) {
        free(s_samples);
        s_samples = NULL;
        return ESP_ERR_NO_MEM;
    }
    s_ping = ping;
    if (xTaskCreate(batch_task, "csi_upload", 8192, NULL, 4, &s_task) != pdPASS ||
        xTaskCreate(capture_task, "csi_capture", 3072, NULL, 5, &s_capture_task) != pdPASS) {
        if (s_task) vTaskDelete(s_task);
        free(s_samples);
        vSemaphoreDelete(s_ping_done);
        s_ping_done = NULL;
        s_samples = NULL;
        s_task = NULL;
        return ESP_ERR_NO_MEM;
    }
    ESP_LOGI(TAG, "RAM buffers=%u bytes batch_samples=%u buffers=%u ping_hz=%u timeout_ms=%u; no collection timer; no delivery retries",
             (unsigned int)(capacity * sizeof(*s_samples)),
             (unsigned int)CONFIG_CSI_BATCH_MAX_SAMPLES, (unsigned int)CONFIG_CSI_BATCH_BUFFER_COUNT,
             (unsigned int)CONFIG_CSI_BATCH_PING_HZ,
             (unsigned int)CONFIG_CSI_POST_TIMEOUT_MS);
    return ESP_OK;
}
#endif
