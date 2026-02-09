#include "aes.hpp"

struct AES_ctx ctx;

// Your 16-byte (128-bit) key
uint8_t key[16] = {0x2b, 0x7e, 0x15, 0x16, 0x28, 0xae, 0xd2, 0xa6,
                   0xab, 0xf7, 0x15, 0x88, 0x09, 0xcf, 0x4f, 0x3c};

// Data to encrypt (must be 16 bytes for ECB mode)
uint8_t plaintext[16] = {0x6b, 0xc1, 0xbe, 0xe2, 0x2e, 0x40, 0x9f, 0x96,
                         0xe9, 0x3d, 0x7e, 0x11, 0x73, 0x93, 0x17, 0x2a};

uint8_t buffer[16];

void setup() {
  Serial.begin(9600);
  while (!Serial);
  
  // Copy plaintext to buffer (encryption works in-place)
  memcpy(buffer, plaintext, 16);
  
  Serial.println("Plaintext:");
  printHex(buffer, 16);
  
  // Initialize AES context with key
  AES_init_ctx(&ctx, key);
  
  // Encrypt (modifies buffer in-place)
  AES_ECB_encrypt(&ctx, buffer);
  
  Serial.println("Ciphertext:");
  printHex(buffer, 16);
  
  // Decrypt (modifies buffer in-place)
  AES_ECB_decrypt(&ctx, buffer);
  
  Serial.println("Decrypted:");
  printHex(buffer, 16);
}

void loop() {
}

void printHex(uint8_t* data, int length) {
  for (int i = 0; i < length; i++) {
    if (data[i] < 0x10) Serial.print("0");
    Serial.print(data[i], HEX);
    Serial.print(" ");
  }
  Serial.println();
}
