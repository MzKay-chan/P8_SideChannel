void setup() {
  Serial.begin(9600);
  pinMode(3, OUTPUT);  // Trigger pin
  
  // Wait for serial command
  while(!Serial.available());
  Serial.read();
}
#define INSTRUC_BLOCK \
  "clr r16\n\t" \
  "mov r17, %[val]\n\t" \
  "cpse r17, r16\n\t" \
  "rjmp 1f\n\t" \
  "nop\n\t" \
  "nop\n\t" \
  "nop\n\t" \
  "nop\n\t" \
  "1:\n\t"

uint8_t input_byte;

void loop() {
  while(!Serial.available());
  input_byte = Serial.read();

  PORTD |= (1 << PD3);  // trigger HIGH

asm volatile(
  INSTRUC_BLOCK
  INSTRUC_BLOCK
  INSTRUC_BLOCK
  INSTRUC_BLOCK
  INSTRUC_BLOCK
  INSTRUC_BLOCK
  INSTRUC_BLOCK
  INSTRUC_BLOCK
  INSTRUC_BLOCK
  INSTRUC_BLOCK
  INSTRUC_BLOCK

  :
  : [val] "r" (input_byte)
  : "r16", "r17"
);

  PORTD &= ~(1 << PD3); // trigger LOW
}