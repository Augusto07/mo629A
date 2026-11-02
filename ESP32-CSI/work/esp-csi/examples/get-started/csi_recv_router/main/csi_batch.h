#pragma once

#include "sdkconfig.h"
#if CONFIG_CSI_BATCH_POST_ENABLED
#include "esp_err.h"
#include "esp_wifi.h"
#include "ping/ping_sock.h"

esp_err_t csi_batch_start(esp_ping_handle_t ping);
void csi_batch_capture(const wifi_csi_info_t *info);
void csi_batch_ping_ended(void);
#endif
