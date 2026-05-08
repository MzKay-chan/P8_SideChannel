#include <avr/io.h>
#include <avr/interrupt.h>
#include <util/delay.h>

// ── Pins ─────────────────────────────────────────────────────────────────────
// Trigger: PD3 (Arduino pin 3) — driven via direct port writes (sbi/cbi),
//          1-cycle transitions instead of digitalWrite's ~60 cycles.
// Handshake: PD2 (Arduino pin 2) — polled via digitalRead (only between traces,
//          so its overhead doesn't affect the measurement window).
#define TRIGGER_PORT    PORTD
#define TRIGGER_DDR     DDRD
#define TRIGGER_BIT     PD3
#define HANDSHAKE_PIN   2

#define N_TRACES        1800   // multiple of 256 — each byte value seen N_TRACES/256 times
#define FIXED_VAL       0xFF
#define DELAY_US        500    // settling time between traces

// ── Test variant selection ───────────────────────────────────────────────────
// Pick one variant, reflash, then update TEST_NAME in tvla.py and
// tvla_analysis.backup.py to match.
//
//   0  nop   — control: should NOT leak
//   1  mov   — register-file write only
//   2  eor   — bitwise XOR through ALU
//   3  and   — bitwise AND through ALU
//   4  or    — bitwise OR  through ALU
//   5  add   — arithmetic add  (with carry side-effect)
//   6  sub   — arithmetic sub  (with carry side-effect)
//   7  cp    — compare (flags only, no register writeback)
//   8  cpse  — compare-and-skip-if-equal (data-dependent PC)
//   9  sts   — SRAM store (heavy bus toggle)
//  10  lds   — SRAM load (val pre-stored before trigger)
//  11  mul   — hardware multiplier
//
#define TEST_VARIANT    2

// SRAM scratch byte for sts/lds tests (linker places it in RAM).
volatile uint8_t scratch __attribute__((used));

// PRE_ASM   : runs *before* the trigger goes HIGH — not measured
// OP_ASM    : the single instruction being measured
// CLOBBERS  : extra clobbers beyond "memory" (lead with comma)
//
// All variants put SBI/CBI immediately around OP_ASM so the scope window
// captures exactly that instruction, with PRE_ASM happening pre-trigger.
#if   TEST_VARIANT == 0
  #define TEST_NAME "nop"
  #define PRE_ASM   ""
  #define OP_ASM    "nop                  \n\t"
  #define CLOBBERS
#elif TEST_VARIANT == 1
  #define TEST_NAME "mov"
  #define PRE_ASM   ""
  #define OP_ASM    "mov  r16, %[v]       \n\t"
  #define CLOBBERS  , "r16"
#elif TEST_VARIANT == 2
  #define TEST_NAME "eor"
  #define PRE_ASM   "ldi  r16, 0x55       \n\t"
  #define OP_ASM    "eor  r16, %[v]       \n\t"
  #define CLOBBERS  , "r16"
#elif TEST_VARIANT == 3
  #define TEST_NAME "and"
  #define PRE_ASM   "ldi  r16, 0x55       \n\t"
  #define OP_ASM    "and  r16, %[v]       \n\t"
  #define CLOBBERS  , "r16"
#elif TEST_VARIANT == 4
  #define TEST_NAME "or"
  #define PRE_ASM   "ldi  r16, 0x55       \n\t"
  #define OP_ASM    "or   r16, %[v]       \n\t"
  #define CLOBBERS  , "r16"
#elif TEST_VARIANT == 5
  #define TEST_NAME "add"
  #define PRE_ASM   "ldi  r16, 0x55       \n\t"
  #define OP_ASM    "add  r16, %[v]       \n\t"
  #define CLOBBERS  , "r16"
#elif TEST_VARIANT == 6
  #define TEST_NAME "sub"
  #define PRE_ASM   "ldi  r16, 0x55       \n\t"
  #define OP_ASM    "sub  r16, %[v]       \n\t"
  #define CLOBBERS  , "r16"
#elif TEST_VARIANT == 7
  #define TEST_NAME "cp"
  #define PRE_ASM   "ldi  r16, 0xAA       \n\t"
  #define OP_ASM    "cp   r16, %[v]       \n\t"
  #define CLOBBERS  , "r16"
#elif TEST_VARIANT == 8
  #define TEST_NAME "cpse"
  #define PRE_ASM   "ldi  r16, 0xAA       \n\t"
  #define OP_ASM    "cpse r16, %[v]       \n\t" \
                    "nop                  \n\t"   /* skipped on equality */
  #define CLOBBERS  , "r16"
#elif TEST_VARIANT == 9
  #define TEST_NAME "sts"
  #define PRE_ASM   ""
  #define OP_ASM    "sts  %[s], %[v]      \n\t"
  #define CLOBBERS
#elif TEST_VARIANT == 10
  #define TEST_NAME "lds"
  #define PRE_ASM   "sts  %[s], %[v]      \n\t"   /* pre-store, NOT measured */
  #define OP_ASM    "lds  r16, %[s]       \n\t"
  #define CLOBBERS  , "r16"
#elif TEST_VARIANT == 11
  #define TEST_NAME "mul"
  #define PRE_ASM   "ldi  r17, 0xAA       \n\t"
  #define OP_ASM    "mul  r17, %[v]       \n\t"
  #define CLOBBERS  , "r0", "r1", "r17"
#else
  #error "Unknown TEST_VARIANT"
#endif

// ── Inlined test runner ──────────────────────────────────────────────────────
// always_inline + cli/sei + direct port writes:
//   - asm executes with interrupts off (no Timer0 ISR jitter)
//   - trigger HIGH/LOW are 1-cycle SBI/CBI instead of ~60-cycle digitalWrite
//   - run_test is inlined so no CALL/prologue/epilogue cycles between
//     wait_hs_high() and the trigger edge
static inline __attribute__((always_inline))
void run_test(uint8_t val) {
    cli();
    asm volatile (
        PRE_ASM
        "sbi  %[port], %[bit]   \n\t"   // trigger HIGH (1 cycle) — t = 0
        OP_ASM                          // measured instruction(s)
        "cbi  %[port], %[bit]   \n\t"   // trigger LOW
        :
        : [v]    "r" (val),
          [port] "I" (_SFR_IO_ADDR(TRIGGER_PORT)),
          [bit]  "I" (TRIGGER_BIT),
          [s]    "i" (&scratch)
        : "memory" CLOBBERS
    );
    sei();
}

static inline void wait_hs_high(void) { while (digitalRead(HANDSHAKE_PIN) == LOW)  { } }
static inline void wait_hs_low (void) { while (digitalRead(HANDSHAKE_PIN) == HIGH) { } }

// Generating a sequence of bytes for testing so that each HM is equally represented 
uint8_t hw_bytes[9][70];
uint8_t hw_counts[9] = {0};

void precompute_hw_table() {
    for (int b = 0; b < 256; b++) {
        uint8_t hw = __builtin_popcount(b);
        hw_bytes[hw][hw_counts[hw]++] = b;
    }
}

void setup() {
    // Trigger pin: configure as output via DDR, start LOW
    TRIGGER_DDR  |=  (1 << TRIGGER_BIT);
    TRIGGER_PORT &= ~(1 << TRIGGER_BIT);

    pinMode(HANDSHAKE_PIN, INPUT);
    pinMode(LED_BUILTIN, OUTPUT);

    // Blink while waiting — start Python during this time
    while (digitalRead(HANDSHAKE_PIN) == LOW) {
        digitalWrite(LED_BUILTIN, HIGH); delay(200);
        digitalWrite(LED_BUILTIN, LOW);  delay(200);
    }
    digitalWrite(LED_BUILTIN, HIGH); // solid = running

    // Wait for the start pulse to drop LOW so loop() begins from a known-LOW
    // state and the first wait_hs_high() handshake is not pre-satisfied.
    wait_hs_low();
}

void loop() {
    precompute_hw_table();
    
    uint8_t hw_index[9] = {0}; // round robin index per hamming weight
    int traces_per_hw = N_TRACES / 9; // 0-8 = 9 weights

    for (int i = 0; i < N_TRACES; i++) {
        // --- Fixed trace ---
        wait_hs_high();
        run_test(FIXED_VAL);
        wait_hs_low();
        _delay_us(DELAY_US);

        // --- Random trace ---
        uint8_t hw = i / traces_per_hw; // which hamming weight
        if (hw > 8) hw = 8;
        uint8_t val = hw_bytes[hw][hw_index[hw] % hw_counts[hw]];
        hw_index[hw]++;

        wait_hs_high();
        run_test(val);
        wait_hs_low();
        _delay_us(DELAY_US);
    }

    digitalWrite(LED_BUILTIN, LOW);
    while (1); // halt
}
