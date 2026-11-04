/* Exercise the real capture, encoder and controller with deterministic drivers. */
#include <assert.h>
#include <setjmp.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "host_stubs.h"
#include "../main/csi_batch.c"

static int64_t now_us;
static unsigned int opens, cleanups, starts, stops, disabled, notified;
static unsigned int auth_headers;
static bool auth_header_error;
static int response = 201, open_error, write_error;
static int early_status;
static bool expire, expire_write, response_error;
static bool exit_on_wait;
static size_t inject_capture;
static char body[262144], last_log[512];
static size_t body_used, expected_size;
static bool ping_done;
static jmp_buf resumed;
static int8_t packet[CSI_BATCH_RAW_BYTES];
static wifi_csi_info_t info;

void host_log(const char *tag, const char *fmt, ...)
{
    (void)tag;
    va_list args;
    va_start(args, fmt);
    vsnprintf(last_log, sizeof(last_log), fmt, args);
    va_end(args);
}
int64_t esp_timer_get_time(void) { return now_us += 10; }
const char *esp_err_to_name(esp_err_t err) { (void)err; return "mock"; }
esp_err_t esp_wifi_set_csi(bool on)
{
    if (on) ++starts;
    if (!on) ++disabled;
    return ESP_OK;
}
esp_err_t esp_ping_start(esp_ping_handle_t h) { assert(h); return ESP_OK; }
esp_err_t esp_ping_stop(esp_ping_handle_t h)
{
    assert(h); ++stops; csi_batch_ping_ended(); return ESP_OK;
}
esp_err_t esp_ping_get_profile(esp_ping_handle_t h, int profile, void *data, uint32_t size)
{
    assert(h && (profile == ESP_PING_PROF_REQUEST || profile == ESP_PING_PROF_REPLY));
    assert(size == sizeof(uint32_t));
    *(uint32_t *)data = 50;
    return ESP_OK;
}
esp_err_t esp_wifi_sta_get_ap_info(wifi_ap_record_t *ap)
{
    assert(ap); memset(ap, 0, sizeof(*ap)); return ESP_OK;
}
esp_err_t esp_read_mac(uint8_t *m, int type) { (void)type; memset(m, 0x12, 6); return ESP_OK; }
void esp_fill_random(void *p, size_t n) { memset(p, 0x34, n); }
size_t heap_caps_get_free_size(int cap) { (void)cap; return 100000; }
int xTaskCreate(void (*fn)(void *), const char *name, uint32_t stack, void *arg, unsigned int priority, TaskHandle_t *out)
{
    (void)fn; (void)name; (void)stack; (void)arg; (void)priority;
    *out = (void *)1; return pdPASS;
}
void xTaskNotifyGive(TaskHandle_t task) { assert(task); ++notified; }
uint32_t ulTaskNotifyTake(int clear, uint32_t ticks)
{
    (void)clear;
    assert(ticks == portMAX_DELAY || ticks == pdMS_TO_TICKS(100));
    if (exit_on_wait) longjmp(resumed, 1);
    return 0;
}
void vTaskDelete(TaskHandle_t task) { assert(task); }
void vTaskDelay(uint32_t ticks) { now_us += (int64_t)ticks * 1000; }
SemaphoreHandle_t xSemaphoreCreateBinary(void) { return (void *)2; }
int xSemaphoreGive(SemaphoreHandle_t sem) { assert(sem); ping_done = true; return 1; }
int xSemaphoreTake(SemaphoreHandle_t sem, uint32_t ticks)
{
    assert(sem);
    if (ticks == portMAX_DELAY) assert(ping_done);
    bool available = ping_done;
    ping_done = false;
    return available;
}
void vSemaphoreDelete(SemaphoreHandle_t sem) { (void)sem; }
esp_err_t esp_crt_bundle_attach(void *p) { (void)p; return ESP_OK; }
esp_http_client_handle_t esp_http_client_init(const esp_http_client_config_t *c)
{
    assert(c->method == HTTP_METHOD_POST && c->disable_auto_redirect);
    assert(c->max_authorization_retries == -1);
    return (void *)3;
}
esp_err_t esp_http_client_set_timeout_ms(esp_http_client_handle_t c,int t) { assert(c && t > 0); return ESP_OK; }
esp_err_t esp_http_client_set_header(esp_http_client_handle_t c,const char *key,const char *value)
{
    assert(c);
    if (!strcmp(key, "Authorization")) {
        assert(!strcmp(value, "Bearer " CONFIG_CSI_POST_TOKEN));
        ++auth_headers;
        return auth_header_error ? ESP_FAIL : ESP_OK;
    }
    assert(!strcmp(key,"Content-Type") && !strcmp(value,"application/json"));
    return ESP_OK;
}
esp_err_t esp_http_client_open(esp_http_client_handle_t c,int n)
{
    assert(c && n > 0);
    assert(auth_headers == (CONFIG_CSI_POST_TOKEN[0] ? 1U : 0U));
    ++opens; expected_size = (size_t)n;
    if (expire) now_us += 2000000;
    return open_error;
}
int esp_http_client_write(esp_http_client_handle_t c,const char *p,int n)
{
    assert(c && n > 0);
    if (inject_capture) {
        size_t count = inject_capture;
        inject_capture = 0;
        for (size_t i = 0; i < count; ++i) {
            now_us += 20000;
            csi_batch_capture(&info);
        }
    }
    if (write_error) return 0;
    if (expire_write) now_us += 2000000;
    /* Force partial writes; one TCP request must still have an exact body. */
    if (n > 37) n = 37;
    assert(body_used + (size_t)n < sizeof(body));
    memcpy(body + body_used, p, (size_t)n);
    body_used += (size_t)n; body[body_used] = 0;
    return n;
}
int64_t esp_http_client_fetch_headers(esp_http_client_handle_t c)
{
    assert(c);
    if (body_used != expected_size) return early_status ? 0 : -1;
    return response_error ? -1 : 0;
}
int esp_http_client_get_status_code(esp_http_client_handle_t c)
{
    assert(c); return early_status ? early_status : response;
}
int esp_http_client_get_errno(esp_http_client_handle_t c) { assert(c); return 0; }
esp_err_t esp_http_client_cleanup(esp_http_client_handle_t c) { assert(c); ++cleanups; return ESP_OK; }

static void reset_transport(void)
{
    opens = cleanups = starts = stops = disabled = 0;
    auth_headers = 0; auth_header_error = false;
    body_used = expected_size = 0; body[0] = 0;
    response = 201; open_error = write_error = 0;
    early_status = 0;
    expire = expire_write = response_error = false;
}
static bool reject_sink(void *ctx, const char *p, size_t n)
{
    (void)ctx; (void)p; (void)n; return false;
}
int main(int argc, char **argv)
{
    assert(argc == 2);
    memset(packet, -128, sizeof(packet));
    info = (wifi_csi_info_t) {
        .buf = packet, .len = sizeof(packet), .mac = {0x9a,0xd7,0x42,0x16,0x37,0x54},
        .first_word_invalid = true,
        .rx_ctrl = {.timestamp = UINT32_MAX, .rssi = -57, .noise_floor = -97, .channel = 11, .sig_mode = 1},
    };
    assert(csi_batch_start((void *)1) == ESP_OK);
    assert(csi_batch_start((void *)1) == ESP_ERR_INVALID_STATE);
    csi_batch_capture(&info); assert(s_captured == 0);
    assert(capture_control_step() && s_capture_running && s_collecting);
    assert(starts == 1 && stops == 0 && disabled == 0);
    csi_batch_capture(&info);
    packet[0] = 127;
    assert(s_samples[0].data[0] == -128);
    assert(s_samples[0].rx_timestamp_us == UINT32_MAX);
    s_samples[0].timestamp_us = UINT64_C(5000000000);
    info.len = 129;
    csi_batch_capture(&info);
    assert(s_captured == 1 && s_dropped_samples == 1);
    info.len = sizeof(packet);
    for (size_t i = 1; i < CONFIG_CSI_BATCH_MAX_SAMPLES; ++i) csi_batch_capture(&info);
    assert(s_buffers[0].state == BUFFER_READY && s_active == 1 && s_collecting);
    assert(s_buffers[0].count == CONFIG_CSI_BATCH_MAX_SAMPLES && notified >= 1);

    csi_batch_meta_t meta = {.device_id = "dev\"\\\n", .session_id = "session", .batch_id = 42};
    size_t count = CONFIG_CSI_BATCH_MAX_SAMPLES;
    int status = 0;
    reset_transport();
    assert(post_batch(&meta, s_samples, count, &status));
    assert(opens == 1 && cleanups == 1 && status == 201 && body_used == expected_size);
    FILE *out = fopen(argv[1], "wb"); assert(out);
    fputs(body, out); fputc('\n', out);
    size_t size = 0;
    assert(csi_batch_json(&meta, NULL, 0, NULL, NULL, &size) && size > 0);
    assert(!csi_batch_json(&meta, s_samples, count, reject_sink, NULL, &size));
    assert(!csi_batch_json(&meta, NULL, 1, NULL, NULL, &size));
    uint16_t saved_len = s_samples[0].len;
    s_samples[0].len = 129;
    assert(!csi_batch_json(&meta, s_samples, 1, NULL, NULL, &size));
    s_samples[0].len = saved_len;

    reset_transport(); response = 503;
    assert(!post_batch(&meta, s_samples, count, &status) && opens == 1 && cleanups == 1 && status == 503);
    reset_transport(); response = 302;
    assert(!post_batch(&meta, s_samples, count, &status) && opens == 1 && cleanups == 1 && status == 302);
    reset_transport(); response = 401;
    assert(!post_batch(&meta, s_samples, count, &status) && opens == 1 && cleanups == 1 && status == 401);
    if (CONFIG_CSI_POST_TOKEN[0]) {
        reset_transport(); auth_header_error = true;
        assert(!post_batch(&meta, s_samples, count, &status) && opens == 0 && cleanups == 1);
    }
    reset_transport(); open_error = ESP_FAIL;
    assert(!post_batch(&meta, s_samples, count, &status) && opens == 1 && cleanups == 1);
    reset_transport(); write_error = 1;
    assert(!post_batch(&meta, s_samples, count, &status) && opens == 1 && cleanups == 1);
    reset_transport(); write_error = 1; early_status = 403;
    assert(!post_batch(&meta, s_samples, count, &status) && opens == 1 && cleanups == 1 && status == 403);
    assert(strstr(last_log, "stage=early_response"));
    reset_transport(); expire = true;
    assert(post_batch(&meta, s_samples, count, &status) && body_used == expected_size);
    reset_transport(); expire_write = true;
    assert(!post_batch(&meta, s_samples, count, &status));
    assert(body_used > 0 && body_used < expected_size && strstr(last_log, "stage=write"));
    reset_transport(); response_error = true;
    assert(!post_batch(&meta, s_samples, count, &status));
    assert(body_used == expected_size && strstr(last_log, "stage=response"));
    reset_transport();
    const char *saved_stub = STUB_URL;
    STUB_URL = CONFIG_CSI_POST_URL;
    assert(!post_batch(&meta, s_samples, count, &status) && opens == 0);
    STUB_URL = saved_stub;

    /* Real uploader: Wi-Fi arrivals during partial HTTP writes go into a
     * different slot, leaving the serialized buffer immutable. */
    reset_transport();
    csi_batch_sample_t saved[CONFIG_CSI_BATCH_MAX_SAMPLES];
    memcpy(saved, s_samples, sizeof(saved));
    inject_capture = 10;
    assert(upload_next_batch());
    assert(!memcmp(saved, s_samples, sizeof(saved)));
    assert(s_buffers[0].state == BUFFER_FREE && s_buffers[1].count == 10);
    assert(s_collecting && s_capture_running && stops == 0 && disabled == 0);
    assert(s_sent == 1 && s_discarded == 0 && opens == 1);
    fputs(body, out); fputc('\n', out);

    /* No timer: a partial buffer remains collecting even after 100 seconds. */
    now_us += INT64_C(100000000);
    assert(capture_control_step() && s_buffers[1].count == 10 && s_collecting);
    assert(!upload_next_batch());
    for (size_t i = 0; i < 10 + 3 * CONFIG_CSI_BATCH_MAX_SAMPLES; ++i) csi_batch_capture(&info);
    assert(s_active == -1 && !s_collecting);
    csi_batch_capture(&info);
    assert(s_dropped_samples == 2); /* callback already in flight at saturation */
    assert(capture_control_step() && !s_capture_running);
    assert(stops == 1 && disabled == 1 && s_pause_count == 1);
    now_us += INT64_C(5000000);
    assert(capture_control_step() && !s_collecting);
    assert(stops == 1); /* waiting for space does not repeatedly stop pings */
    reset_transport();
    assert(upload_next_batch());
    assert(strstr(body, "\"batch_id\":1,"));
    fputs(body, out); fputc('\n', out);
    assert(capture_control_step() && s_capture_running && s_collecting);
    assert(s_active == 1 && s_paused_us >= UINT64_C(5000000));

    /* Failed batches are attempted once, released, and do not stall capture. */
    reset_transport(); response = 503;
    assert(upload_next_batch() && opens == 1 && cleanups == 1);
    assert(strstr(body, "\"batch_id\":2,"));
    assert(s_discarded == 1 && s_discarded_samples == CONFIG_CSI_BATCH_MAX_SAMPLES);
    assert(s_buffers[2].state == BUFFER_FREE && s_collecting);
    reset_transport();
    assert(upload_next_batch() && strstr(body, "\"batch_id\":3,"));
    reset_transport();
    assert(upload_next_batch() && strstr(body, "\"batch_id\":4,"));
    assert(!upload_next_batch());

    /* Repeated capture/upload far beyond the former 3-second limit. */
    for (unsigned int cycle = 0; cycle < 100; ++cycle) {
        for (size_t i = 0; i < CONFIG_CSI_BATCH_MAX_SAMPLES; ++i) {
            now_us += 20000;
            csi_batch_capture(&info);
        }
        assert(capture_control_step() && s_collecting);
        reset_transport();
        assert(upload_next_batch() && opens == 1 && stops == 0 && disabled == 0);
    }
    assert(s_pause_count == 1 && s_sent == 104 && s_discarded == 1);
    assert(s_captured == UINT64_C(105) * CONFIG_CSI_BATCH_MAX_SAMPLES);

    /* Both production loops idle on notifications, not a collection timer. */
    exit_on_wait = true;
    if (setjmp(resumed) == 0) batch_task(NULL);
    if (setjmp(resumed) == 0) capture_task(NULL);
    fclose(out);
    free(s_samples);
    fprintf(stderr, "Continuous capture/FIFO/HTTP/JSON tests passed; bounded RAM=%zu bytes\n",
            sizeof(csi_batch_sample_t) * CONFIG_CSI_BATCH_MAX_SAMPLES * CONFIG_CSI_BATCH_BUFFER_COUNT);
    return 0;
}
