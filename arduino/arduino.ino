#include <TimerOne.h>

// Configuration constants
const uint8_t micPin = A0;
const unsigned long sampleRate = 16000;      // 16 kHz sample rate
const unsigned long baudRate   = 1000000;    // 1 Mbaud for high-speed transfer
const int bufferSize = 256;                  // Buffer size for stable transmission
const int filterSize = 4;                    // Moving average filter size

// Volatile variables for interrupt
volatile bool readyToSample = false;
volatile int bufferIndex = 0;
volatile bool bufferReady = false;

// Buffers
uint8_t audioBuffer[bufferSize];
uint8_t transmitBuffer[bufferSize];

// Filter variables
uint16_t filterBuffer[filterSize];
uint8_t filterIndex = 0;
uint16_t filterSum = 0;

// Status variables
unsigned long lastStatusTime = 0;
unsigned long sampleCount = 0;
bool systemReady = false;

void setup() {
  // Initialize serial communication
  Serial.begin(baudRate);
  while (!Serial) {
    delay(10); // Wait for serial port to connect
  }
  
  // Configure ADC for faster readings
  // ADC Prescaler: 16 (1MHz/16 = 62.5kHz ADC clock)
  // This gives us faster ADC conversion (~13 ADC cycles = ~208μs per conversion)
  ADCSRA &= ~((1 << ADPS2) | (1 << ADPS1) | (1 << ADPS0)); // Clear prescaler bits
  ADCSRA |= (1 << ADPS2);                                    // Set prescaler to 16 (100 in binary)
  
  // Set ADC reference to AVCC (5V)
  ADMUX = (1 << REFS0);
  
  // Enable ADC
  ADCSRA |= (1 << ADEN);
  
  // Initialize filter buffer
  for (int i = 0; i < filterSize; i++) {
    filterBuffer[i] = 512; // Initialize to mid-point (2.5V for 5V reference)
    filterSum += 512;
  }
  
  // Warm up ADC and stabilize
  Serial.println("Warming up ADC...");
  for (int i = 0; i < 200; i++) {
    analogRead(micPin);
    delayMicroseconds(100);
  }
  
  // Configure Timer1 for precise 16kHz sampling
  // Timer period = 1/16000 = 62.5 microseconds
  Serial.println("Configuring timer...");
  Timer1.initialize(62);           // 62.5 μs period for 16kHz
  Timer1.attachInterrupt(onTimer);
  
  // Initialize variables
  bufferIndex = 0;
  bufferReady = false;
  sampleCount = 0;
  lastStatusTime = millis();
  systemReady = true;
  
  // Send ready signal
  Serial.println("AUDIO_READY");
  Serial.println("System initialized - 16kHz sampling active");
  
  // LED indicator (if available on pin 13)
  pinMode(13, OUTPUT);
  digitalWrite(13, HIGH); // System ready indicator
}

void loop() {
  // Check if buffer is ready to transmit
  if (bufferReady && systemReady) {
    // Disable interrupts during buffer operations
    noInterrupts();
    
    // Copy buffer for transmission
    memcpy(transmitBuffer, audioBuffer, bufferSize);
    bufferReady = false;
    bufferIndex = 0;
    
    // Update sample count
    sampleCount += bufferSize;
    
    interrupts();
    
    // Transmit buffer as fast as possible
    Serial.write(transmitBuffer, bufferSize);
    
    // Status reporting every 5 seconds
    unsigned long currentTime = millis();
    if (currentTime - lastStatusTime > 5000) {
      lastStatusTime = currentTime;
      
      // Calculate effective sample rate
      float effectiveRate = (float)sampleCount / (currentTime / 1000.0);
      
      // Send status (commented out to avoid interference with audio stream)
      // Serial.print("Rate: ");
      // Serial.print(effectiveRate);
      // Serial.println(" Hz");
      
      // Reset counter periodically to avoid overflow
      if (currentTime > 60000) { // Reset every minute
        sampleCount = 0;
        lastStatusTime = 0;
      }
    }
  }
  
  // Minimal delay to prevent overwhelming CPU
  delayMicroseconds(10);
}

// High-precision timer interrupt for 16kHz sampling
void onTimer() {
  if (!bufferReady && systemReady) {
    // Start ADC conversion
    ADCSRA |= (1 << ADSC);
    
    // Wait for conversion to complete (busy wait for precision)
    while (ADCSRA & (1 << ADSC));
    
    // Read ADC result
    uint16_t raw = ADC;
    
    // Apply moving average filter to reduce noise
    filterSum -= filterBuffer[filterIndex];
    filterBuffer[filterIndex] = raw;
    filterSum += raw;
    filterIndex = (filterIndex + 1) % filterSize;
    
    uint16_t filtered = filterSum / filterSize;
    
    // Apply simple high-pass filter to remove DC bias
    static uint16_t dcOffset = 512;
    dcOffset = (dcOffset * 15 + filtered) / 16; // Slowly track DC component
    
    int16_t acCoupled = filtered - dcOffset + 128; // Center around 128 for 8-bit
    
    // Clamp to valid range
    if (acCoupled < 0) acCoupled = 0;
    if (acCoupled > 255) acCoupled = 255;
    
    // Store sample in buffer
    audioBuffer[bufferIndex] = (uint8_t)acCoupled;
    bufferIndex++;
    
    // Check if buffer is full
    if (bufferIndex >= bufferSize) {
      bufferReady = true;
    }
  }
}

// Optional: Error recovery function
void recoverFromError() {
  systemReady = false;
  Timer1.detachInterrupt();
  
  delay(100);
  
  // Reinitialize
  bufferIndex = 0;
  bufferReady = false;
  
  Timer1.attachInterrupt(onTimer);
  systemReady = true;
  
  Serial.println("System recovered");
}