package com.example;

import org.apache.logging.log4j.LogManager;
import org.apache.logging.log4j.Logger;

public class App {
    private static final Logger logger = LogManager.getLogger(App.class);

    public static void main(String[] args) {
        // Vulnerable: Log4Shell (CVE-2021-44228)
        // Attacker-controlled input passed directly to logger
        String userInput = args.length > 0 ? args[0] : "world";
        logger.info("Hello, " + userInput);
    }
}
