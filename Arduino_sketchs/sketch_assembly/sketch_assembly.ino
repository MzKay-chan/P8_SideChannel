#include <avr/io.h>
#include <util/delay.h>

#define TRIGGER_PIN  3
#define START_PIN    2
#define N_TRACES     2000
#define FIXED_VAL    0xFF
#define DELAY_US     500   // settling time between traces

// Galois LFSR — same seed as Python side
uint8_t lfsr_state = 0xAC;

uint8_t lfsr_next(void) {
    uint8_t lsb = lfsr_state & 0x01;
    lfsr_state >>= 1;
    if (lsb) lfsr_state ^= 0xB8;
    return lfsr_state;
}

void run_test(uint8_t val) {
    asm volatile(
        "mov  r16, %[v]   \n\t"
        "clr  r17         \n\t"
        "cpse r16, r17    \n\t"
        "rjmp 1f          \n\t"
        "nop              \n\t"
        "1:               \n\t"
        : : [v] "r" (val) : "r16", "r17"
    );
}

void setup() {
    pinMode(TRIGGER_PIN, OUTPUT);
    pinMode(START_PIN, INPUT);
    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(TRIGGER_PIN, LOW);

    // Blink while waiting — start Python during this time
    while (digitalRead(START_PIN) == LOW) {
        digitalWrite(LED_BUILTIN, HIGH); delay(200);
        digitalWrite(LED_BUILTIN, LOW);  delay(200);
    }
    digitalWrite(LED_BUILTIN, HIGH); // solid = running
}

void loop() {
    for (int i = 0; i < N_TRACES; i++) {

        // --- Fixed trace ---
        digitalWrite(TRIGGER_PIN, HIGH);
        run_test(FIXED_VAL);
        digitalWrite(TRIGGER_PIN, LOW);
        _delay_us(DELAY_US);

        // --- Random trace ---
        uint8_t val = lfsr_next();
        digitalWrite(TRIGGER_PIN, HIGH);
        run_test(val);
        digitalWrite(TRIGGER_PIN, LOW);
        _delay_us(DELAY_US);
    }

    // Done — solid LED off, done blinking
    digitalWrite(LED_BUILTIN, LOW);
    while (1); // halt
}