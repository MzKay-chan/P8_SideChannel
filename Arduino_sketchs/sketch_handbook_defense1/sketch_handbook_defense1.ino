// Trigger is Pin 2
int triggerPin = 3;

String known_passwordstr = String("ilovecheese");

// MATHIAS' PASSWORD CHECK
// The leaks should be more subtle with this algorithm.
// Sources of leakage still remaining:
// - masks beeing set to 0xFF or 0x00 is in theory possible to see on a power trace.
//   the data that is being iterated over changes abruptly at one specific iteration.
// When i < correctLength, pw_mask -> 0xFF, but when i >= correctLength, pw_mask -> 0x00
// This leak might be more subtle, but it is not gone. 
// 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00....
// It feels like im going in circles, i dont know if there is a way to keep the length FULLY secret
#define MAX_LEN 32
const char knownPassword[MAX_LEN] = "ilovecheese";
size_t correctLength = strlen(knownPassword);
bool checkPassword(const char* pass) {
	size_t inputLength = strlen(pass);
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
    
    // OLD PASS WORD CHECK
    // if (input_passwordstr == known_passwordstr) {
    bool pass_good = checkPassword(input_passwordstr.c_str());
    if (pass_good) {
        Serial.write("Password OK\n");
    } else {
        // Delay up to 500ms randomly
        Serial.write("Password Bad\n");
    }

    digitalWrite(triggerPin, LOW);
}
