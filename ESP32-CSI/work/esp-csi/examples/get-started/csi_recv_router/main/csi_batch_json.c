#include "csi_batch_json.h"

#include <inttypes.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>

static bool append(char *buf, size_t capacity, size_t *used, const char *fmt, ...)
{
    va_list args;
    va_start(args, fmt);
    int n = vsnprintf(buf + *used, capacity - *used, fmt, args);
    va_end(args);
    if (n < 0 || (size_t)n >= capacity - *used) {
        return false;
    }
    *used += (size_t)n;
    return true;
}

static bool quote(char *buf, size_t cap, size_t *used, const char *text)
{
    if (!text || !append(buf, cap, used, "\"")) {
        return false;
    }
    for (const unsigned char *p = (const unsigned char *)text; *p; ++p) {
        if (*p == '"' || *p == '\\') {
            if (!append(buf, cap, used, "\\%c", *p)) return false;
        } else if (*p < 32) {
            if (!append(buf, cap, used, "\\u%04x", (unsigned int)*p)) return false;
        } else if (!append(buf, cap, used, "%c", *p)) {
            return false;
        }
    }
    return append(buf, cap, used, "\"");
}

static bool emit(csi_json_sink_t sink, void *ctx, const char *buf, size_t n, size_t *total)
{
    if (sink && !sink(ctx, buf, n)) return false;
    *total += n;
    return true;
}

bool csi_batch_json(const csi_batch_meta_t *meta, const csi_batch_sample_t *samples,
                    size_t count, csi_json_sink_t sink, void *ctx, size_t *length)
{
    char buf[1536];
    size_t used = 0, total = 0;
    if (!meta || !length || (count && !samples)) return false;
    *length = 0;
    if (!append(buf, sizeof(buf), &used, "{\"schema_version\":1,\"device_id\":") ||
        !quote(buf, sizeof(buf), &used, meta->device_id) ||
        !append(buf, sizeof(buf), &used, ",\"session_id\":") ||
        !quote(buf, sizeof(buf), &used, meta->session_id) ||
        !append(buf, sizeof(buf), &used,
                ",\"batch_id\":%" PRIu32 ",\"samples\":[", meta->batch_id) ||
        !emit(sink, ctx, buf, used, &total)) return false;

    for (size_t i = 0; i < count; ++i) {
        const csi_batch_sample_t *s = &samples[i];
        if (s->len == 0 || s->len > CSI_BATCH_RAW_BYTES) return false;
        used = 0;
        if (!append(buf, sizeof(buf), &used,
                "%s{\"seq\":%" PRIu32 ",\"timestamp_us\":%" PRIu64 ","
                "\"ap_mac\":\"%02x:%02x:%02x:%02x:%02x:%02x\","
                "\"rssi_dbm\":%d,\"noise_floor_dbm\":%d,\"channel\":%u,\"bandwidth_mhz\":%u,"
                "\"first_word_invalid\":%s,\"csi_raw\":[",
                i ? "," : "", s->seq, s->timestamp_us,
                s->mac[0], s->mac[1], s->mac[2], s->mac[3], s->mac[4], s->mac[5],
                s->rssi, s->noise_floor, (unsigned int)s->channel, s->cwb ? 40U : 20U,
                s->first_word_invalid ? "true" : "false")) return false;
        for (size_t j = 0; j < s->len; ++j) {
            if (!append(buf, sizeof(buf), &used, "%s%d", j ? "," : "", s->data[j])) return false;
        }
        if (!append(buf, sizeof(buf), &used, "]}") ||
            !emit(sink, ctx, buf, used, &total)) return false;
    }
    if (!emit(sink, ctx, "]}", 2, &total)) return false;
    *length = total;
    return true;
}
