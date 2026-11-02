idf_component_register(SRC_DIRS "."
                       INCLUDE_DIRS "."
                       PRIV_REQUIRES esp_http_client esp_timer mbedtls esp_wifi
                                     esp_netif esp_event nvs_flash lwip esp_rom
                                     esp_hw_support heap freertos log
                                     protocol_examples_common)
