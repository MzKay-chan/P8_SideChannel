#include <Arduino.h>
#include <string.h>

#define MAX_LEN 32

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

	digitalWrite(triggerPin, HIGH);
	bool ok = checkPassword(inputPassArr, inputLen);
	digitalWrite(triggerPin, LOW);
	if (ok) {
		Serial.write("OK\n");
	} else {
		Serial.write("FAIL\n");
	}
	
}


bool checkPassword(const char* pass, size_t inputLength) {
	uint8_t diff = 0;

	size_t max = (inputLength > correctLength) ? inputLength : correctLength;

	for (size_t i = 0; i < max; i++) {
		uint8_t p = (i < inputLength) ? pass[i] : 0;
		uint8_t k = (i < correctLength) ? knownPassword[i] : 0;

		diff |= p ^ k;
	}

	return diff == 0;
}