// Trigger is Pin 2
int triggerPin = 2;

String known_passwordstr = String("ilovecheese");
String input_passwordstr;

char input_password[20];
char tempchr;
int index;

// the setup routine runs once when you press reset:
void setup() {
    // initialize serial communication at 9600 bits per second:
    Serial.begin(9600);
    pinMode(triggerPin, OUTPUT);

    tempchr = '0';
    index = 0;
}

// the loop routine runs over and over again forever:
void loop() {

    // Wait a little bit after startup & clear everything
    digitalWrite(triggerPin, LOW);
    delay(250);

    Serial.flush();
    Serial.write("Enter Password:");

    // wait for last character
    while ((tempchr != '\n') && (index < 19)) {
        if (Serial.available() > 0) {
            tempchr = Serial.read();
            input_password[index++] = tempchr;
        }
    }

    // Null terminate and strip non-characters
    input_password[index] = '\0';
    input_passwordstr = String(input_password);
    input_passwordstr.trim();

    index = 0;
    tempchr = 0;

    digitalWrite(triggerPin, HIGH);

    if (input_passwordstr == known_passwordstr) {
        Serial.write("Password OK\n");
    } else {
        // Delay up to 500ms randomly
        delay(random(500));
        Serial.write("Password Bad\n");
    }
}