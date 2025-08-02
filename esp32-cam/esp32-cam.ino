#include "esp_camera.h"
#include <WiFi.h>
#include <WebServer.h>

// WiFi credentials - CHANGE THESE!
const char* ssid     = "Saleh";
const char* password = "saleh100";

WebServer server(80);

// Pin definition for CAMERA_MODEL_AI_THINKER
#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM      0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27
#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM        5
#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22

void handleStream() {
  WiFiClient client = server.client();
  String response = 
    "HTTP/1.1 200 OK\r\n"
    "Content-Type: multipart/x-mixed-replace; boundary=frame\r\n\r\n";
  server.sendContent(response);

  while (true) {
    camera_fb_t * fb = esp_camera_fb_get();
    if (!fb) break;
    String partHeader = 
      "--frame\r\n"
      "Content-Type: image/jpeg\r\n"
      "Content-Length: " + String(fb->len) + "\r\n\r\n";
    server.sendContent(partHeader);
    client.write(fb->buf, fb->len);
    server.sendContent("\r\n");
    esp_camera_fb_return(fb);
    // allow client to abort
    if (!client.connected()) break;
  }
}

void setup(){
  Serial.begin(115200);
  Serial.println("ESP32-CAM Starting...");
  
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer   = LEDC_TIMER_0;
  config.pin_d0       = Y2_GPIO_NUM;
  config.pin_d1       = Y3_GPIO_NUM;
  config.pin_d2       = Y4_GPIO_NUM;
  config.pin_d3       = Y5_GPIO_NUM;
  config.pin_d4       = Y6_GPIO_NUM;
  config.pin_d5       = Y7_GPIO_NUM;
  config.pin_d6       = Y8_GPIO_NUM;
  config.pin_d7       = Y9_GPIO_NUM;
  config.pin_xclk     = XCLK_GPIO_NUM;
  config.pin_pclk     = PCLK_GPIO_NUM;
  config.pin_vsync    = VSYNC_GPIO_NUM;
  config.pin_href     = HREF_GPIO_NUM;
  config.pin_sscb_sda = SIOD_GPIO_NUM;
  config.pin_sscb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn     = PWDN_GPIO_NUM;
  config.pin_reset    = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;
  config.frame_size   = FRAMESIZE_VGA;    // 640×480 for good speed/quality
  config.jpeg_quality = 12;               // 0–63 lower means higher quality
  config.fb_count     = 2;
  
  // Init camera
  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("Camera init failed with error 0x%x", err);
    return;
  }
  
  Serial.println("Camera initialized successfully");
  
  // Connect Wi-Fi
  WiFi.begin(ssid, password);
  Serial.print("Connecting to WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println();
  Serial.print("Ready! Stream at http://");
  Serial.print(WiFi.localIP());
  Serial.println("/stream");
  
  // Routes
  server.on("/", [](){
    String html = "<html><head><title>ESP32-CAM</title></head><body>";
    html += "<h1>ESP32-CAM Live Stream</h1>";
    html += "<img src='/stream' style='width:100%;max-width:800px;'>";
    html += "</body></html>";
    server.send(200, "text/html", html);
  });
  
  server.on("/stream", HTTP_GET, handleStream);
  server.begin();
  
  Serial.println("HTTP server started");
}

void loop(){
  server.handleClient();
}