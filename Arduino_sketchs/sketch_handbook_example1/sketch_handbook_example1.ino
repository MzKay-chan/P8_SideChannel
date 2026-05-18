// Trigger is Pin 2
int triggerPin = 3;

String known_passwordstr = String("ilovecheese");


// the setup routine runs once when you press reset:
void setup() {
    // initialize serial communication at 9600 bits per second:
    Serial.begin(9600);
    pinMode(triggerPin, OUTPUT);
}

//TO clear the serial
void clearSerial(){
    while(Serial.available() > 0){
        Serial.read();
    }
}

// the loop routine runs over and over again forever:
void loop() {
    String input_passwordstr;
    char input_password[20] = {0};  // initialize all elements to null character
    char tempchr = '0';
    int index = 0;
    int timeout_count = 0;
    // We start by setting the counter to zero, this helps us send a ready signal to the serial port
    int counter = 0;
    // We try and set som delays, to ensure that we dont "overload" the serial
    const int TIMEOUT_THRESHOLD = 10000;
    const int MAX_TIMEOUT = 5;

    // Then we set the trigger to low so that it can again be set to high for the next trace
    clearSerial();
    Serial.write("Enter Password:");
    // delay(1000); // don't know if this is neceassary
    // clearSerial();

    //Then we wait for a password
    // while ((tempchr != '\n') && (index < 19)){
    //     counter ++; 
    //     if (counter > TIMEOUT_THRESHOLD) {
    //         timeout_count++;
    //         if (timeout_count >= MAX_TIMEOUT) {  // ← GIVE UP AFTER 5 TRIES
    //             Serial.println("TIMEOUT - No data received");
    //             delay(5000);  // Wait 5 seconds before trying again
    //             return;}  // Exit this loop iteratioN
    //         index = 0;
    //         clearSerial();
    //         counter = 0;}
    //     if (Serial.available() > 0) {
    //         tempchr = Serial.read();
    //         if (tempchr == '\n' || tempchr == '\r'){
    //             break;}
    //         input_password[index++] = tempchr;
    //         counter = 0;}
    //     //Small delay to avoid tight polling
    //     delayMicroseconds(100);}

    // Then we wait for a password (second attempt)
    while (input_password[index - 1] != '\n' && index < 19) {

        if (counter > TIMEOUT_THRESHOLD) {
            Serial.println("TIMEOUT - No data received. (index: " + String(index) + ") password so far:" + String(input_password));
            counter = 0;
            if (input_password[0] == '\0') {
                Serial.write("Enter Password:");
            }
        }

        while (Serial.available() > 0) {
            // Serial.println("Data received: " + String(Serial.available()) + " bytes");
            tempchr = Serial.read();
            // before we add the new char, make sure it's not a loose newline at the start of the input
            if (tempchr != '\r' && (tempchr != '\n' || index > 1)) {
                input_password[index++] = tempchr;
            }
            counter = 0;
        }

        counter++;
        delayMicroseconds(1000);
    }

    clearSerial(); // I think it should already be empty
    Serial.write("Password received\n");
    // Null terminate and strip non-characters
    input_password[index] = '\0';
    input_passwordstr = String(input_password);
    input_passwordstr.trim();

    //String length comparison
    //for (int i = 0; i < known_passwordstr.length(); i++) {
    //    if (input_passwordstr[i] != known_passwordstr[i]) return false;  // early exit!
    //}
    // return true;

    digitalWrite(triggerPin, HIGH);
    
    if (input_passwordstr == known_passwordstr) {
        Serial.write("Password OK\n");
    } else {
        // Delay up to 500ms randomly
        Serial.write("Password Bad\n");
    }

    digitalWrite(triggerPin, LOW);
}
