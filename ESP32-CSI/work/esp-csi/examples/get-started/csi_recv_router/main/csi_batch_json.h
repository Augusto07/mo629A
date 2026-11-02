#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* ESP32 LLTF-only configuration in this example produces 128 raw bytes. */
#define CSI_BATCH_RAW_BYTES 128

typedef struct {
    uint64_t timestamp_us;
    uint32_t seq;
    uint32_t rx_timestamp_us;
    uint16_t len;
    uint16_t sig_len;
    uint8_t mac[6];
    int8_t rssi, noise_floor;
    uint8_t channel, cwb, rate, sig_mode, mcs;
    uint8_t smoothing, not_sounding, aggregation, stbc, fec_coding, sgi;
    uint8_t ampdu_cnt, secondary_channel, ant, first_word_invalid;
    int8_t data[CSI_BATCH_RAW_BYTES];
} csi_batch_sample_t;

typedef struct {
    const char *device_id;
    const char *session_id;
    uint32_t batch_id;
    uint64_t window_started_us, window_ended_us;
    uint32_t dropped_samples_total, discarded_batches_total;
} csi_batch_meta_t;

typedef bool (*csi_json_sink_t)(void *ctx, const char *data, size_t len);

/* NULL sink counts bytes only. Fixed working storage; no JSON tree or heap. */
bool csi_batch_json(const csi_batch_meta_t *meta, const csi_batch_sample_t *samples,
                    size_t count, csi_json_sink_t sink, void *ctx, size_t *length);
