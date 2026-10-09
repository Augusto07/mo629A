#include <ESP8266WiFi.h>

const char* ssid = "ssid"; // ID da rede
const char* password = "pwd"; // PWD da rede

unsigned long ultimaLeitura = 0;
const unsigned long intervalo = 100; // Trocar aqui o polling rate

void setup() {
  Serial.begin(115200);
  delay(1000);

  WiFi.begin(ssid, password);

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
  }

  Serial.println("tempo_ms,rssi_dbm");
}

void loop() {
  if (millis() - ultimaLeitura >= intervalo) {
    ultimaLeitura = millis();

    if (WiFi.status() == WL_CONNECTED) {
      Serial.print(millis());
      Serial.print(",");
      Serial.println(WiFi.RSSI());
    }
  }
}