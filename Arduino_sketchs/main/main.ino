#include <Arduino.h>
#include <string.h>

#define MAX_LEN 32

bool checkPassword(const char* pass, size_t inputLength);

uint8_t triggerPin = 3;

const char knownPassword[MAX_LEN] = "ilovecheese";
size_t correctLength = strlen(knownPassword);
char inputPassArr[MAX_LEN];
char tempChar;
int index;

void setup() {
	delay(2000);
	// initialize serial communication
	Serial.begin(9600);
	pinMode(triggerPin, OUTPUT);

	tempChar = 0;
	index = 0;
}

void loop() {
	index = 0;
	tempChar = 0;

	memset(inputPassArr, 0, MAX_LEN);
	digitalWrite(triggerPin, LOW); // Set the triggerpin to low at the start
	delay(250);

	Serial.write("Enter password: "); 

	while (index < MAX_LEN - 1) {
		if (Serial.available() > 0 ) {
			tempChar = Serial.read();

			if (tempChar == '\r') continue;

			if (tempChar == '\n') break;

			inputPassArr[index++] = tempChar;
		}
	}

	inputPassArr[index] = '\0';

	if (index > 0 && inputPassArr[index - 1] == '\n') {
		inputPassArr[index - 1] = '\0';
	}

	size_t inputLen = strlen(inputPassArr);

	digitalWrite(triggerPin, HIGH);
	bool ok = checkPassword(inputPassArr, inputLen);
	digitalWrite(triggerPin, LOW);
	if (ok) {
		Serial.write("OK\n");
	} else {
		Serial.write("FAIL\n");
	}
	
}

// The leaks should be more subtle with this algorithm.
// Sources of leakage still remaining:
// - masks beeing set to 0xFF or 0x00 is in theory possible to see on a power trace.
//   the data that is being iterated over changes abruptly at one specific iteration.
// When i < correctLength, pw_mask -> 0xFF, but when i >= correctLength, pw_mask -> 0x00
// This leak might be more subtle, but it is not gone. 
// 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00....
// It feels like im going in circles, i dont know if there is a way to keep the length FULLY secret
bool checkPassword(const char* pass, size_t inputLength) {
	uint8_t diff = 0;

	for (size_t i = 0; i < MAX_LEN; i++) {
		// in_mask = 0xFF if i < inputLength, else 0x00
		uint8_t in_mask = (uint8_t)((i - inputLength) >> 8);
		// pw_mask = 0xFF if i < correctLength, else 0x00
		uint8_t pw_mask = (uint8_t)((i - correctLength) >> 8);

		// If i < inputLength:
		//   in_mask = 0xFF -> p = pass[i]
		// Else:
		//   in_mask = 0x00 -> p = 0
		uint8_t p = ((uint8_t)pass[i]) & in_mask;
		// If i < correctLength:
		//   pw_mask = 0xFF -> k = knownPassword[i]
		// Else:
		//   pw_mask = 0x00 -> k = 0
		uint8_t k = ((uint8_t)knownPassword[i]) & pw_mask;

		// If p == k, p^k -> 0
		diff |= p ^ k; // Data-dependent (possible leak)
	}

	return diff == 0;
}

// Jakob’s suggestion -- LEAK‼️
// the loops to add the input and known password to the padded arrays sum to inputLength + correctLength
// sum = inputLength + correctLength
// The attacker knows inputLength, and they can read the sum from the power traces. 
bool checkPassword_1(const char* pass, size_t inputLength) {
	uint8_t paddedInput[MAX_LEN] = {0};
	uint8_t paddedPassword[MAX_LEN] = {0};

	// Copy input
	for (size_t i = 0; i < inputLength && i < MAX_LEN; i++) {
		paddedInput[i] = (uint8_t)pass[i];
	}

	// Copy known password
	for (size_t i = 0; i < correctLength && i < MAX_LEN; i++) { 
		paddedPassword[i] = (uint8_t)knownPassword[i];
	}

	uint8_t diff = 0;

	// XOR all characters
	for (size_t i = 0; i < MAX_LEN; i++) {
		diff |= paddedInput[i] ^ paddedPassword[i];
	}

	// XOR lengths
	diff |= (uint8_t)(inputLength ^ correctLength);

	return diff == 0;
}

// Leaks length
bool checkPassword_0(const char* pass, size_t inputLength) {
	uint8_t diff = 0;

	// max is the larger of the two lengths ------ LEAK‼️
	size_t max = (inputLength > correctLength) ? inputLength : correctLength;

	for (size_t i = 0; i < max; i++) {
		// If i is in the range of the input length, p = the character at i
		uint8_t p = (i < inputLength) ? pass[i] : 0;
		// If i is in the range of the known length, k = the character at i
		uint8_t k = (i < correctLength) ? knownPassword[i] : 0;

		// If p == k, p^k -> 0
		diff |= p ^ k;
	}

	return diff == 0;
}