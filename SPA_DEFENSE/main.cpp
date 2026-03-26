#include <Arduino.h>
#include <string.h>

// put function declarations here:
#define MAX_LEN 20

bool checkPassword(const char* pass, size_t inputLength);

uint8_t triggerPin = 3;

const char knownPassword[] = "ilovecheese";
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


	// activate trigger pin before password check

	digitalWrite(triggerPin, HIGH);
	bool ok = checkPassword(inputPassArr, inputLen);
	digitalWrite(triggerPin, LOW);
	if (ok) {
		Serial.write("OK\n");
	} else {
		Serial.write("FAIL\n");
	}
	
}

// WHAT TO DO????	
bool checkPassword(const char* pass, size_t inputLength) {
	// size_t inputLength = strlen(pass);
	// uint16_t count = 0;
	// uint16_t dummy_count = 0;

	uint8_t diff = 0;
	// uint8_t len_diff = 0;

	// len_diff = (uint8_t)(inputLength ^ correctLength);

	size_t max = (inputLength > correctLength) ? inputLength : correctLength;

	for (size_t i = 0; i < max; i++) {
		// uint8_t input_mask = (uint8_t)((i - inputLength) >> 8);

		// uint8_t pass_mask = (uint8_t)((i - correctLength) >> 8);

		// uint8_t p = pass[i] & input_mask;
		// uint8_t k = knownPassword[i] & pass_mask;

		uint8_t p = (i < inputLength) ? pass[i] : 0;
		uint8_t k = (i < correctLength) ? knownPassword[i] : 0;

		diff |= p ^ k;
	}

	return diff == 0;
	// return (diff | len_diff) == 0;


    // CHECK PASSWORD WITHOUT LEAKING ANY INFORMATION.
	// for (uint16_t i = 0; i < inputLength; i++) {
	// 	if (pass[i] == knownPassword[i % (correctLength + 1)]) {
	// 		count++;
	// 	}
	// 	else {
	// 		count += correctLength + 1;
	// 	}
	// }

	// if (count == correctLength) return true; else return false;


}