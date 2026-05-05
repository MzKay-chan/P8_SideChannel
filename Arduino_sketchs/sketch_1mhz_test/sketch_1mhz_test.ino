#include <Arduino.h>

const int triggerPin = 3;
String input_passwordstr = String("eeeeeeeeeee");
String known_passwordstr = String("eeeeeeeeeee");

void setup() {
  pinMode(triggerPin, OUTPUT);
}

void loop() {
    delayMicroseconds(200);
    digitalWrite(triggerPin, HIGH);
    if (input_passwordstr == known_passwordstr) {
        Serial.write("Password OK\n");
    } else {
        // Delay up to 500ms randomly
        Serial.write("Password Bad\n");
    }
    digitalWrite(triggerPin, LOW);
}